"""
StateBench: Benchmarking Frontier Agent Policy Maintenance

A benchmark environment for evaluating whether frontier AI agents can
maintain a globally coherent rule system under sequential updates,
even with full tool access.

Core insight: Models can edit individual rules fluently, but struggle
to maintain behavioral equivalence when updates interact through
priorities, exceptions, and scope changes.
"""

import json
import sys
from task_generator import generate_task, DOMAINS
from agent_env import StateBenchEnvironment, format_task_prompt
from verifier import verify_behavioral_equivalence
from compiler import compile_policy
from calibration import generate_benchmark_suite


def demo_single_task():
    """Run a single task demonstration showing the full pipeline."""
    print("=" * 70)
    print("StateBench: Single Task Demo")
    print("=" * 70)

    # Generate a medium-difficulty task
    task = generate_task(domain="refund", n_rules=6, n_updates=4, seed=42)
    env = StateBenchEnvironment(task)

    # Show the prompt
    prompt = format_task_prompt(env)
    print(prompt)

    # Show what each tool returns
    print("\n" + "=" * 70)
    print("TOOL DEMO: What the agent can see")
    print("=" * 70)

    # Compile check
    print("\n--- compile_check() ---")
    result = env.compile_check()
    print(json.dumps(result, indent=2))

    # Run tests before any edits
    print("\n--- run_tests(n_scenarios=200) [before edits] ---")
    result = env.run_tests(200)
    print(json.dumps(result, indent=2))

    # Find counterexample
    print("\n--- find_counterexample() [before edits] ---")
    result = env.find_counterexample_tool()
    print(json.dumps(result, indent=2))

    # Check references
    print("\n--- check_references() ---")
    result = env.check_references_tool()
    print(json.dumps(result, indent=2))

    print("\n" + "=" * 70)
    print("BASELINES")
    print("=" * 70)

    # Naive: no edits
    env_naive = StateBenchEnvironment(task)
    naive_result = env_naive.submit()
    print(f"\nNaive (no edits):    {naive_result['final_score']:.1%} "
          f"({naive_result['matches']}/{naive_result['total_scenarios']})")

    # Oracle: gold policy
    env_oracle = StateBenchEnvironment(task)
    env_oracle.edit_policy(task["gold_policy"])
    oracle_result = env_oracle.submit()
    print(f"Oracle (gold):       {oracle_result['final_score']:.1%} "
          f"({oracle_result['matches']}/{oracle_result['total_scenarios']})")

    # Partial: apply updates 1-2 only (simulating an agent that gives up early)
    env_partial = StateBenchEnvironment(task)
    import yaml
    partial_policy = yaml.safe_load(env_partial.current_policy)
    # Apply just the first update manually (narrow scope)
    for rule in partial_policy["rules"]:
        if rule["id"] == "rule_2":
            rule["conditions"].append("item_condition == 'defective'")
            break
    env_partial.edit_policy(yaml.dump(partial_policy, default_flow_style=False, sort_keys=False))
    partial_result = env_partial.submit()
    print(f"Partial (1/4 edits): {partial_result['final_score']:.1%} "
          f"({partial_result['matches']}/{partial_result['total_scenarios']})")

    return task


def demo_benchmark_suite():
    """Generate and report on a full benchmark suite."""
    print("\n" + "=" * 70)
    print("StateBench: Benchmark Suite (20 tasks)")
    print("=" * 70)

    tasks = generate_benchmark_suite(n_tasks=20)

    # Compute naive baseline for each task
    print(f"\n{'ID':>10} {'Domain':>15} {'Diff':>8} {'Rules':>6} {'Updates':>7} "
          f"{'NaiveScore':>10} {'NeedsFix':>9}")
    print("-" * 75)

    scores = []
    for t in tasks:
        env = StateBenchEnvironment(t)
        result = env.submit()
        naive_score = result["final_score"]
        needs_fix = 1.0 - naive_score
        scores.append(naive_score)
        print(f"{t['task_id']:>10} {t['domain']:>15} {t['behavioral_diff']:>8.3f} "
              f"{t['metadata']['n_rules_initial']:>6} {t['metadata']['n_updates']:>7} "
              f"{naive_score:>10.1%} {needs_fix:>9.1%}")

    avg_naive = sum(scores) / len(scores)
    print(f"\n{'Average naive score:':>40} {avg_naive:.1%}")
    print(f"{'Average work needed:':>40} {1.0 - avg_naive:.1%}")


def demo_failure_annotations():
    """Show the detailed failure annotations the benchmark produces."""
    print("\n" + "=" * 70)
    print("StateBench: Failure Annotation Demo")
    print("=" * 70)

    # Generate a task with known interaction complexity
    task = generate_task(domain="escalation", n_rules=8, n_updates=6, seed=7)
    env = StateBenchEnvironment(task)

    # Submit unchanged to see failure labels
    result = env.submit()
    print(f"\nDomain: {task['domain']}")
    print(f"Rules: {task['metadata']['n_rules_initial']} initial, "
          f"{task['metadata']['n_rules_final']} after updates")
    print(f"Updates: {len(task['update_stream'])}")
    print(f"\nNaive score: {result['final_score']:.1%}")
    print(f"\nFailure breakdown:")
    for label, count in sorted(result["failure_breakdown"].items(),
                                key=lambda x: -x[1]):
        pct = count / result["total_scenarios"] * 100
        print(f"  {label:>25}: {count:>4} ({pct:.1f}%)")

    print(f"\nStatic issues: {result['static_issues'] or 'None'}")

    # Show the updates
    print(f"\nUpdate stream:")
    for u in task["update_stream"]:
        print(f"  [{u['type']}] {u['description']}")

    # Show trajectory
    print(f"\nTrajectory length: {len(env.get_trajectory())} tool calls")


if __name__ == "__main__":
    demo_single_task()
    demo_benchmark_suite()
    demo_failure_annotations()
