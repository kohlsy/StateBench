"""
StateBench Agent Environment

Tools: read_policy, read_updates, edit_policy, compile_check, submit.

edit_policy() is blind: returns only {"status":"ok"}.
compile_check() returns only pass/fail with minimal error message.
No behavioral feedback is available before submit().
"""

from __future__ import annotations
import json
from compiler import compile_policy, PolicyCompileError
from verifier import verify_behavioral_equivalence, run_static_checks


class StateBenchEnvironment:
    def __init__(self, task: dict, max_tool_calls: int = 50):
        self.initial_policy = task["initial_policy"]
        self.update_stream = task["update_stream"]
        self.gold_policy = task["gold_policy"]
        self.domain = task["domain"]
        self.metadata = task.get("metadata", {})

        self.current_policy = str(self.initial_policy)
        self.submitted = False
        self.tool_calls = 0
        self.max_tool_calls = max_tool_calls
        self.trajectory = []

    def _log(self, tool: str, args: dict, result: dict):
        self.trajectory.append({
            "step": self.tool_calls,
            "tool": tool,
            "args": {k: v[:200] if isinstance(v, str) else v for k, v in args.items()},
            "result": result,
        })

    # --- Tools ---

    def read_policy(self) -> dict:
        self.tool_calls += 1
        result = {"policy": self.current_policy}
        self._log("read_policy", {}, {"length": len(self.current_policy)})
        return result

    def read_updates(self) -> dict:
        self.tool_calls += 1
        result = {"updates": self.update_stream}
        self._log("read_updates", {}, {"n_updates": len(self.update_stream)})
        return result

    def edit_policy(self, new_policy: str) -> dict:
        """Blind replace — returns only status:ok. No structural hints."""
        self.tool_calls += 1
        self.current_policy = new_policy
        result = {"status": "ok"}
        self._log("edit_policy", {"policy_preview": new_policy[:200]}, result)
        return result

    def compile_check(self) -> dict:
        """Returns only ok or compile_error with a minimal message. No rule counts, no ids."""
        self.tool_calls += 1
        try:
            compile_policy(self.current_policy)
            result = {"status": "ok"}
        except PolicyCompileError as e:
            msg = str(e).split("\n")[0][:200]
            result = {"status": "compile_error", "message": msg}
        except Exception:
            result = {"status": "compile_error", "message": "Invalid YAML structure"}
        self._log("compile_check", {}, result)
        return result

    def submit(self) -> dict:
        self.tool_calls += 1
        self.submitted = True
        try:
            vr = verify_behavioral_equivalence(
                self.gold_policy, self.current_policy,
                n_scenarios=2000, seed=99999
            )
            static_issues = run_static_checks(self.current_policy)
            result = {
                "status": "submitted",
                "final_score": round(vr.score, 4),
                "total_scenarios": vr.total,
                "matches": vr.matches,
                "mismatches": len(vr.mismatches),
                "failure_breakdown": vr.summary()["failure_breakdown"],
                "static_issues": static_issues,
            }
        except Exception as e:
            result = {
                "status": "error",
                "final_score": 0.0,
                "message": str(e),
            }
        self._log("submit", {}, result)
        return result

    def get_trajectory(self) -> list[dict]:
        return self.trajectory

    def get_tool_descriptions(self) -> str:
        return """Available tools:

1. read_policy() -> Returns the current working policy YAML
2. read_updates() -> Returns the update stream to apply
3. edit_policy(new_policy: str) -> Replace the current policy with a new YAML string. Returns {"status":"ok"} only.
4. compile_check() -> Check YAML syntax. Returns {"status":"ok"} or {"status":"compile_error","message":"..."}.
5. submit() -> Submit your final policy for scoring (irreversible)

No behavioral feedback is available before submit()."""


def format_task_prompt(env: StateBenchEnvironment) -> str:
    updates_text = "\n".join(
        f"  {i+1}. {u['description']}"
        for i, u in enumerate(env.update_stream)
    )
    return f"""# Policy Update Task

## Domain
{env.domain}

## Your Task
You are given a policy written in YAML and a sequence of updates to apply.
Modify the policy so it correctly reflects ALL updates.

The policy uses a priority-based rule system:
- Each rule has conditions, a decision, and a priority level
- When multiple rules match a scenario, the highest-priority rule wins
- Rules can override other rules (listed in their 'overrides' field)
- Definitions are shared values referenced in conditions as {{name}}
- Empty conditions = default/fallback rule (matches everything)

## Current Policy
```yaml
{env.initial_policy}
```

## Updates to Apply
{updates_text}

## Critical Instructions
- You have NO behavioral oracle. You cannot check correctness before submitting.
- edit_policy() returns only {{"status":"ok"}} — no structural feedback.
- compile_check() tells you only whether the YAML parses — nothing else.
- Definition changes propagate silently to every rule that references them.
- Priority determines which rule wins — higher priority number wins.
- Some updates describe behavior already present in the policy — adding a redundant rule may break things.
- Updates may build on each other: a later update may modify something established by an earlier update.

Apply all changes correctly, then submit.
"""


if __name__ == "__main__":
    from task_generator import generate_task

    task = generate_task(domain="refund", n_rules=12, n_updates=8, seed=42,
                         interaction_bias=0.95, ultra_hard_mode=True)
    env = StateBenchEnvironment(task)

    print(format_task_prompt(env))
    print("\n" + "=" * 60)
    print("TOOL DESCRIPTIONS")
    print("=" * 60)
    print(env.get_tool_descriptions())

    print("\n" + "=" * 60)
    print("NAIVE BASELINE: submit initial policy unchanged")
    print("=" * 60)
    result = env.submit()
    print(f"Score: {result['final_score']}")
    print(f"Mismatches: {result['mismatches']}/{result['total_scenarios']}")
    print(f"Failure breakdown: {result['failure_breakdown']}")
