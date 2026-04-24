"""
StateBench Compiler

Compiles a YAML policy definition into a callable decision function.
The decision function takes a scenario dict and returns the decision
from the highest-priority matching rule.
"""

from __future__ import annotations

import yaml
import re
from typing import Any, Callable


class PolicyCompileError(Exception):
    pass


class CompiledPolicy:
    """A compiled policy that can evaluate scenarios."""

    def __init__(self, rules: list[dict], definitions: dict):
        self.rules = sorted(rules, key=lambda r: r["priority"], reverse=True)
        self.definitions = definitions
        self._compiled_conditions = {}
        self._compile_all()

    def _compile_all(self):
        """Pre-compile all rule conditions into callable predicates."""
        for rule in self.rules:
            predicates = []
            for cond_str in rule.get("conditions", []):
                pred = self._compile_condition(cond_str)
                predicates.append(pred)
            self._compiled_conditions[rule["id"]] = predicates

    def _compile_condition(self, cond_str: str) -> Callable[[dict], bool]:
        """Compile a single condition string into a callable predicate."""
        # Substitute definitions: {var_name} -> value
        resolved = cond_str
        for key, val in self.definitions.items():
            placeholder = "{" + key + "}"
            if placeholder in resolved:
                resolved = resolved.replace(placeholder, repr(val))

        def predicate(scenario: dict) -> bool:
            try:
                return bool(eval(resolved, {"__builtins__": {}}, scenario))
            except Exception:
                return False

        return predicate

    def evaluate(self, scenario: dict) -> dict:
        """
        Evaluate a scenario against the policy.
        Returns the decision from the highest-priority matching rule.
        """
        matched_rules = []
        for rule in self.rules:
            conditions = self._compiled_conditions[rule["id"]]
            if not conditions:
                # Empty conditions = default/fallback rule
                matched_rules.append(rule)
                continue
            if all(pred(scenario) for pred in conditions):
                matched_rules.append(rule)

        if not matched_rules:
            return {"decision": "no_match", "rule_id": None, "priority": -1}

        # Highest priority wins (rules already sorted desc by priority)
        winner = matched_rules[0]
        return {
            "decision": winner["decision"],
            "rule_id": winner["id"],
            "priority": winner["priority"],
        }

    def get_rule_ids(self) -> list[str]:
        return [r["id"] for r in self.rules]

    def get_rule(self, rule_id: str) -> dict | None:
        for r in self.rules:
            if r["id"] == rule_id:
                return r
        return None


def compile_policy(policy_yaml: str) -> CompiledPolicy:
    """Compile a YAML policy string into a CompiledPolicy."""
    try:
        data = yaml.safe_load(policy_yaml)
    except yaml.YAMLError as e:
        raise PolicyCompileError(f"Invalid YAML: {e}")

    if not isinstance(data, dict):
        raise PolicyCompileError("Policy must be a YAML mapping")

    definitions = data.get("definitions", {})
    rules = data.get("rules", [])

    if not rules:
        raise PolicyCompileError("Policy must contain at least one rule")

    # Validate rules
    for rule in rules:
        if "id" not in rule:
            raise PolicyCompileError(f"Rule missing 'id': {rule}")
        if "decision" not in rule:
            raise PolicyCompileError(f"Rule '{rule['id']}' missing 'decision'")
        if "priority" not in rule:
            raise PolicyCompileError(f"Rule '{rule['id']}' missing 'priority'")
        if "conditions" not in rule:
            rule["conditions"] = []

    # Check for duplicate IDs
    ids = [r["id"] for r in rules]
    dupes = [i for i in ids if ids.count(i) > 1]
    if dupes:
        raise PolicyCompileError(f"Duplicate rule IDs: {set(dupes)}")

    # Check for duplicate priorities
    priorities = [r["priority"] for r in rules]
    dupe_prios = [p for p in priorities if priorities.count(p) > 1]
    if dupe_prios:
        raise PolicyCompileError(f"Duplicate priorities: {set(dupe_prios)}")

    return CompiledPolicy(rules, definitions)


def compile_policy_file(path: str) -> CompiledPolicy:
    """Compile a YAML policy file."""
    with open(path) as f:
        return compile_policy(f.read())


# --- Static checks ---

def check_references(policy_yaml: str) -> list[str]:
    """Check for dangling override references."""
    data = yaml.safe_load(policy_yaml)
    rules = data.get("rules", [])
    ids = {r["id"] for r in rules}
    issues = []
    for rule in rules:
        for ref in rule.get("overrides", []):
            if ref not in ids:
                issues.append(f"Rule '{rule['id']}' overrides non-existent rule '{ref}'")
    return issues


def check_contradictions(policy: CompiledPolicy) -> list[str]:
    """Check for rules with identical conditions but different decisions."""
    issues = []
    for i, r1 in enumerate(policy.rules):
        for r2 in policy.rules[i+1:]:
            if (r1.get("conditions") == r2.get("conditions")
                    and r1["decision"] != r2["decision"]
                    and r1["conditions"]):  # skip empty-condition defaults
                issues.append(
                    f"Rules '{r1['id']}' and '{r2['id']}' have same conditions "
                    f"but different decisions (resolved by priority)"
                )
    return issues


if __name__ == "__main__":
    # Quick smoke test
    policy = compile_policy_file("examples/refund_policy_v1.yaml")
    print(f"Compiled {len(policy.rules)} rules")
    print(f"Rule IDs: {policy.get_rule_ids()}")

    # Test scenarios
    scenarios = [
        {"purchase_age_days": 10, "item_condition": "unopened", "item_price": 50,
         "customer_tier": "bronze", "is_final_sale": False},
        {"purchase_age_days": 60, "item_condition": "defective", "item_price": 50,
         "customer_tier": "bronze", "is_final_sale": False},
        {"purchase_age_days": 10, "item_condition": "unopened", "item_price": 800,
         "customer_tier": "bronze", "is_final_sale": False},
        {"purchase_age_days": 10, "item_condition": "unopened", "item_price": 800,
         "customer_tier": "platinum", "is_final_sale": False},
        {"purchase_age_days": 10, "item_condition": "unopened", "item_price": 50,
         "customer_tier": "platinum", "is_final_sale": True},
    ]

    for s in scenarios:
        result = policy.evaluate(s)
        print(f"\nScenario: {s}")
        print(f"  -> {result['decision']} (rule: {result['rule_id']}, pri: {result['priority']})")
