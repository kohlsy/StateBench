"""
StateBench Scenario Generator & Verifier

Generates random scenarios to test behavioral equivalence between
a gold policy and a candidate policy, and produces detailed failure labels.
"""

from __future__ import annotations

import random
import yaml
from typing import Any
from compiler import compile_policy, CompiledPolicy, check_references


# --- Schema extraction ---

def extract_schema(policy_yaml: str) -> dict:
    """
    Extract the implicit schema from a policy: what variables are used
    in conditions, and what values/ranges they can take.
    """
    data = yaml.safe_load(policy_yaml)
    definitions = data.get("definitions", {})
    rules = data.get("rules", [])

    # Collect all variable references from conditions
    variables = {}
    for rule in rules:
        for cond in rule.get("conditions", []):
            _extract_vars_from_condition(cond, definitions, variables)

    return variables


def _extract_vars_from_condition(cond: str, definitions: dict, variables: dict):
    """Parse a condition string to extract variable names and plausible value ranges."""
    import re

    # Substitute definitions first
    resolved = cond
    for key, val in definitions.items():
        resolved = resolved.replace("{" + key + "}", repr(val))

    # Pattern: var < number, var > number, var == value, var in [list]
    # Numeric comparison: var < N or var > N
    m = re.match(r"(\w+)\s*([<>]=?)\s*(\d+)", resolved)
    if m:
        var, op, val = m.group(1), m.group(2), int(m.group(3))
        if var not in variables:
            variables[var] = {"type": "numeric", "min": 0, "max": val * 3}
        else:
            variables[var]["max"] = max(variables[var].get("max", 0), val * 3)
        return

    # Equality: var == 'value' or var == True/False
    m = re.match(r"(\w+)\s*==\s*'(\w+)'", resolved)
    if m:
        var, val = m.group(1), m.group(2)
        if var not in variables:
            variables[var] = {"type": "categorical", "values": {val}}
        else:
            variables[var].setdefault("values", set()).add(val)
        return

    # Boolean: var == True / var == False
    m = re.match(r"(\w+)\s*==\s*(True|False)", resolved)
    if m:
        var = m.group(1)
        variables[var] = {"type": "boolean"}
        return

    # Membership: var in ['a', 'b', 'c']
    m = re.match(r"(\w+)\s+in\s+\[(.+)\]", resolved)
    if m:
        var = m.group(1)
        vals_str = m.group(2)
        vals = re.findall(r"'(\w+)'", vals_str)
        if var not in variables:
            variables[var] = {"type": "categorical", "values": set(vals)}
        else:
            variables[var].setdefault("values", set()).update(vals)
        return


def generate_scenarios(policy_yaml: str, n: int = 1000, seed: int = 42) -> list[dict]:
    """Generate n random scenarios based on the policy's implicit schema."""
    rng = random.Random(seed)
    schema = extract_schema(policy_yaml)

    # Add some out-of-range values to catch edge cases
    scenarios = []
    for _ in range(n):
        scenario = {}
        for var, info in schema.items():
            if info["type"] == "numeric":
                lo, hi = info.get("min", 0), info.get("max", 100)
                # Mix of in-range and boundary values
                if rng.random() < 0.2:
                    scenario[var] = rng.choice([lo, hi, lo - 1, hi + 1])
                else:
                    scenario[var] = rng.randint(lo, hi)
            elif info["type"] == "categorical":
                vals = list(info["values"])
                # Occasionally inject an unseen value
                if rng.random() < 0.1:
                    scenario[var] = "unknown_value"
                else:
                    scenario[var] = rng.choice(vals)
            elif info["type"] == "boolean":
                scenario[var] = rng.choice([True, False])
        scenarios.append(scenario)
    return scenarios


# --- Verifier ---

class VerificationResult:
    """Result of comparing gold vs candidate policy behavior."""

    def __init__(self):
        self.total = 0
        self.matches = 0
        self.mismatches = []
        self.failure_labels = {}  # category -> count

    @property
    def score(self) -> float:
        return self.matches / self.total if self.total > 0 else 0.0

    @property
    def pass_rate(self) -> float:
        return self.score

    def add_match(self):
        self.total += 1
        self.matches += 1

    def add_mismatch(self, scenario: dict, gold_result: dict, candidate_result: dict, label: str):
        self.total += 1
        self.mismatches.append({
            "scenario": scenario,
            "gold": gold_result,
            "candidate": candidate_result,
            "failure_label": label,
        })
        self.failure_labels[label] = self.failure_labels.get(label, 0) + 1

    def summary(self) -> dict:
        return {
            "total_scenarios": self.total,
            "matches": self.matches,
            "mismatches": len(self.mismatches),
            "score": round(self.score, 4),
            "failure_breakdown": dict(self.failure_labels),
        }


def classify_mismatch(gold: dict, candidate: dict, gold_policy: CompiledPolicy,
                      candidate_policy: CompiledPolicy) -> str:
    """Classify the type of mismatch for failure labeling."""
    g_rule = gold["rule_id"]
    c_rule = candidate["rule_id"]
    g_dec = gold["decision"]
    c_dec = candidate["decision"]

    # Check if candidate used a rule that doesn't exist
    if c_rule and not candidate_policy.get_rule(c_rule):
        return "phantom_rule"

    # Check if candidate missed a rule that should have fired
    if g_rule and c_rule is None:
        return "missed_rule"

    # Check if the gold rule was higher priority but candidate picked lower
    if gold["priority"] > candidate["priority"]:
        return "wrong_priority"

    if gold["priority"] < candidate["priority"]:
        return "stale_rule_retained"

    # Different decisions at same priority level
    if g_dec != c_dec:
        return "wrong_decision"

    # Different rule at same priority
    if g_rule != c_rule:
        return "wrong_rule_selection"

    return "unknown_mismatch"


def verify_behavioral_equivalence(
    gold_yaml: str,
    candidate_yaml: str,
    n_scenarios: int = 1000,
    seed: int = 42,
) -> VerificationResult:
    """
    Core verifier: compile both policies, run scenarios, compare behavior.
    Returns detailed results with failure labels.
    """
    gold_policy = compile_policy(gold_yaml)
    candidate_policy = compile_policy(candidate_yaml)

    # Generate scenarios from gold policy schema
    scenarios = generate_scenarios(gold_yaml, n=n_scenarios, seed=seed)

    result = VerificationResult()
    for scenario in scenarios:
        gold_out = gold_policy.evaluate(scenario)
        cand_out = candidate_policy.evaluate(scenario)

        if gold_out["decision"] == cand_out["decision"]:
            result.add_match()
        else:
            label = classify_mismatch(gold_out, cand_out, gold_policy, candidate_policy)
            result.add_mismatch(scenario, gold_out, cand_out, label)

    return result


def find_counterexample(
    gold_yaml: str,
    candidate_yaml: str,
    n_scenarios: int = 5000,
    seed: int = 99,
) -> dict | None:
    """
    Find a single counterexample where gold and candidate disagree.
    Returns the first mismatch found, or None if equivalent.
    """
    gold_policy = compile_policy(gold_yaml)
    candidate_policy = compile_policy(candidate_yaml)
    scenarios = generate_scenarios(gold_yaml, n=n_scenarios, seed=seed)

    for scenario in scenarios:
        gold_out = gold_policy.evaluate(scenario)
        cand_out = candidate_policy.evaluate(scenario)
        if gold_out["decision"] != cand_out["decision"]:
            return {
                "scenario": scenario,
                "expected_decision": gold_out["decision"],
                "expected_rule": gold_out["rule_id"],
                "actual_decision": cand_out["decision"],
                "actual_rule": cand_out["rule_id"],
            }
    return None


# --- Static checks ---

def run_static_checks(policy_yaml: str) -> list[str]:
    """Run all static checks on a policy."""
    issues = []

    # Reference check
    issues.extend(check_references(policy_yaml))

    # Compile check
    try:
        policy = compile_policy(policy_yaml)
    except Exception as e:
        issues.append(f"Compilation failed: {e}")
        return issues

    return issues


if __name__ == "__main__":
    # Demo: verify a policy against itself (should be 100%)
    with open("examples/refund_policy_v1.yaml") as f:
        policy_yaml = f.read()

    print("=== Self-verification (should be 100%) ===")
    result = verify_behavioral_equivalence(policy_yaml, policy_yaml)
    print(result.summary())

    print("\n=== Static checks ===")
    issues = run_static_checks(policy_yaml)
    print(f"Issues: {issues if issues else 'None'}")

    print("\n=== Scenario examples ===")
    scenarios = generate_scenarios(policy_yaml, n=5, seed=0)
    policy = compile_policy(policy_yaml)
    for s in scenarios:
        r = policy.evaluate(s)
        print(f"  {s} -> {r['decision']} ({r['rule_id']})")
