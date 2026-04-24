"""
Generate 10 diverse annotated StateBench example tasks for the submission.

Variety axes:
  - Domain: refund, approval, access_control, escalation
  - n_rules: 4 → 10
  - n_updates: 2 → 8
  - Dominant update character: definition-propagation, priority-cascade,
    override-chain, scope-exposure, revoke-with-fallback, mixed

Outputs:
  - examples/example_tasks.json  (machine-readable)
  - examples/examples.md         (human-readable, section 6 of submission)
"""

import json
import sys
from pathlib import Path

from task_generator import generate_task, DOMAINS
from verifier import verify_behavioral_equivalence, find_counterexample
from compiler import compile_policy


# ---------------------------------------------------------------------------
# Task specifications
# 10 tasks chosen to cover all domains, difficulty levels, and update types
# ---------------------------------------------------------------------------

EXAMPLE_SPECS = [
    # 1. Trivial warm-up: one definition change, one new rule, no interaction
    dict(domain="refund",         n_rules=4,  n_updates=2, seed=7,
         label="easy",
         story="A single definition change shifts the refund window; a new rule adds high-value escalation. No interaction — each update is self-contained."),

    # 2. Approval: revoke + change_decision — removing a rule exposes the fallback
    dict(domain="approval",       n_rules=4,  n_updates=3, seed=40,
         label="easy",
         story="A rule is revoked and another's decision flips. The tricky part: revoking the rule lets a lower-priority fallback take over cases that were previously handled."),

    # 3. Access control: priority swap changes winner across many scenarios
    dict(domain="access_control", n_rules=6,  n_updates=4, seed=25,
         label="medium",
         story="A priority swap between two broadly-matching rules flips the winner for a large slice of scenarios. The swap looks like a minor bookkeeping change but has global behavioral consequences."),

    # 4. Escalation: exception added to a rule that also has an override
    dict(domain="escalation",     n_rules=6,  n_updates=4, seed=31,
         label="medium",
         story="An exception is carved out of a rule that already overrides another. Agents must track both the override relationship and the new exception without conflating them."),

    # 5. Refund: definition change propagates into 2+ rules simultaneously
    dict(domain="refund",         n_rules=6,  n_updates=5, seed=44,
         label="medium",
         story="Changing 'standard_window' from 30 to 45 silently expands the applicability of every rule that references it. Agents that edit rules one-by-one often miss that the definition already did the work — or double-apply it."),

    # 6. Approval: narrow_scope + add_exception exposes a shadowed conflict
    dict(domain="approval",       n_rules=8,  n_updates=5, seed=55,
         label="hard",
         story="Narrowing a rule's scope removes it from some scenarios, making a previously-shadowed lower-priority rule the winner there. An exception is then added to that exposed rule. Two-step interactions are easy to miss."),

    # 7. Access control: cascading override chain — new rule overrides one that overrides another
    dict(domain="access_control", n_rules=8,  n_updates=6, seed=63,
         label="hard",
         story="Three sequential override operations build a chain: A overrides B, then C overrides A, then B is revoked. Agents must reason about transitive precedence after each step, not just apply updates in isolation."),

    # 8. Escalation: widen_scope after revoke creates unexpected fallthrough
    dict(domain="escalation",     n_rules=8,  n_updates=6, seed=71,
         label="hard",
         story="A rule is revoked, then a surviving sibling rule is widened to cover more cases. The widening interacts with the now-absent rule: scenarios that used to hit the revoked rule now fall through to the widened sibling with a different decision."),

    # 9. Refund: layered exceptions with priority inversion across many rules
    dict(domain="refund",         n_rules=10, n_updates=7, seed=88,
         label="very_hard",
         story="Four add_exception operations each inherit their parent rule's conditions plus one extra. Priority inversions then reorder these stacked exceptions. Maintaining correct layering under both changes requires tracking 10+ rule interactions simultaneously."),

    # 10. Approval: all 9 update types, maximum interaction surface
    dict(domain="approval",       n_rules=10, n_updates=8, seed=99,
         label="very_hard",
         story="All nine update types appear across 8 sequential changes. A definition change in step 2 affects conditions that are narrowed in step 5. A rule revoked in step 3 was an override target for a rule added in step 6. The update stream is deliberately non-local: almost every step touches something a prior step already changed."),
]


# ---------------------------------------------------------------------------
# Annotation helpers
# ---------------------------------------------------------------------------

def classify_update_character(updates: list[dict]) -> str:
    """One-line description of what kind of complexity dominates."""
    types = [u["type"] for u in updates]
    counts = {t: types.count(t) for t in set(types)}

    signals = []
    if counts.get("change_definition", 0) >= 1:
        signals.append("definition propagation")
    if counts.get("change_priority", 0) >= 1:
        signals.append("priority inversion")
    if counts.get("override_existing", 0) + counts.get("add_exception", 0) >= 2:
        signals.append("override/exception chain")
    if counts.get("narrow_scope", 0) + counts.get("widen_scope", 0) >= 1:
        signals.append("scope exposure")
    if counts.get("revoke_rule", 0) >= 1:
        signals.append("revoke-exposes-fallback")
    if not signals:
        signals.append("sequential local edits")

    return ", ".join(signals)


def describe_update(u: dict) -> str:
    return f"[{u['type']}] {u['description']}"


def find_interacting_pairs(updates: list[dict]) -> list[str]:
    """Identify update pairs that likely interact."""
    pairs = []
    types = [u["type"] for u in updates]

    # definition change + any rule condition reference
    for i, u in enumerate(updates):
        if u["type"] == "change_definition":
            for j, v in enumerate(updates):
                if j != i and v["type"] in ("narrow_scope", "widen_scope", "add_exception"):
                    pairs.append(f"Update {i+1} ({u['type']}) → Update {j+1} ({v['type']}): "
                                 f"the definition change propagates into the scope/exception modification")

    # revoke + widen/override on surviving rules
    for i, u in enumerate(updates):
        if u["type"] == "revoke_rule":
            for j, v in enumerate(updates[i+1:], start=i+1):
                if v["type"] in ("widen_scope", "override_existing"):
                    pairs.append(f"Update {i+1} (revoke) → Update {j+1} ({v['type']}): "
                                 f"revoking exposes new winners that the later change then modifies")

    # priority change followed by override
    for i, u in enumerate(updates):
        if u["type"] == "change_priority":
            for j, v in enumerate(updates[i+1:], start=i+1):
                if v["type"] in ("add_exception", "override_existing"):
                    pairs.append(f"Update {i+1} (change_priority) → Update {j+1} ({v['type']}): "
                                 f"priority reordering changes which rule the override/exception applies to")

    return pairs


def generate_annotated_example(spec: dict) -> dict:
    """Generate a task and compute all annotations."""
    task = generate_task(
        domain=spec["domain"],
        n_rules=spec["n_rules"],
        n_updates=spec["n_updates"],
        seed=spec["seed"],
    )

    # Verify gold is valid
    try:
        compile_policy(task["gold_policy"])
    except Exception as e:
        print(f"  WARNING: gold policy failed to compile: {e}")

    # Behavioral difference
    vr = verify_behavioral_equivalence(
        task["gold_policy"], task["initial_policy"],
        n_scenarios=1000, seed=spec["seed"],
    )
    behavioral_diff = round(1.0 - vr.score, 3)
    failure_breakdown = vr.summary()["failure_breakdown"]

    # Counterexample: what does the initial policy get wrong?
    cx = find_counterexample(
        task["gold_policy"], task["initial_policy"],
        n_scenarios=5000, seed=spec["seed"] * 3,
    )

    # Update character
    updates = task["update_stream"]
    dominant_pattern = classify_update_character(updates)
    interacting_pairs = find_interacting_pairs(updates)

    # Policy summary
    import yaml
    initial_data = yaml.safe_load(task["initial_policy"])
    gold_data = yaml.safe_load(task["gold_policy"])
    initial_rule_ids = [r["id"] for r in initial_data.get("rules", [])]
    gold_rule_ids = [r["id"] for r in gold_data.get("rules", [])]
    added_rules = [r for r in gold_rule_ids if r not in initial_rule_ids]
    removed_rules = [r for r in initial_rule_ids if r not in gold_rule_ids]

    return {
        "example_id": f"ex_{spec['seed']:03d}",
        "domain": spec["domain"],
        "difficulty": spec["label"],
        "n_rules_initial": spec["n_rules"],
        "n_updates": spec["n_updates"],
        "seed": spec["seed"],
        "story": spec["story"],
        "dominant_interaction_pattern": dominant_pattern,
        "behavioral_diff_pct": round(behavioral_diff * 100, 1),
        "failure_breakdown_initial_vs_gold": failure_breakdown,
        "initial_policy": task["initial_policy"],
        "gold_policy": task["gold_policy"],
        "initial_definitions": initial_data.get("definitions", {}),
        "initial_rule_ids": initial_rule_ids,
        "gold_rule_ids": gold_rule_ids,
        "rules_added_by_updates": added_rules,
        "rules_removed_by_updates": removed_rules,
        "update_stream": updates,
        "interacting_update_pairs": interacting_pairs,
        "counterexample_of_initial": cx,
    }


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------

def render_markdown(examples: list[dict]) -> str:
    lines = []
    lines.append("# StateBench: 10 Concrete Example Tasks\n")
    lines.append(
        "Each example shows the domain, initial policy summary, update stream, "
        "what makes it hard, and the behavioral gap the agent must close.\n"
    )

    for i, ex in enumerate(examples, 1):
        lines.append(f"---\n")
        lines.append(f"## Example {i}: {ex['domain'].replace('_', ' ').title()} — {ex['difficulty'].replace('_', ' ').title()}\n")

        lines.append(f"**Task ID:** `{ex['example_id']}`  ")
        lines.append(f"**Domain:** {ex['domain']}  ")
        lines.append(f"**Difficulty:** {ex['difficulty']}  ")
        lines.append(f"**Initial rules:** {ex['n_rules_initial']}  ")
        lines.append(f"**Updates:** {ex['n_updates']}\n")

        lines.append(f"**Behavioral gap** (fraction of scenarios where initial ≠ gold): "
                     f"**{ex['behavioral_diff_pct']}%**\n")

        lines.append(f"### What makes it hard\n")
        lines.append(f"{ex['story']}\n")

        lines.append(f"**Dominant interaction pattern:** {ex['dominant_interaction_pattern']}\n")

        if ex["interacting_update_pairs"]:
            lines.append(f"**Update interactions:**\n")
            for pair in ex["interacting_update_pairs"]:
                lines.append(f"- {pair}")
            lines.append("")

        lines.append(f"### Initial Policy Summary\n")
        lines.append(f"**Definitions:** {json.dumps(ex['initial_definitions'])}\n")
        lines.append(f"**Rules:** {', '.join(f'`{r}`' for r in ex['initial_rule_ids'])}\n")

        lines.append(f"```yaml")
        lines.append(ex["initial_policy"].rstrip())
        lines.append(f"```\n")

        lines.append(f"### Update Stream ({ex['n_updates']} updates)\n")
        for j, u in enumerate(ex["update_stream"], 1):
            lines.append(f"{j}. `[{u['type']}]` {u['description']}")
        lines.append("")

        lines.append(f"### What Changed (Gold vs Initial)\n")
        if ex["rules_added_by_updates"]:
            lines.append(f"- Rules **added**: {', '.join(f'`{r}`' for r in ex['rules_added_by_updates'])}")
        if ex["rules_removed_by_updates"]:
            lines.append(f"- Rules **removed**: {', '.join(f'`{r}`' for r in ex['rules_removed_by_updates'])}")
        lines.append(f"- **{ex['behavioral_diff_pct']}%** of scenarios now produce a different decision")

        if ex["failure_breakdown_initial_vs_gold"]:
            fb = ex["failure_breakdown_initial_vs_gold"]
            breakdown_str = ", ".join(f"{k}: {v}" for k, v in sorted(fb.items(), key=lambda x: -x[1]))
            lines.append(f"- Failure breakdown: {breakdown_str}")
        lines.append("")

        if ex["counterexample_of_initial"]:
            cx = ex["counterexample_of_initial"]
            lines.append(f"### Counterexample (initial policy is wrong here)\n")
            lines.append(f"```")
            lines.append(f"Scenario:  {cx['scenario']}")
            lines.append(f"Expected:  {cx['expected_decision']} (rule: {cx['expected_rule']})")
            lines.append(f"Got (initial): {cx['actual_decision']} (rule: {cx['actual_rule']})")
            lines.append(f"```\n")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    out_dir = Path("examples")
    out_dir.mkdir(exist_ok=True)

    examples = []
    print(f"Generating {len(EXAMPLE_SPECS)} example tasks...\n")

    for i, spec in enumerate(EXAMPLE_SPECS, 1):
        label = spec["label"]
        domain = spec["domain"]
        n_u = spec["n_updates"]
        n_r = spec["n_rules"]
        print(f"  [{i:2d}/10] {domain:15s}  {label:10s}  rules={n_r}  updates={n_u}  seed={spec['seed']}", end="", flush=True)
        try:
            ex = generate_annotated_example(spec)
            examples.append(ex)
            print(f"  →  {ex['behavioral_diff_pct']}% behavioral gap")
        except Exception as e:
            print(f"  ERROR: {e}")

    # Save JSON
    json_path = out_dir / "example_tasks.json"
    with open(json_path, "w") as f:
        json.dump(examples, f, indent=2)
    print(f"\nSaved {len(examples)} examples to {json_path}")

    # Save Markdown
    md = render_markdown(examples)
    md_path = out_dir / "examples.md"
    with open(md_path, "w") as f:
        f.write(md)
    print(f"Saved markdown to {md_path}")

    # Print summary table
    print(f"\n{'ID':>8}  {'Domain':>15}  {'Diff':>10}  {'Rules':>5}  {'Updates':>7}  {'Gap%':>5}  Pattern")
    print("-" * 90)
    for ex in examples:
        pattern_short = ex["dominant_interaction_pattern"][:35]
        print(f"{ex['example_id']:>8}  {ex['domain']:>15}  {ex['difficulty']:>10}  "
              f"{ex['n_rules_initial']:>5}  {ex['n_updates']:>7}  "
              f"{ex['behavioral_diff_pct']:>5.1f}  {pattern_short}")


if __name__ == "__main__":
    main()
