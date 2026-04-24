"""
StateBench Agent Runner

Runs frontier model agents (Claude, GPT) through StateBench tasks
using a tool-use loop. Saves trajectories and evaluation results.

Usage:
    python run_agent.py --demo
    python run_agent.py --model claude-sonnet-4-20250514 --n_tasks 30 --output results/
    python run_agent.py --model gpt-4o --n_tasks 30 --output results/
    python run_agent.py --model claude-sonnet-4-20250514 gpt-4o --n_tasks 30 --output results/
"""

import os
import sys
import json
import time
import argparse
import csv
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from task_generator import generate_task
from agent_env import StateBenchEnvironment, format_task_prompt
from calibration import generate_benchmark_suite


# ---------------------------------------------------------------------------
# Tool schema (provider-agnostic; converted below)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "read_policy",
        "description": "Read the current working policy YAML.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_updates",
        "description": "Read the update stream to apply.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "edit_policy",
        "description": (
            "Replace the current policy with a new YAML string. "
            "Pass the COMPLETE policy, not a diff."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "new_policy": {
                    "type": "string",
                    "description": "The complete updated policy YAML",
                }
            },
            "required": ["new_policy"],
        },
    },
    {
        "name": "compile_check",
        "description": "Check if the current policy YAML is syntactically valid. Returns {\"status\":\"ok\"} or {\"status\":\"compile_error\",\"message\":\"...\"}.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "submit",
        "description": "Submit the current policy as your final answer. Returns your score (0–1).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]

MAX_TOOL_CALLS = 50  # effectively unlimited — hardness comes from zero oracle feedback

SYSTEM_PROMPT = """You are a policy maintenance agent. Your task is to update a YAML policy to correctly reflect a set of sequential changes.

The policy DSL:
- Each rule has: id, conditions (list of boolean expressions), decision, priority (integer), optionally overrides (list of rule ids)
- Highest-priority rule wins when multiple conditions match a scenario
- Conditions reference shared definitions as {definition_name}
- Empty conditions = default/fallback rule (matches everything)
- The overrides field is informational; priority determines which rule actually wins

CRITICAL: You have NO behavioral oracle.
There is no run_tests() and no find_counterexample().
compile_check() tells you only whether the YAML parses — it gives no behavioral feedback.
edit_policy() returns only {"status":"ok"} — no structural hints.
You must reason your way to the correct policy — you cannot verify behavioral correctness before submitting.

Reasoning discipline:
- Each update states a desired behavioral outcome — you must determine what YAML change (if any) achieves it
- Some updates describe behavior already present in the current policy — the correct action is no change
- Definition changes propagate silently to EVERY rule referencing that definition — do not double-apply
- Priority determines which rule wins — higher number wins when multiple rules match
- A later update may modify something established by an earlier update in the same stream — track cumulative state
- When an update narrows or changes a previously-established rule, modify that rule rather than adding a duplicate

Think globally. A single definition change can silently alter many rules.
Submit when you are confident your policy is correct."""


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

def execute_tool(env: StateBenchEnvironment, tool_name: str, tool_input: dict) -> dict:
    if tool_name == "read_policy":
        return env.read_policy()
    elif tool_name == "read_updates":
        return env.read_updates()
    elif tool_name == "edit_policy":
        return env.edit_policy(tool_input.get("new_policy", ""))
    elif tool_name == "compile_check":
        return env.compile_check()
    elif tool_name == "submit":
        return env.submit()
    elif tool_name in ("run_tests", "find_counterexample", "check_references"):
        return {"error": f"Tool '{tool_name}' is not available."}
    else:
        return {"error": f"Unknown tool: {tool_name}"}


# ---------------------------------------------------------------------------
# Anthropic agent loop
# ---------------------------------------------------------------------------

def run_anthropic_agent(
    env: StateBenchEnvironment,
    task_prompt: str,
    model: str = "claude-sonnet-4-6",
    max_steps: int = MAX_TOOL_CALLS,
) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    anthropic_tools = [
        {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
        for t in TOOLS
    ]

    messages = [{"role": "user", "content": task_prompt}]
    steps = 0
    submitted = False
    final_result = None

    while steps < max_steps and not submitted:
        # Force submit if only 1 call left and model hasn't submitted yet
        if env.tool_calls >= env.max_tool_calls - 1 and not submitted:
            final_result = env.submit()
            submitted = True
            break

        for attempt in range(5):
            try:
                response = client.messages.create(
                    model=model,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    tools=anthropic_tools,
                    messages=messages,
                )
                break
            except Exception as e:
                if "rate_limit" in str(e).lower() or "429" in str(e):
                    wait = 20 * (attempt + 1)
                    time.sleep(wait)
                else:
                    raise
        else:
            raise RuntimeError("Rate limit retries exhausted")

        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        if response.stop_reason == "end_turn":
            final_result = env.submit()
            submitted = True
            break

        tool_results = []
        for block in assistant_content:
            if block.type == "tool_use":
                steps += 1
                result = execute_tool(env, block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                })
                if block.name == "submit":
                    final_result = result
                    submitted = True

        if tool_results:
            messages.append({"role": "user", "content": tool_results})
        elif not submitted:
            final_result = env.submit()
            submitted = True

    if not submitted:
        final_result = env.submit()

    return final_result or {"final_score": 0.0, "failure_breakdown": {}}


# ---------------------------------------------------------------------------
# OpenAI agent loop
# ---------------------------------------------------------------------------

def run_openai_agent(
    env: StateBenchEnvironment,
    task_prompt: str,
    model: str = "gpt-4o",
    max_steps: int = MAX_TOOL_CALLS,
) -> dict:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in TOOLS
    ]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task_prompt},
    ]

    steps = 0
    submitted = False
    final_result = None

    while steps < max_steps and not submitted:
        # Force submit if only 1 call left
        if env.tool_calls >= env.max_tool_calls - 1 and not submitted:
            final_result = env.submit()
            submitted = True
            break

        for attempt in range(5):
            try:
                response = client.chat.completions.create(
                    model=model,
                    tools=openai_tools,
                    messages=messages,
                )
                break
            except Exception as e:
                if "rate_limit" in str(e).lower() or "429" in str(e):
                    wait = 20 * (attempt + 1)
                    time.sleep(wait)
                else:
                    raise
        else:
            raise RuntimeError("Rate limit retries exhausted")

        choice = response.choices[0]
        msg = choice.message
        messages.append({"role": "assistant", "content": msg.content, "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in (msg.tool_calls or [])
        ] or None})

        if choice.finish_reason == "stop" or not msg.tool_calls:
            final_result = env.submit()
            submitted = True
            break

        for tc in msg.tool_calls:
            steps += 1
            try:
                tool_input = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                tool_input = {}

            result = execute_tool(env, tc.function.name, tool_input)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })

            if tc.function.name == "submit":
                final_result = result
                submitted = True

    if not submitted:
        final_result = env.submit()

    return final_result or {"final_score": 0.0, "failure_breakdown": {}}


# ---------------------------------------------------------------------------
# Task runner
# ---------------------------------------------------------------------------

def run_task(task: dict, model: str, max_steps: int = MAX_TOOL_CALLS, save_trajectory: bool = False) -> dict:
    env = StateBenchEnvironment(task, max_tool_calls=MAX_TOOL_CALLS)
    task_prompt = format_task_prompt(env)

    start = time.time()

    if "claude" in model or "anthropic" in model.lower():
        final_result = run_anthropic_agent(env, task_prompt, model=model, max_steps=max_steps)
    else:
        final_result = run_openai_agent(env, task_prompt, model=model, max_steps=max_steps)

    elapsed = time.time() - start
    score = final_result.get("final_score", 0.0)

    record = {
        "task_id": task.get("task_id", "unknown"),
        "domain": task["domain"],
        "difficulty": task.get("difficulty", "unknown"),
        "n_rules_initial": task["metadata"]["n_rules_initial"],
        "n_updates": task["metadata"]["n_updates"],
        "behavioral_diff_gold_vs_initial": task.get("behavioral_diff"),
        "model": model,
        "final_score": score,
        "success": score >= 0.95,
        "n_tool_calls": env.tool_calls,
        "elapsed_seconds": round(elapsed, 1),
        "failure_breakdown": final_result.get("failure_breakdown", {}),
        "static_issues": final_result.get("static_issues", []),
        "trajectory_length": len(env.trajectory),
    }

    if save_trajectory:
        record["trajectory"] = env.get_trajectory()

    return record


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

def run_benchmark(
    tasks: list[dict],
    models: list[str],
    output_dir: str,
    max_steps: int = 30,
    save_trajectories: bool = False,
    max_workers: int = 8,
) -> list[dict]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print_lock = threading.Lock()
    all_results = []

    for model in models:
        print(f"\n{'='*60}")
        print(f"MODEL: {model}  (workers={max_workers})")
        print(f"{'='*60}")

        completed = [0]  # mutable counter for thread-safe progress
        model_results = [None] * len(tasks)

        def _run_one(idx_task):
            i, task = idx_task
            tid = task.get("task_id", f"task_{i:04d}")
            try:
                record = run_task(task, model, max_steps=max_steps, save_trajectory=save_trajectories)
                status = "PASS" if record["success"] else "FAIL"
                line = f"  [{i+1:2d}/{len(tasks)}] {tid} ({task['domain']}, {task.get('difficulty','?')}) {status}  score={record['final_score']:.3f}  tools={record['n_tool_calls']}  ({record['elapsed_seconds']}s)"
            except Exception as e:
                record = {
                    "task_id": tid,
                    "domain": task["domain"],
                    "difficulty": task.get("difficulty", "unknown"),
                    "model": model,
                    "final_score": 0.0,
                    "success": False,
                    "n_tool_calls": 0,
                    "error": str(e),
                }
                line = f"  [{i+1:2d}/{len(tasks)}] {tid} ERROR: {e}"
            return i, record, line

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_run_one, (i, task)): i for i, task in enumerate(tasks)}
            for fut in as_completed(futures):
                i, record, line = fut.result()
                model_results[i] = record
                with print_lock:
                    print(line, flush=True)

        model_results = [r for r in model_results if r is not None]
        all_results.extend(model_results)

        model_slug = model.replace("/", "-").replace(".", "-")
        model_file = output_path / f"results_{model_slug}.json"
        with open(model_file, "w") as f:
            json.dump(model_results, f, indent=2)
        print(f"\n  Saved to {model_file}")
        _print_model_summary(model_results, model)

    combined_file = output_path / "results_combined.json"
    with open(combined_file, "w") as f:
        json.dump(all_results, f, indent=2)

    csv_file = output_path / "results.csv"
    _save_csv(all_results, csv_file)

    _print_combined_summary(all_results)
    return all_results


def _print_model_summary(results: list[dict], model: str):
    scored = [r for r in results if "error" not in r]
    successes = [r for r in scored if r.get("success")]
    print(f"\n  Summary for {model}:")
    print(f"    Tasks completed: {len(scored)}/{len(results)}")
    if scored:
        avg_score = sum(r["final_score"] for r in scored) / len(scored)
        avg_tools = sum(r.get("n_tool_calls", 0) for r in scored) / len(scored)
        print(f"    Success (≥0.95): {len(successes)}/{len(scored)} = {100*len(successes)/len(scored):.1f}%")
        print(f"    Avg score:       {avg_score:.3f}")
        print(f"    Avg tool calls:  {avg_tools:.1f}")
        print()
        for diff in ["easy", "medium", "hard", "very_hard", "ultra_hard"]:
            sub = [r for r in scored if r.get("difficulty") == diff]
            if sub:
                succ = sum(1 for r in sub if r.get("success"))
                avg = sum(r["final_score"] for r in sub) / len(sub)
                print(f"    {diff:10s}: {succ}/{len(sub)} success, avg={avg:.3f}")


def _print_combined_summary(results: list[dict]):
    print("\n" + "=" * 60)
    print("COMBINED RESULTS")
    print("=" * 60)
    models = list(dict.fromkeys(r.get("model", "") for r in results))
    for model in models:
        sub = [r for r in results if r.get("model") == model and "error" not in r]
        if not sub:
            continue
        succ = sum(1 for r in sub if r.get("success"))
        avg_score = sum(r["final_score"] for r in sub) / len(sub)
        avg_tools = sum(r.get("n_tool_calls", 0) for r in sub) / len(sub)
        print(f"\n  {model}")
        print(f"    Success rate (≥0.95): {succ}/{len(sub)} = {100*succ/len(sub):.1f}%")
        print(f"    Avg behavioral score: {avg_score:.3f}")
        print(f"    Avg tool calls:       {avg_tools:.1f}")


def _save_csv(results: list[dict], path: Path):
    if not results:
        return
    cols = [
        "task_id", "domain", "difficulty", "n_rules_initial", "n_updates",
        "behavioral_diff_gold_vs_initial", "model", "final_score", "success",
        "n_tool_calls", "elapsed_seconds",
    ]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)
    print(f"\n  CSV saved to {path}")


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def demo_single_task(model: str = "claude-sonnet-4-20250514"):
    """Run a quick demo on a single medium-difficulty task."""
    print(f"Generating demo task (refund domain, 6 rules, 4 updates)...")
    task = generate_task(domain="refund", n_rules=6, n_updates=4, seed=42)
    task["task_id"] = "demo_001"
    task["difficulty"] = "medium"

    from verifier import verify_behavioral_equivalence
    vr = verify_behavioral_equivalence(task["gold_policy"], task["initial_policy"], n_scenarios=500)
    task["behavioral_diff"] = round(1.0 - vr.score, 3)

    print(f"  Behavioral diff initial→gold: {task['behavioral_diff']*100:.1f}%")
    print(f"\nRunning {model}...\n")

    record = run_task(task, model, max_steps=20, save_trajectory=True)

    print(f"\n{'='*50}")
    print(f"RESULT")
    print(f"{'='*50}")
    print(f"  Final score:    {record['final_score']:.4f}")
    print(f"  Success (≥.95): {record['success']}")
    print(f"  Tool calls:     {record['n_tool_calls']}")
    print(f"  Elapsed:        {record['elapsed_seconds']}s")
    print(f"  Failure breakdown: {record['failure_breakdown']}")

    if record.get("trajectory"):
        print(f"\n  Tool call sequence:")
        for step in record["trajectory"]:
            print(f"    step {step['step']:2d}: {step['tool']}")

    Path("results").mkdir(exist_ok=True)
    with open("results/demo_result.json", "w") as f:
        json.dump(record, f, indent=2)
    print(f"\n  Saved to results/demo_result.json")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="StateBench Agent Runner")
    parser.add_argument(
        "--model", nargs="+",
        default=["claude-sonnet-4-20250514"],
        help="Model(s) to evaluate. Claude: claude-sonnet-4-20250514, claude-opus-4-20250514. GPT: gpt-4o, o3, o4-mini",
    )
    parser.add_argument("--n_tasks", type=int, default=20, help="Number of benchmark tasks")
    parser.add_argument("--max_steps", type=int, default=MAX_TOOL_CALLS, help="Max tool calls per task (hard cap 5)")
    parser.add_argument("--output", default="results", help="Output directory")
    parser.add_argument("--seed_start", type=int, default=0, help="Seed offset for task generation")
    parser.add_argument("--suite", default="ultra_only", choices=["ultra_only", "hard_only", "default"],
                        help="ultra_only=all ultra_hard varied; hard_only=hard/very_hard/ultra_hard; default=medium/hard/very_hard")
    parser.add_argument("--save_trajectories", action="store_true", help="Save full tool-call trajectories")
    parser.add_argument("--workers", type=int, default=8, help="Parallel workers per model")
    parser.add_argument("--demo", action="store_true", help="Run single demo task and exit")
    args = parser.parse_args()

    if args.demo:
        model = args.model[0] if args.model else "claude-sonnet-4-20250514"
        demo_single_task(model=model)
    else:
        print(f"Generating {args.n_tasks}-task benchmark suite (suite={args.suite})...")
        tasks = generate_benchmark_suite(n_tasks=args.n_tasks, seed_start=args.seed_start,
                                         suite=args.suite)
        n_rules_vals = [t["metadata"]["n_rules_initial"] for t in tasks]
        n_updates_vals = [t["metadata"]["n_updates"] for t in tasks]
        print(f"Generated {len(tasks)} tasks | "
              f"rules: {min(n_rules_vals)}-{max(n_rules_vals)} | "
              f"updates: {min(n_updates_vals)}-{max(n_updates_vals)} | "
              f"no oracle feedback\n")
        run_benchmark(
            tasks,
            args.model,
            args.output,
            max_steps=args.max_steps,
            save_trajectories=args.save_trajectories,
            max_workers=args.workers,
        )
