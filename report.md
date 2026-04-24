# StateBench: A No-Oracle Policy-Maintenance Benchmark for Frontier Models

---

## 1. Project Summary

### The Capability Gap

Frontier models are fluent editors. Ask Claude or GPT-4o to rewrite a rule, swap a condition, or add a new clause — they will do it cleanly and confidently. But policy artifacts are not collections of independent rules. They are systems with shared definitions, priority orderings, override chains, and fallback behaviors. A single update can cascade silently across six rules at once. A priority swap can reshape which rule wins across hundreds of scenario types. A revocation can expose lower-priority rules that now become the effective policy.

**StateBench tests whether a frontier model can maintain global coherence in an evolving policy artifact under a stream of semantically specified updates — without any behavioral oracle feedback before final submission.**

The gap we found: models apply individual updates correctly about 85% of the time, but when three priority swaps and two rule revocations arrive in the same update stream, their submitted policy is wrong in 40–80% of scenarios. The failure is not editing ability — it is the failure to track cumulative global state across 8–10 interacting changes.

### Why It Is Interesting

This is not a contrived gotcha. Real-world policy maintenance — access control policies, compliance rules, pricing logic, SLA escalation trees — involves exactly this challenge: sequential human decisions that individually make sense but whose combined effect on a priority-ordered rule system is non-trivial to compute mentally. The environment formalizes a gap that matters in production software maintenance, regulatory compliance automation, and any domain where an agent is expected to serve as a coherent policy editor.

### Why We Are Well-Positioned

We built a deterministic latent rule graph generator, a domain-specific policy DSL with a compiler and behavioral verifier, and a harness that runs frontier models as agents with a constrained tool set. All three components are independently controllable: task difficulty is tunable by varying rule counts, update counts, and skeleton type without changing the scoring mechanism.

---

## 2. Environment Design

### Task

The agent is given:
1. **An initial policy artifact** — a YAML document encoding 12–16 rules with conditions, decisions, priorities, override references, and shared numeric definitions.
2. **An update stream** — 8–10 sequential policy updates written in uniform business-memo language (e.g., "When the customer tier is platinum and the purchase age exceeds 60 days, deny the refund."). Updates are intentionally indistinguishable in surface form: adds, modifies, priority swaps, revocations, default changes, and no-ops all use the same memo-style register.

The agent must produce a final YAML policy that is **behaviorally equivalent** to the gold policy — the policy that results from correctly applying all updates to the initial artifact.

### The Policy DSL

```yaml
definitions:
  standard_window: 30        # shared numeric constant
  max_refund_amount: 500

rules:
- id: r001
  conditions: []             # empty = default/fallback
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

Key DSL semantics:
- **Highest priority wins** when multiple rules match a scenario.
- **Definitions** are shared references; changing one propagates to all rules that use it.
- **Overrides** is informational metadata; the compiler uses priority numbers for resolution.
- **Empty conditions** = default rule (matches everything; always priority 1).

### Tools

The agent has exactly five tools:

| Tool | Returns | What it reveals |
|------|---------|-----------------|
| `read_policy()` | Current YAML artifact | Full artifact |
| `read_updates()` | List of update strings | Full update stream |
| `edit_policy(new_yaml)` | `{"status": "ok"}` | Nothing — blind replace |
| `compile_check()` | `{"status": "ok"}` or `{"status": "compile_error", "message": "..."}` | Syntax validity only |
| `submit()` | Final behavioral score | Revealed only after submission |

Critically absent:
- No `run_tests()` — no behavioral preview
- No `find_counterexample()` — no targeted error feedback
- No rule count, priority list, or structural summary from any tool

### Reward

After `submit()`, the submitted policy is evaluated against the gold policy using **behavioral equivalence testing**: 2000 scenarios are sampled from the full variable space, each scenario is evaluated against both policies, and the fraction of matching decisions is the score.

```
score = matches / 2000
success = score >= 0.95
```

The 0.95 threshold was chosen because a model that gets even one priority swap wrong typically fails 10–30% of scenarios — a misranked rule dominates an entire region of the scenario space, not just one edge case. 0.95 is strict enough that a single meaningful reasoning failure causes a task to fail, while allowing for minor ambiguity in how priority numbers are assigned (e.g., a rule assigned priority 8 vs. 9 when either would produce the same behavioral outcome).

Failure modes tracked:
- **wrong_priority**: scenario matched by multiple rules; wrong rule won due to priority error
- **stale_rule_retained**: a revoked rule remained in submitted policy
- **wrong_decision**: rule with correct conditions had wrong decision after update

The reward is exact and verifiable: given any two policies and any seed, the score is deterministic.

---

## 3. Prototype Implementation

The prototype has six components, all runnable:

| File | Role |
|------|------|
| `task_generator.py` | Latent rule graph + update stream generator |
| `compiler.py` | Parses YAML → Policy object, validates conditions |
| `verifier.py` | Behavioral equivalence tester (samples scenarios, compares decisions) |
| `agent_env.py` | Tool environment (5 tools, blind edit_policy, minimal compile_check) |
| `run_agent.py` | Agent harness for Claude (Anthropic) and GPT models (OpenAI) |
| `calibration.py` | Suite generator with behavioral gap filter and back-fill |

**To run the benchmark:**
```bash
pip install anthropic openai pyyaml
export ANTHROPIC_API_KEY=...
python run_agent.py --model claude-sonnet-4-6 --n_tasks 20 --suite ultra_only --output results/ --workers 3
```

**To generate and inspect tasks without running agents:**
```bash
python calibration.py   # generates 20 ultra_hard tasks, prints examples
python task_generator.py  # generates one task, shows initial policy + updates
```

---

## 4. Variant Generation Strategy

### Generation Mechanism

Each task is generated from a **latent rule graph** — a Python object that is never shown to the agent:

1. **Domain selection**: one of four domains (refund, approval, access_control, escalation), each with domain-specific variables, decision types, and definition templates.
2. **Initial graph**: `n_rules` (12–16) rules are generated with random conditions over domain variables, random decisions, and 40% probability of override relationships. All numeric conditions reference shared definitions via `{definition_name}` syntax.
3. **Update skeleton**: a pre-planned sequence of update types is selected based on `n_updates` (8–10). Each skeleton guarantees: 3 `change_priority` slots, 2 `revoke_rule` slots, 1 `chain_create`, 1–2 `chain_ref` (dependency chain), 1 `no_op_disguised`.
4. **Update execution**: each slot type is instantiated against the current graph state, mutates the graph, and generates a natural-language description in uniform memo style.
5. **Gold policy**: the final state of the latent graph after all updates.
6. **Description format**: all update descriptions use the same surface form regardless of operation type — `"When [conditions], [decision]."` — to prevent the model from inferring operation type from wording alone.

### Quality Controls

- **Behavioral gap filter**: tasks where the initial policy is already ≥ 85% correct are rejected and replaced from later seeds. This ensures every task requires meaningful changes.
- **Gold self-check**: every generated task verifies that the gold policy achieves 2000/2000 behavioral equivalence with itself (catches generator bugs).
- **Ambiguity filter**: update descriptions are checked against a list of vague words (`generally`, `usually`, `where appropriate`, etc.) and regenerated if found.
- **Skeleton guarantee**: the pre-planned skeleton ensures every task has the minimum required number of priority swaps, revocations, and dependency chain updates, regardless of random seed.

### Scalability

The space of valid tasks is enormous:
- 4 domains × (12–16 initial rules) × (8–10 updates) × seed space → effectively unlimited
- Different seeds produce different definition values, condition variable combinations, decision types, and priority orderings
- The skeleton structure means difficulty is controlled while content varies freely
- New domains can be added by specifying variables, decisions, and definition templates (~30 lines of Python)

---

## 5. Data Produced

Each benchmark run produces:

| Artifact | Description |
|----------|-------------|
| Task instances | `initial_policy` (YAML), `update_stream` (list of strings), `gold_policy` (YAML), `metadata` |
| Agent trajectories | Ordered list of `{tool, args, result}` per task |
| Final scores | Behavioral equivalence score (0–1), success flag (≥0.95) |
| Failure breakdowns | Per-task counts of `wrong_priority`, `stale_rule_retained`, `wrong_decision` |
| Static issues | Dangling override references in submitted policy |

All results are saved as JSON (with trajectories) and CSV (for analysis). Example trajectory for a passing task:

```
step 1: read_policy()     → {policy: "..."}
step 2: read_updates()    → {updates: [...]}
step 3: edit_policy(...)  → {status: "ok"}
step 4: compile_check()   → {status: "ok"}
step 5: submit()          → {final_score: 1.0, mismatches: 0}
```

---

## 6. Concrete Examples

### Example 1 — Severe Priority Failure (score: 0.366)

**Domain**: refund | **Rules**: 12 | **Updates**: 8

**Update stream:**
1. `When the customer tier is platinum, escalate to a manager.`
2. `When the purchase channel is phone, the final sale status is active, the item price is at most 100 and the customer tier is platinum both hold, offer store credit is the applicable outcome.`
3. `The separate handling for cases where the customer tier is platinum and the item condition is defective has been removed.`
4. `Where the customer tier is platinum applies, the outcome is deny the refund.`
5. `Cases satisfying both [purchase age < 100, channel in {online, in_store}, tier = silver] and [channel = phone, in_store] result in request documentation.`
6. `No distinct rule governs cases where the final sale status is not active and the customer tier is platinum or silver.`
7. `Cases satisfying both [the purchase age (in days) is less than 100, and the purchase channel is online or in store, and the customer tier is silver] and [the purchase channel is online, and the item condition is defective, and the purchase age (in days) exceeds 60] result in request documentation, not approve the refund.`
8. `Cases where the purchase channel is phone or in store should result in offer store credit.` *(no-op disguised)*

**What happened**: Claude applied update 1 (added platinum rule), update 4 (changed its decision), but failed to correctly track the three subsequent priority swaps that repositioned this rule relative to 5 others — and failed to remove the two revoked rules (updates 3 and 6). Result: 591 wrong-priority mismatches + 677 stale-rule mismatches = **score 0.366**.

---

### Example 2 — Priority + Chain Dependency Failure (score: 0.630)

**Domain**: escalation | **Rules**: 14 | **Updates**: 9

**Update stream:**
1. `Cases where the ticket age (in hours) is at most 24 should result in escalate to L2 support.` *(chain_create)*
2. `[Priority swap: ticket_age ≤ 72 vs. previous_escalations ≥ 4 AND age ≤ 24 → page_oncall wins]`
3. `The separate handling for ticket_age ≤ 8 and security_classification = not active has been removed.` *(revoke)*
4. `When the ticket age (in hours) is at most 24, take no action.` *(chain_ref — changes decision of rule from update 1)*
5. `[Priority swap: customer tier + severity + revenue impact → take no action wins]`
6. `Cases where ticket_age ≤ 24, revenue_impact = active, security = active are no longer subject to a separate rule.` *(revoke)*
7. `[Priority swap: previous_escalations < 4 vs ≥ 4 → no_action wins]`
8. `Where the ticket age (in hours) is at most 72 applies, the outcome is page the on-call engineer.` *(no-op disguised)*
9. `Where the ticket age (in hours) is at most 24 applies, the outcome is page the on-call engineer.` *(chain_ref — changes decision again)*

**What happened**: Claude tracked the chain_create (update 1) and first chain_ref (update 4) correctly, but by update 9 (second chain_ref), the three priority swaps and two revocations had made the priority ordering unrecognizable. The submitted policy had incorrect priority numbers for 7 rules. **Score: 0.630.**

---

### Example 3 — Correct (score: 1.000)

**Domain**: approval | **Rules**: 13 | **Updates**: 9

Claude correctly:
- Applied the chain_create (new rule for `amount < 100 → deny`)
- Tracked the chain_ref decision change two updates later
- Resolved all three priority swaps by incrementing the winning rule's priority above the losing rule's
- Removed both revoked rules entirely
- Identified the no_op_disguised as already-covered behavior and made no change
- Submitted a policy with 2000/2000 behavioral equivalence. **Score: 1.000.**

---

## 7. Why It Would Be Useful

### For Evaluation

StateBench targets a clean, real capability gap: **global state tracking under sequential, interacting updates**. The failure is not hallucination, not formatting error, not refusal — it is the inability to mentally execute a sequence of non-commutative mutations on a shared data structure and arrive at the correct final state. This maps directly to software engineering tasks (maintaining configuration files, updating rule engines, applying sequential migrations), legal/compliance document maintenance, and any setting where an agent must act as a coherent policy editor.

The benchmark is **hard to overfit**: tasks are generated from a combinatorial space, the scoring is exact behavioral equivalence (not rubric-based), and the update descriptions are deliberately uninformative about operation type. A model cannot game this benchmark by learning surface patterns.

### For Training

The trajectories produced — especially failures — are high-value training signal. Each failure trajectory shows exactly where a model lost track of global state: which priority swap it computed incorrectly, which revoked rule it retained, which chain_ref decision change it missed. This failure taxonomy is precise and mechanistic, enabling targeted fine-tuning or RLHF on the specific reasoning failure modes.

Correct trajectories (score = 1.0) demonstrate the desired reasoning pattern: reading both the policy and updates, mentally simulating cumulative state changes, applying all modifications in one coherent edit, and submitting confidently. These are examples of the global-coherence reasoning we want to reinforce.

The benchmark can scale to thousands of tasks across all four domains with controlled difficulty, making it suitable both as an evaluation suite and as a training data generator.

---

## Results Summary

### Calibration progression (claude-sonnet-4-6)

| Configuration | Pass Rate | Avg Score | Notes |
|---------------|-----------|-----------|-------|
| With oracle tools (run_tests + find_counterexample) | 86.7% | 0.951 | Tools leaked gold behavior; model iterated to answer |
| Oracle removed, 10-tool cap | 65.0% | 0.923 | Still too easy; compile_check provided structural hints |
| Clean memo descriptions, no oracle | 70.0% | 0.941 | Operation-type signals removed; still too easy |
| **Priority/revocation skeleton (3 swaps + 2 revocations)** | **16.7%** | **0.772** | **Target zone achieved** |

The progression from 86.7% to 16.7% documents each design decision: removing oracle feedback, removing structural leakage, and finally guaranteeing the specific update types that break global coherence tracking.

### Cross-model comparison (final benchmark configuration)

| Model | Provider | Type | Tasks | Pass Rate | Avg Score | Avg Tool Calls |
|-------|----------|------|-------|-----------|-----------|----------------|
| claude-sonnet-4-6 | Anthropic | Standard frontier | 18 | **16.7%** | 0.772 | 4.7 |
| o3 | OpenAI | Reasoning model | 20 | **10.0%** | 0.650 | 4.4 |

Both a standard frontier model and OpenAI's most capable reasoning model score below 17% on the ultra-hard suite. The reasoning model (o3) does not have a structural advantage — it fails in the same way, on the same update types. This suggests the bottleneck is not general reasoning capability but specifically the ability to track cumulative non-commutative state mutations across a shared rule system.

**Dominant failure mode**: `wrong_priority` appears in 100% of failed tasks across both models. `stale_rule_retained` appears in approximately 80% of failures. `wrong_decision` is rare, appearing in around 15% of failures and always alongside priority errors.
