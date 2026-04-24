"""
StateBench Task Generator — Final Edition

Update descriptions use uniform business-memo language with no operation-type fingerprints.
YAML rule IDs are neutral sequential labels (r001, r002, ...).
No semantic rule names or descriptions exposed in YAML output.
overrides field is kept — it is part of the policy artifact the agent maintains.
"""

from __future__ import annotations

import re
import random
import yaml
import copy
from typing import Any


# ---------------------------------------------------------------------------
# Domain templates
# ---------------------------------------------------------------------------

DOMAINS = {
    "refund": {
        "description": "Customer refund/return policy",
        "variables": {
            "purchase_age_days": {"type": "numeric", "range": [0, 365]},
            "item_price":        {"type": "numeric", "range": [0, 2000]},
            "item_condition":    {"type": "categorical", "values": ["unopened", "opened", "defective", "damaged"]},
            "customer_tier":     {"type": "categorical", "values": ["bronze", "silver", "gold", "platinum"]},
            "is_final_sale":     {"type": "boolean"},
            "purchase_channel":  {"type": "categorical", "values": ["online", "in_store", "phone"]},
        },
        "decisions": ["approve_refund", "deny_refund", "escalate_to_manager",
                      "offer_store_credit", "request_documentation"],
        "definition_templates": {
            "standard_window":   [14, 30, 45, 60],
            "extended_window":   [60, 90, 120],
            "max_refund_amount": [100, 250, 500, 1000],
        },
    },
    "approval": {
        "description": "Expense/procurement approval policy",
        "variables": {
            "amount":          {"type": "numeric", "range": [0, 100000]},
            "department":      {"type": "categorical", "values": ["engineering", "sales", "marketing", "ops", "legal"]},
            "requester_level": {"type": "categorical", "values": ["intern", "ic", "manager", "director", "vp"]},
            "expense_type":    {"type": "categorical", "values": ["travel", "software", "hardware", "consulting", "training"]},
            "is_budgeted":     {"type": "boolean"},
            "is_recurring":    {"type": "boolean"},
        },
        "decisions": ["auto_approve", "manager_approval", "director_approval", "vp_approval", "deny"],
        "definition_templates": {
            "auto_approve_limit": [100, 250, 500],
            "manager_limit":      [1000, 2500, 5000],
            "director_limit":     [10000, 25000, 50000],
        },
    },
    "access_control": {
        "description": "System access control policy",
        "variables": {
            "user_role":                {"type": "categorical", "values": ["viewer", "editor", "admin", "superadmin"]},
            "resource_sensitivity":     {"type": "categorical", "values": ["public", "internal", "confidential", "restricted"]},
            "is_during_business_hours": {"type": "boolean"},
            "has_mfa":                  {"type": "boolean"},
            "account_age_days":         {"type": "numeric", "range": [0, 730]},
            "failed_login_count":       {"type": "numeric", "range": [0, 20]},
        },
        "decisions": ["grant_access", "deny_access", "require_mfa", "require_approval", "temporary_lock"],
        "definition_templates": {
            "new_account_threshold": [7, 14, 30],
            "lockout_threshold":     [3, 5, 10],
            "mfa_grace_period":      [30, 60, 90],
        },
    },
    "escalation": {
        "description": "Support ticket escalation policy",
        "variables": {
            "ticket_age_hours":     {"type": "numeric", "range": [0, 168]},
            "customer_tier":        {"type": "categorical", "values": ["free", "starter", "pro", "enterprise"]},
            "severity":             {"type": "categorical", "values": ["low", "medium", "high", "critical"]},
            "is_revenue_impacting": {"type": "boolean"},
            "previous_escalations": {"type": "numeric", "range": [0, 5]},
            "is_security_related":  {"type": "boolean"},
        },
        "decisions": ["no_action", "escalate_l2", "escalate_l3", "escalate_manager", "page_oncall"],
        "definition_templates": {
            "sla_low":      [48, 72, 96],
            "sla_medium":   [24, 36, 48],
            "sla_high":     [4, 8, 12],
            "sla_critical": [1, 2, 4],
        },
    },
}


# ---------------------------------------------------------------------------
# Ambiguity filter
# ---------------------------------------------------------------------------

VAGUE_WORDS = [
    "generally", "usually", "where appropriate", "more selective",
    "handle similarly", "stricter", "looser", "should be favored",
    "where possible", "as needed", "when applicable", "in some cases",
    "may be", "might", "could be", "at your discretion",
]


def _ambiguity_ok(desc: str) -> bool:
    dl = desc.lower()
    return not any(w in dl for w in VAGUE_WORDS)


# ---------------------------------------------------------------------------
# Natural language helpers
# ---------------------------------------------------------------------------

VAR_LABELS = {
    "purchase_age_days":        "purchase age (in days)",
    "item_price":               "item price",
    "item_condition":           "item condition",
    "customer_tier":            "customer tier",
    "is_final_sale":            "final sale status",
    "purchase_channel":         "purchase channel",
    "amount":                   "request amount",
    "department":               "department",
    "requester_level":          "requester level",
    "expense_type":             "expense type",
    "is_budgeted":              "budget status",
    "is_recurring":             "recurring flag",
    "user_role":                "user role",
    "resource_sensitivity":     "resource sensitivity",
    "is_during_business_hours": "business hours flag",
    "has_mfa":                  "MFA status",
    "account_age_days":         "account age (in days)",
    "failed_login_count":       "failed login count",
    "ticket_age_hours":         "ticket age (in hours)",
    "severity":                 "severity level",
    "is_revenue_impacting":     "revenue impact flag",
    "previous_escalations":     "previous escalation count",
    "is_security_related":      "security classification",
}

DECISION_LABELS = {
    "approve_refund":        "approve the refund",
    "deny_refund":           "deny the refund",
    "escalate_to_manager":   "escalate to a manager",
    "offer_store_credit":    "offer store credit",
    "request_documentation": "request documentation",
    "auto_approve":          "auto-approve the request",
    "manager_approval":      "require manager approval",
    "director_approval":     "require director approval",
    "vp_approval":           "require VP approval",
    "deny":                  "deny the request",
    "grant_access":          "grant access",
    "deny_access":           "deny access",
    "require_mfa":           "require MFA verification",
    "require_approval":      "require explicit approval",
    "temporary_lock":        "temporarily lock the account",
    "no_action":             "take no action",
    "escalate_l2":           "escalate to L2 support",
    "escalate_l3":           "escalate to L3 support",
    "escalate_manager":      "escalate to manager",
    "page_oncall":           "page the on-call engineer",
}

DEFINITION_LABELS = {
    "standard_window":       "standard return window (days)",
    "extended_window":       "extended return window (days)",
    "max_refund_amount":     "maximum refundable amount",
    "auto_approve_limit":    "auto-approval spending limit",
    "manager_limit":         "manager approval spending limit",
    "director_limit":        "director approval spending limit",
    "new_account_threshold": "new account grace period (days)",
    "lockout_threshold":     "failed-login lockout threshold",
    "mfa_grace_period":      "MFA grace period (days)",
    "sla_low":               "SLA for low-severity tickets (hours)",
    "sla_medium":            "SLA for medium-severity tickets (hours)",
    "sla_high":              "SLA for high-severity tickets (hours)",
    "sla_critical":          "SLA for critical tickets (hours)",
}


def _var_label(var: str) -> str:
    return VAR_LABELS.get(var, var.replace("_", " "))


def _decision_label(decision: str) -> str:
    return DECISION_LABELS.get(decision, decision.replace("_", " "))


def _def_label(key: str) -> str:
    return DEFINITION_LABELS.get(key, key.replace("_", " "))


def _cond_to_text(cond_str: str, definitions: dict) -> str:
    resolved = cond_str
    for key, val in definitions.items():
        resolved = resolved.replace("{" + key + "}", str(val))

    m = re.match(r"(\w+)\s*<=\s*(\d+(?:\.\d+)?)", resolved)
    if m:
        return f"the {_var_label(m.group(1))} is at most {m.group(2)}"
    m = re.match(r"(\w+)\s*>=\s*(\d+(?:\.\d+)?)", resolved)
    if m:
        return f"the {_var_label(m.group(1))} is at least {m.group(2)}"
    m = re.match(r"(\w+)\s*<\s*(\d+(?:\.\d+)?)", resolved)
    if m:
        return f"the {_var_label(m.group(1))} is less than {m.group(2)}"
    m = re.match(r"(\w+)\s*>\s*(\d+(?:\.\d+)?)", resolved)
    if m:
        return f"the {_var_label(m.group(1))} exceeds {m.group(2)}"
    m = re.match(r"(\w+)\s*==\s*'(\w+)'", resolved)
    if m:
        return f"the {_var_label(m.group(1))} is {m.group(2).replace('_', ' ')}"
    m = re.match(r"(\w+)\s*==\s*True", resolved)
    if m:
        return f"the {_var_label(m.group(1))} is active"
    m = re.match(r"(\w+)\s*==\s*False", resolved)
    if m:
        return f"the {_var_label(m.group(1))} is not active"
    m = re.match(r"(\w+)\s+in\s+\[(.+)\]", resolved)
    if m:
        var = m.group(1)
        vals = re.findall(r"'(\w+)'", m.group(2))
        if len(vals) == 1:
            return f"the {_var_label(var)} is {vals[0].replace('_', ' ')}"
        vals_text = " or ".join(v.replace("_", " ") for v in vals)
        return f"the {_var_label(var)} is {vals_text}"
    return cond_str


def _conds_to_text(conditions: list[str], definitions: dict) -> str:
    if not conditions:
        return "all cases (no specific conditions)"
    parts = [_cond_to_text(c, definitions) for c in conditions]
    if len(parts) == 1:
        return parts[0]
    return ", and ".join(parts)


# ---------------------------------------------------------------------------
# Universal memo-style outcome template
# ---------------------------------------------------------------------------

def _memo_outcome(conds_text: str, dec_text: str, rng: random.Random) -> str:
    """
    Uniform business-memo language for any behavioral policy statement.
    Deliberately indistinguishable between add/modify/no-op from wording alone.
    """
    templates = [
        f"When {conds_text}, {dec_text}.",
        f"Cases where {conds_text} should result in {dec_text}.",
        f"Where {conds_text} applies, the outcome is {dec_text}.",
        f"Situations in which {conds_text} are to be handled as: {dec_text}.",
    ]
    for t in templates:
        if _ambiguity_ok(t):
            return rng.choice([t2 for t2 in templates if _ambiguity_ok(t2)] or [templates[0]])
    return templates[0]


# ---------------------------------------------------------------------------
# Condition generators
# ---------------------------------------------------------------------------

def _make_numeric_condition(var: str, info: dict, definitions: dict,
                             rng: random.Random,
                             force_definition: bool = False) -> tuple[str, str | None]:
    lo, hi = info["range"]
    matching_defs = [k for k, v in definitions.items()
                     if isinstance(v, (int, float)) and lo <= v <= hi]
    use_def = matching_defs and (force_definition or rng.random() < 0.5)
    if use_def:
        def_key = rng.choice(matching_defs)
        op = rng.choice(["<", ">", "<=", ">="])
        return f"{var} {op} {{{def_key}}}", def_key
    else:
        threshold = rng.randint(lo + 1, max(lo + 2, hi // 2))
        op = rng.choice(["<", ">", "<=", ">="])
        return f"{var} {op} {threshold}", None


def _make_categorical_condition(var: str, info: dict, rng: random.Random) -> str:
    values = info["values"]
    if rng.random() < 0.5:
        val = rng.choice(values)
        return f"{var} == '{val}'"
    else:
        k = rng.randint(1, max(1, len(values) - 1))
        subset = rng.sample(values, k)
        vals_str = ", ".join(f"'{v}'" for v in subset)
        return f"{var} in [{vals_str}]"


def _make_boolean_condition(var: str, rng: random.Random) -> str:
    val = rng.choice([True, False])
    return f"{var} == {val}"


def _make_condition(var: str, info: dict, definitions: dict,
                    rng: random.Random, force_definition: bool = False) -> str:
    if info["type"] == "numeric":
        cond, _ = _make_numeric_condition(var, info, definitions, rng, force_definition)
        return cond
    elif info["type"] == "categorical":
        return _make_categorical_condition(var, info, rng)
    else:
        return _make_boolean_condition(var, rng)


# ---------------------------------------------------------------------------
# Latent rule graph  (no semantic name tracking — neutral IDs only)
# ---------------------------------------------------------------------------

class LatentRuleGraph:
    def __init__(self, domain: str, rng: random.Random):
        self.domain_name = domain
        self.domain = DOMAINS[domain]
        self.rng = rng
        self.definitions = {}
        self.rules = []
        self.next_priority = 0

    def add_definition(self, key: str, value: Any):
        self.definitions[key] = value

    def add_rule(self, rule_id: str, conditions: list[str], decision: str,
                 overrides: list[str] | None = None):
        self.next_priority += 1
        self.rules.append({
            "id": rule_id,
            "conditions": conditions,
            "decision": decision,
            "priority": self.next_priority,
            "overrides": overrides or [],
        })

    def remove_rule(self, rule_id: str):
        self.rules = [r for r in self.rules if r["id"] != rule_id]

    def modify_rule(self, rule_id: str, **kwargs):
        for r in self.rules:
            if r["id"] == rule_id:
                r.update(kwargs)
                return
        raise ValueError(f"Rule {rule_id} not found")

    def to_yaml(self) -> str:
        """
        Outputs neutral sequential IDs (r001, r002, ...).
        Keeps overrides (remapped to neutral IDs).
        Omits description field — no semantic labels exposed to the agent.
        """
        id_map = {rule["id"]: f"r{idx+1:03d}" for idx, rule in enumerate(self.rules)}

        data = {
            "definitions": dict(self.definitions),
            "rules": [],
        }
        for rule in self.rules:
            r: dict[str, Any] = {
                "id": id_map[rule["id"]],
                "conditions": rule["conditions"],
                "decision": rule["decision"],
                "priority": rule["priority"],
            }
            mapped_overrides = [id_map[oid] for oid in rule.get("overrides", []) if oid in id_map]
            if mapped_overrides:
                r["overrides"] = mapped_overrides
            data["rules"].append(r)

        return yaml.dump(data, default_flow_style=False, sort_keys=False)

    def copy(self) -> LatentRuleGraph:
        return copy.deepcopy(self)


# ---------------------------------------------------------------------------
# Initial graph generator
# ---------------------------------------------------------------------------

def generate_initial_graph(domain: str, n_rules: int = 6, seed: int = 42,
                            force_definitions: bool = False) -> LatentRuleGraph:
    rng = random.Random(seed)
    d = DOMAINS[domain]
    graph = LatentRuleGraph(domain, rng)

    for key, options in d["definition_templates"].items():
        graph.add_definition(key, rng.choice(options))

    # Default/fallback rule — empty conditions, matches everything
    graph.add_rule("default_action", conditions=[], decision=d["decisions"][-1])

    vars_list = list(d["variables"].items())

    for i in range(n_rules - 1):
        rule_id = f"rule_{i+1}"
        n_conds = rng.randint(1, min(3, len(vars_list)))
        chosen_vars = rng.sample(vars_list, n_conds)

        conditions = []
        for var, info in chosen_vars:
            conditions.append(_make_condition(var, info, graph.definitions, rng,
                                              force_definition=force_definitions))

        decision = rng.choice(d["decisions"])

        overrides = []
        existing_ids = [r["id"] for r in graph.rules if r["id"] != "default_action"]
        if existing_ids and rng.random() < 0.4:
            n_overrides = rng.randint(1, min(2, len(existing_ids)))
            overrides = rng.sample(existing_ids, n_overrides)

        graph.add_rule(rule_id, conditions, decision, overrides)

    return graph


# ---------------------------------------------------------------------------
# Update type groups
# ---------------------------------------------------------------------------

INTERACTING_TYPES = [
    "change_definition",
    "change_priority",
    "override_existing",
    "add_exception",
    "narrow_scope",
]

LOCAL_TYPES = [
    "add_rule",
    "revoke_rule",
    "change_decision",
    "widen_scope",
]

ALL_UPDATE_TYPES = INTERACTING_TYPES + LOCAL_TYPES


# ---------------------------------------------------------------------------
# Description builders
# All use uniform memo-style language — operation type NOT inferrable from wording.
# All reference rules by their conditions/behavior, never by a stored name or id.
# ---------------------------------------------------------------------------

def _desc_behavioral(conditions: list[str], decision: str,
                     definitions: dict, rng: random.Random) -> str:
    """Generic behavioral statement: 'When [conditions], [decision].'"""
    conds_text = _conds_to_text(conditions, definitions)
    dec_text = _decision_label(decision)
    return _memo_outcome(conds_text, dec_text, rng)


def _desc_change_definition(key: str, new_val: Any, rng: random.Random) -> str:
    label = _def_label(key)
    templates = [
        f"The {label} is {new_val}.",
        f"Effective immediately, the {label} is {new_val}.",
        f"The {label} is set to {new_val}.",
        f"The {label} is now {new_val}.",
    ]
    return rng.choice(templates)


def _desc_update_default(new_dec: str, rng: random.Random) -> str:
    dec_text = _decision_label(new_dec)
    templates = [
        f"Unmatched cases result in {dec_text}.",
        f"Cases not covered by any specific rule should result in {dec_text}.",
        f"The standard outcome for cases with no applicable rule is {dec_text}.",
        f"Cases with no matching specific rule are handled by: {dec_text}.",
    ]
    return rng.choice(templates)


def _desc_change_priority(winner: dict, loser: dict,
                           definitions: dict, rng: random.Random) -> str:
    """Describe the precedence outcome when two rules overlap."""
    w_conds = _conds_to_text(winner["conditions"], definitions) if winner["conditions"] else "all unmatched cases"
    l_conds = _conds_to_text(loser["conditions"], definitions) if loser["conditions"] else "all unmatched cases"
    w_dec = _decision_label(winner["decision"])
    l_dec = _decision_label(loser["decision"])
    templates = [
        f"When {w_conds} and {l_conds} both hold, the outcome is {w_dec}.",
        f"Cases satisfying both [{w_conds}] and [{l_conds}] result in {w_dec}, not {l_dec}.",
        f"Where {w_conds} and {l_conds} overlap, {w_dec} is the applicable outcome.",
    ]
    return rng.choice(templates)


def _desc_revoke(conditions: list[str], definitions: dict, rng: random.Random) -> str:
    """Describe removal of a rule in neutral terms."""
    conds_text = _conds_to_text(conditions, definitions)
    templates = [
        f"Cases where {conds_text} are no longer subject to a separate specific rule.",
        f"The separate handling for cases where {conds_text} has been removed.",
        f"No distinct rule governs cases where {conds_text}.",
    ]
    return rng.choice(templates)


# ---------------------------------------------------------------------------
# Ultra-hard update skeleton builder
# ---------------------------------------------------------------------------

def _build_ultra_hard_skeleton(n_updates: int) -> list[str]:
    """
    Skeleton guaranteeing maximum priority/revocation pressure:
    - 3 change_priority slots (guaranteed, not left to random interacting)
    - 2 revoke_rule slots
    - 1 chain_create + 1-2 chain_ref (dependency chain)
    - 1 no_op_disguised
    This targets the specific failure modes: priority arithmetic after
    mid-stream additions/removals, and stale-rule retention.
    """
    if n_updates == 8:
        return [
            "chain_create",    # 0 — creates chain-A
            "change_priority", # 1 — swap #1
            "revoke_rule",     # 2 — removal #1 (exposes lower rules)
            "chain_ref",       # 3 — modifies chain-A
            "change_priority", # 4 — swap #2
            "revoke_rule",     # 5 — removal #2
            "change_priority", # 6 — swap #3
            "no_op_disguised", # 7
        ]
    elif n_updates == 9:
        return [
            "chain_create",    # 0 — creates chain-A
            "change_priority", # 1 — swap #1
            "revoke_rule",     # 2 — removal #1
            "chain_ref",       # 3 — modifies chain-A
            "change_priority", # 4 — swap #2
            "revoke_rule",     # 5 — removal #2
            "change_priority", # 6 — swap #3
            "no_op_disguised", # 7
            "chain_ref",       # 8 — modifies chain-A again
        ]
    else:  # n_updates == 10
        return [
            "chain_create",    # 0 — creates chain-A
            "change_priority", # 1 — swap #1
            "revoke_rule",     # 2 — removal #1
            "chain_ref",       # 3 — modifies chain-A
            "change_priority", # 4 — swap #2
            "update_default",  # 5 — fallback change
            "revoke_rule",     # 6 — removal #2
            "change_priority", # 7 — swap #3
            "no_op_disguised", # 8
            "chain_ref",       # 9 — modifies chain-A again
        ]


# ---------------------------------------------------------------------------
# Update stream generator
# ---------------------------------------------------------------------------

def generate_update_stream(graph: LatentRuleGraph, n_updates: int = 4,
                           seed: int = 42, interaction_bias: float = 0.4,
                           ultra_hard_mode: bool = False) -> list[dict]:
    rng = random.Random(seed)
    d = graph.domain
    updates = []

    if ultra_hard_mode:
        skeleton = _build_ultra_hard_skeleton(min(max(n_updates, 8), 10))
        while len(skeleton) < n_updates:
            skeleton.insert(len(skeleton) // 2, "interacting")
        skeleton = skeleton[:n_updates]
    else:
        skeleton = [None] * n_updates

    # Tracks chain rules created during this stream:
    # {rule_id, conditions (current, updated by chain_ref), decision (current)}
    chain_rules: list[dict] = []
    definition_change_history: dict[str, list] = {}

    for i in range(n_updates):
        slot_type = skeleton[i]
        existing_rules = [r for r in graph.rules if r["id"] != "default_action"]

        # Resolve slot type
        if slot_type == "interacting" or slot_type is None:
            if slot_type is None:
                if not existing_rules:
                    update_type = "add_rule"
                elif rng.random() < interaction_bias:
                    update_type = rng.choice(INTERACTING_TYPES)
                else:
                    update_type = rng.choice(ALL_UPDATE_TYPES)
            else:
                update_type = rng.choice(INTERACTING_TYPES)
        else:
            update_type = slot_type

        # ----------------------------------------------------------------
        # CHAIN_CREATE — new rule that the stream will reference later
        # ----------------------------------------------------------------
        if update_type == "chain_create":
            vars_list = list(d["variables"].items())
            var, info = rng.choice(vars_list)
            cond = _make_condition(var, info, graph.definitions, rng,
                                   force_definition=ultra_hard_mode)
            new_dec = rng.choice(d["decisions"])
            new_id = f"chain_{i+1}_rule"

            if existing_rules and rng.random() < 0.6:
                target = rng.choice(existing_rules)
                overrides = [target["id"]]
            else:
                overrides = []

            description = _desc_behavioral([cond], new_dec, graph.definitions, rng)
            updates.append({
                "type": "chain_create",
                "description": description,
                "rule_id": new_id,
                "conditions": [cond],
                "decision": new_dec,
                "overrides": overrides,
            })
            graph.add_rule(new_id, [cond], new_dec, overrides)
            chain_rules.append({"rule_id": new_id, "conditions": [cond], "decision": new_dec})
            continue

        # ----------------------------------------------------------------
        # CHAIN_REF — modifies the most recent chain_create'd rule
        # Describes by conditions (not by name) so model must track state
        # ----------------------------------------------------------------
        if update_type == "chain_ref":
            if not chain_rules:
                update_type = "change_definition" if graph.definitions else "change_decision"
                # fall through to standard handlers below
            else:
                target_info = chain_rules[-1]
                rule_id = target_info["rule_id"]

                if rng.random() < 0.5:
                    # Narrow scope: add condition, describe full new condition set
                    var, info = rng.choice(list(d["variables"].items()))
                    new_cond = _make_condition(var, info, graph.definitions, rng,
                                              force_definition=ultra_hard_mode)
                    all_conds = target_info["conditions"] + [new_cond]
                    description = _desc_behavioral(all_conds, target_info["decision"],
                                                   graph.definitions, rng)
                    updates.append({
                        "type": "chain_ref",
                        "description": description,
                        "rule_id": rule_id,
                        "sub_type": "narrow_scope",
                        "added_condition": new_cond,
                    })
                    for r in graph.rules:
                        if r["id"] == rule_id:
                            r["conditions"].append(new_cond)
                            break
                    target_info["conditions"] = all_conds
                else:
                    # Change decision: describe updated conditions → new decision
                    old_dec = target_info["decision"]
                    others = [dec for dec in d["decisions"] if dec != old_dec]
                    if not others:
                        others = d["decisions"]
                    new_dec = rng.choice(others)
                    description = _desc_behavioral(target_info["conditions"], new_dec,
                                                   graph.definitions, rng)
                    updates.append({
                        "type": "chain_ref",
                        "description": description,
                        "rule_id": rule_id,
                        "sub_type": "change_decision",
                        "old_decision": old_dec,
                        "new_decision": new_dec,
                    })
                    graph.modify_rule(rule_id, decision=new_dec)
                    target_info["decision"] = new_dec
                continue

        # ----------------------------------------------------------------
        # UPDATE_DEFAULT — changes fallback rule decision
        # Described without "when no other rule matches" language
        # ----------------------------------------------------------------
        if update_type == "update_default":
            default_rule = next((r for r in graph.rules if r["id"] == "default_action"), None)
            if default_rule is None:
                continue
            old_dec = default_rule["decision"]
            others = [dec for dec in d["decisions"] if dec != old_dec]
            if not others:
                continue
            new_dec = rng.choice(others)
            description = _desc_update_default(new_dec, rng)
            updates.append({
                "type": "update_default",
                "description": description,
                "old_decision": old_dec,
                "new_decision": new_dec,
            })
            graph.modify_rule("default_action", decision=new_dec)
            continue

        # ----------------------------------------------------------------
        # NO_OP_OBVIOUS — describes existing behavior, looks like real change
        # ----------------------------------------------------------------
        if update_type == "no_op_obvious":
            candidates = [r for r in existing_rules if r["conditions"]]
            if candidates:
                target = rng.choice(candidates)
                description = _desc_behavioral(target["conditions"], target["decision"],
                                               graph.definitions, rng)
            else:
                default_rule = next(r for r in graph.rules if r["id"] == "default_action")
                description = _desc_update_default(default_rule["decision"], rng)
            updates.append({"type": "no_op_clarification", "description": description})
            continue

        # ----------------------------------------------------------------
        # NO_OP_DISGUISED — describes case already covered, same memo style
        # ----------------------------------------------------------------
        if update_type == "no_op_disguised":
            candidates = [r for r in existing_rules if r["conditions"]]
            if candidates:
                target = rng.choice(candidates)
                description = _desc_behavioral(target["conditions"], target["decision"],
                                               graph.definitions, rng)
            else:
                dflt = next(r for r in graph.rules if r["id"] == "default_action")
                description = _desc_update_default(dflt["decision"], rng)
            updates.append({"type": "no_op_disguised", "description": description})
            continue

        # ----------------------------------------------------------------
        # Standard update types
        # ----------------------------------------------------------------

        if update_type == "add_rule" or not existing_rules:
            vars_list = list(d["variables"].items())
            n_conds = rng.randint(1, min(2, len(vars_list)))
            chosen = rng.sample(vars_list, n_conds)
            conditions = [_make_condition(v, info, graph.definitions, rng,
                                          force_definition=ultra_hard_mode)
                          for v, info in chosen]
            decision = rng.choice(d["decisions"])
            new_id = f"update_{i+1}_new_rule"
            overrides = []
            if existing_rules and rng.random() < 0.4:
                overrides = [rng.choice(existing_rules)["id"]]
            description = _desc_behavioral(conditions, decision, graph.definitions, rng)
            updates.append({
                "type": "add_rule",
                "description": description,
                "rule_id": new_id,
                "conditions": conditions,
                "decision": decision,
                "overrides": overrides,
            })
            graph.add_rule(new_id, conditions, decision, overrides)

        elif update_type == "revoke_rule":
            target = rng.choice(existing_rules)
            description = _desc_revoke(target["conditions"], graph.definitions, rng)
            updates.append({"type": "revoke_rule", "description": description,
                             "rule_id": target["id"]})
            graph.remove_rule(target["id"])

        elif update_type == "change_definition":
            if not graph.definitions:
                continue
            key = rng.choice(list(graph.definitions.keys()))
            templates = d["definition_templates"].get(key, [])
            if not templates:
                continue
            old_val = graph.definitions[key]
            others = [v for v in templates if v != old_val]
            if not others:
                continue
            new_val = rng.choice(others)
            already_changed = key in definition_change_history
            definition_change_history.setdefault(key, []).append(old_val)
            # Second change: omit old value to hide the intermediate state
            description = _desc_change_definition(key, new_val, rng)
            updates.append({
                "type": "change_definition",
                "description": description,
                "key": key,
                "old_value": old_val,
                "new_value": new_val,
                "is_revision": already_changed,
            })
            graph.definitions[key] = new_val

        elif update_type == "change_decision":
            target = rng.choice(existing_rules)
            old_dec = target["decision"]
            others = [dec for dec in d["decisions"] if dec != old_dec]
            if not others:
                continue
            new_dec = rng.choice(others)
            description = _desc_behavioral(target["conditions"], new_dec, graph.definitions, rng)
            updates.append({
                "type": "change_decision",
                "description": description,
                "rule_id": target["id"],
                "old_decision": old_dec,
                "new_decision": new_dec,
            })
            graph.modify_rule(target["id"], decision=new_dec)

        elif update_type == "narrow_scope":
            target = rng.choice(existing_rules)
            var, info = rng.choice(list(d["variables"].items()))
            cond = _make_condition(var, info, graph.definitions, rng,
                                   force_definition=ultra_hard_mode)
            all_conds = target["conditions"] + [cond]
            description = _desc_behavioral(all_conds, target["decision"], graph.definitions, rng)
            updates.append({
                "type": "narrow_scope",
                "description": description,
                "rule_id": target["id"],
                "added_condition": cond,
            })
            target["conditions"].append(cond)

        elif update_type == "widen_scope":
            target = rng.choice(existing_rules)
            if len(target["conditions"]) > 1:
                removed = target["conditions"].pop(rng.randrange(len(target["conditions"])))
                remaining = target["conditions"]
                description = _desc_behavioral(remaining, target["decision"], graph.definitions, rng)
                updates.append({
                    "type": "widen_scope",
                    "description": description,
                    "rule_id": target["id"],
                    "removed_condition": removed,
                })

        elif update_type == "override_existing":
            target = rng.choice(existing_rules)
            var, info = rng.choice(list(d["variables"].items()))
            cond = _make_condition(var, info, graph.definitions, rng,
                                   force_definition=ultra_hard_mode)
            new_dec = rng.choice(d["decisions"])
            new_id = f"update_{i+1}_override"
            description = _desc_behavioral([cond], new_dec, graph.definitions, rng)
            updates.append({
                "type": "override_existing",
                "description": description,
                "rule_id": new_id,
                "overrides": [target["id"]],
                "conditions": [cond],
                "decision": new_dec,
            })
            graph.add_rule(new_id, [cond], new_dec, [target["id"]])

        elif update_type == "add_exception":
            target = rng.choice(existing_rules)
            var, info = rng.choice(list(d["variables"].items()))
            cond = _make_condition(var, info, graph.definitions, rng,
                                   force_definition=ultra_hard_mode)
            others = [dec for dec in d["decisions"] if dec != target["decision"]]
            if not others:
                continue
            new_dec = rng.choice(others)
            exc_id = f"update_{i+1}_exception"
            all_conds = target["conditions"] + [cond]
            description = _desc_behavioral(all_conds, new_dec, graph.definitions, rng)
            updates.append({
                "type": "add_exception",
                "description": description,
                "rule_id": exc_id,
                "exception_to": target["id"],
                "conditions": all_conds,
                "decision": new_dec,
            })
            graph.add_rule(exc_id, all_conds, new_dec, [target["id"]])

        elif update_type == "change_priority":
            if len(existing_rules) < 2:
                continue
            rule_a, rule_b = rng.sample(existing_rules, 2)
            # Determine which rule will win AFTER the swap
            # Before swap: lower priority value means lower rank
            # After swap: rule_a gets rule_b's old priority and vice versa
            # The "winner" after swap = the one that ends up with the higher priority
            if rule_b["priority"] > rule_a["priority"]:
                # rule_b currently higher; after swap rule_a gets higher priority → rule_a wins
                winner, loser = rule_a, rule_b
            else:
                winner, loser = rule_b, rule_a
            description = _desc_change_priority(winner, loser, graph.definitions, rng)
            updates.append({
                "type": "change_priority",
                "description": description,
                "rule_id_1": rule_a["id"],
                "rule_id_2": rule_b["id"],
            })
            rule_a["priority"], rule_b["priority"] = rule_b["priority"], rule_a["priority"]

    return updates


# ---------------------------------------------------------------------------
# Task packaging
# ---------------------------------------------------------------------------

def generate_task(domain: str = "refund", n_rules: int = 6, n_updates: int = 4,
                  seed: int = 42, interaction_bias: float = 0.4,
                  ultra_hard_mode: bool = False) -> dict:
    initial_graph = generate_initial_graph(
        domain, n_rules=n_rules, seed=seed,
        force_definitions=ultra_hard_mode,
    )
    initial_yaml = initial_graph.to_yaml()

    updated_graph = initial_graph.copy()
    updated_graph.rng = random.Random(seed + 1000)
    updates = generate_update_stream(
        updated_graph, n_updates=n_updates,
        seed=seed + 1000, interaction_bias=interaction_bias,
        ultra_hard_mode=ultra_hard_mode,
    )
    gold_yaml = updated_graph.to_yaml()

    update_type_counts: dict[str, int] = {}
    for u in updates:
        update_type_counts[u["type"]] = update_type_counts.get(u["type"], 0) + 1

    return {
        "domain": domain,
        "initial_policy": initial_yaml,
        "update_stream": updates,
        "gold_policy": gold_yaml,
        "metadata": {
            "n_rules_initial": n_rules,
            "n_updates": n_updates,
            "n_rules_final": len(updated_graph.rules),
            "seed": seed,
            "interaction_bias": interaction_bias,
            "ultra_hard_mode": ultra_hard_mode,
            "update_type_counts": update_type_counts,
        },
    }


if __name__ == "__main__":
    from verifier import verify_behavioral_equivalence

    task = generate_task(domain="refund", n_rules=12, n_updates=9, seed=42,
                         interaction_bias=0.95, ultra_hard_mode=True)

    print("=== INITIAL POLICY ===")
    print(task["initial_policy"][:800])
    print("\n=== UPDATE STREAM ===")
    for i, u in enumerate(task["update_stream"], 1):
        print(f"  {i}. [{u['type']}] {u['description']}")
    print("\n=== BEHAVIORAL DIFF ===")
    result = verify_behavioral_equivalence(task["gold_policy"], task["initial_policy"],
                                           n_scenarios=1000, seed=42)
    print(f"  {(1-result.score)*100:.1f}% of scenarios differ")
    print(f"  Failure breakdown: {result.summary()['failure_breakdown']}")
