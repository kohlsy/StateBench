# StateBench

**StateBench tests whether frontier agents can maintain a coherent rule-system state under sequential, interacting updates.**

A no-oracle benchmark for frontier model policy maintenance. Tests whether a model can maintain **global coherence** in an evolving policy artifact under a stream of semantically specified updates — without any behavioral oracle feedback before final submission.

**Result on claude-sonnet-4-6:** 16.7% pass rate, 0.772 avg behavioral score on the ultra-hard skeleton.

---

## What It Tests

Policy artifacts are not collections of independent rules. They are systems with shared definitions, priority orderings, override chains, and fallback behaviors. A single update can cascade silently across six rules. A priority swap can reshape which rule wins across hundreds of scenario types. A revocation can expose lower-priority rules that now become the effective policy.

StateBench measures whether a model can execute a sequence of 8–10 interacting updates — including 3 priority swaps, 2 rule revocations, chain creates, and chain references — and produce a final policy that is behaviorally equivalent to the gold policy, without any test or oracle feedback before submission.

---

## Quick Start

```bash
pip install anthropic openai pyyaml
export ANTHROPIC_API_KEY=sk-...

# Run benchmark (20 tasks, ultra-hard skeleton, 3 parallel workers)
python run_agent.py --model claude-sonnet-4-6 --n_tasks 20 --suite ultra_only --output results/ --workers 3

# Generate and inspect tasks without running agents
python calibration.py     # generates 20 ultra_hard tasks, prints examples
python task_generator.py  # generates one task, shows initial policy + updates
```

For OpenAI models:
```bash
export OPENAI_API_KEY=sk-proj-...
python run_agent.py --model o3 --n_tasks 20 --suite ultra_only --output results/ --workers 2
```

---

## Files

| File | Role |
|------|------|
| `task_generator.py` | Latent rule graph + update stream generator |
| `compiler.py` | Parses YAML → Policy object, validates conditions |
| `verifier.py` | Behavioral equivalence tester (samples scenarios, compares decisions) |
| `agent_env.py` | Tool environment (5 tools, blind edit_policy, minimal compile_check) |
| `run_agent.py` | Agent harness for Claude (Anthropic) and GPT/o3 (OpenAI) |
| `calibration.py` | Suite generator with behavioral gap filter and back-fill |

---

## The Task

The agent receives:

1. **An initial policy artifact** — a YAML document with 12–16 rules, conditions, decisions, priorities, override references, and shared numeric definitions.
2. **An update stream** — 8–10 sequential policy updates in uniform business-memo language. All update types (add, modify, revoke, priority swap, no-op) use identical surface form: `"When [conditions], [decision]."` The model cannot infer operation type from wording.

The agent must produce a final YAML policy **behaviorally equivalent** to the gold policy — the policy that results from correctly applying all updates to the initial artifact.

### Policy DSL

```yaml
definitions:
  standard_window: 30        # shared numeric constant
  max_refund_amount: 500

rules:
- id: r001
  conditions: []             # empty = default/fallback rule
  decision: request_documentation
  priority: 1

- id: r002
  conditions:
  - purchase_age_days > {standard_window}
  - customer_tier in ['gold', 'platinum']
  decision: approve_refund
  priority: 7
  overrides: [r001]
```

Key semantics:
- **Highest priority wins** when multiple rules match a scenario.
- **Definitions** are shared references; changing one propagates to all rules that use it.
- **Overrides** is informational metadata; priority numbers determine resolution.
- **Empty conditions** = default rule (matches everything; always priority 1).
- **Rule IDs** are neutral sequential identifiers (r001, r002, ...) with no semantic content.

---

## Tools

The agent has exactly five tools:

| Tool | Returns | What it reveals |
|------|---------|-----------------|
| `read_policy()` | Current YAML artifact | Full artifact |
| `read_updates()` | List of update strings | Full update stream |
| `edit_policy(new_yaml)` | `{"status": "ok"}` | Nothing — blind replace |
| `compile_check()` | `{"status": "ok"}` or `{"status": "compile_error", "message": "..."}` | Syntax validity only |
| `submit()` | Final behavioral score | Revealed only after submission |

Critically absent:
- No behavioral preview tool — the model cannot check correctness before submitting
- No structural summary (rule count, priority list, IDs) from any tool

`edit_policy()` is a blind replace: it returns `{"status": "ok"}` regardless of content. `compile_check()` returns only whether the YAML parses — no behavioral information, no rule counts, no structural summary.

---

## Scoring

After `submit()`, the submitted policy is evaluated against the gold policy using **behavioral equivalence testing**: 2000 scenarios are sampled from the full variable space, each scenario is evaluated against both policies, and the fraction of matching decisions is the score.

```
score = matches / 2000
success = score >= 0.95
```

Failure modes tracked:
- **wrong_priority**: scenario matched by multiple rules; wrong rule won due to priority error
- **stale_rule_retained**: a revoked rule remained in submitted policy
- **wrong_decision**: rule with correct conditions had wrong decision after update

---

## Variant Generation

Each task is generated from a **latent rule graph** — a Python object never shown to the agent:

1. **Domain selection**: one of four domains (refund, approval, access_control, escalation), each with domain-specific variables, decision types, and definition templates.
2. **Initial graph**: `n_rules` (12–16) rules with random conditions over domain variables, random decisions, and 40% probability of override relationships. All numeric conditions reference shared definitions via `{definition_name}` syntax.
3. **Update skeleton**: a pre-planned sequence of update types guaranteeing: 3 `change_priority` slots, 2 `revoke_rule` slots, 1 `chain_create`, 1–2 `chain_ref` (dependency chain), 1 `no_op_disguised`.
4. **Update execution**: each slot type is instantiated against the current graph state, mutates the graph, and generates a natural-language description in uniform memo style.
5. **Gold policy**: the final state of the latent graph after all updates.

### Quality controls

- **Behavioral gap filter**: tasks where the initial policy is already ≥ 85% correct are rejected and replaced from later seeds.
- **Gold self-check**: every generated task verifies that the gold policy achieves 2000/2000 behavioral equivalence with itself.
- **Ambiguity filter**: descriptions are checked against a list of vague words (`generally`, `usually`, `where appropriate`, etc.) and regenerated if found.
- **Skeleton guarantee**: every task has the minimum required number of priority swaps, revocations, and dependency chain updates.

### Scalability

- 4 domains × (12–16 initial rules) × (8–10 updates) × seed space → effectively unlimited
- New domains can be added by specifying variables, decisions, and definition templates (~30 lines of Python)
- Difficulty is controlled by the skeleton structure; content varies freely across seeds

---

## Results

| Model | Provider | Tasks | Pass Rate | Avg Score |
|-------|----------|-------|-----------|-----------|
| claude-sonnet-4-6 | Anthropic | 18 | **16.7%** | 0.772 |
| o3 | OpenAI | 20 | **10.0%** | 0.650 |

Both a standard frontier model and OpenAI's most capable reasoning model score below 17% on the ultra-hard suite. The failure mode is identical across both models.

**Dominant failure mode**: `wrong_priority` appears in 100% of failed tasks. Revoking rules mid-stream and then executing three priority swaps produces a final priority ordering that is completely unrecognizable from the initial one.

---

## Submission Checklist

- [x] Runnable code: `python run_agent.py --model claude-sonnet-4-6 --n_tasks 20 --suite ultra_only --output results/`
- [x] Deterministic reward function (behavioral equivalence, no LLM judge)
- [x] Results in target difficulty range (10–50% pass rate): **16.7% achieved**
- [x] Failure taxonomy with mechanistic labels (wrong_priority, stale_rule_retained, wrong_decision)
- [x] Infinite task generation from combinatorial space (cannot be overfit)
- [x] No oracle feedback before submission (blind edit_policy, syntax-only compile_check)
- [x] Results saved as JSON (with trajectories) and CSV
