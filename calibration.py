"""
StateBench Difficulty Calibration

Generates tasks across difficulty levels and domains,
and reports behavioral difference between initial and gold policies
to calibrate into the 10-50% agent success zone.
"""

from task_generator import generate_task, DOMAINS
from verifier import verify_behavioral_equivalence, find_counterexample, run_static_checks
from compiler import compile_policy
import json


def calibrate_difficulty(domain: str = "refund", seeds: list[int] = None,
                         rule_counts: list[int] = None,
                         update_counts: list[int] = None):
    """
    Generate tasks at various difficulty levels and report
    how different the gold is from the initial.
    """
    if seeds is None:
        seeds = list(range(10))
    if rule_counts is None:
        rule_counts = [4, 6, 8]
    if update_counts is None:
        update_counts = [2, 4, 6, 8]

    results = []
    for n_rules in rule_counts:
        for n_updates in update_counts:
            diffs = []
            compile_failures = 0
            for seed in seeds:
                try:
                    task = generate_task(domain=domain, n_rules=n_rules,
                                        n_updates=n_updates, seed=seed)
                    # Check gold compiles
                    compile_policy(task["gold_policy"])

                    # How different is the gold from initial?
                    result = verify_behavioral_equivalence(
                        task["gold_policy"], task["initial_policy"],
                        n_scenarios=500, seed=seed
                    )
                    diffs.append(1.0 - result.score)  # fraction that differs
                except Exception as e:
                    compile_failures += 1

            if diffs:
                avg_diff = sum(diffs) / len(diffs)
                max_diff = max(diffs)
                min_diff = min(diffs)
            else:
                avg_diff = max_diff = min_diff = 0.0

            results.append({
                "n_rules": n_rules,
                "n_updates": n_updates,
                "avg_behavioral_diff": round(avg_diff, 3),
                "min_diff": round(min_diff, 3),
                "max_diff": round(max_diff, 3),
                "compile_failures": compile_failures,
                "n_tasks": len(seeds),
            })

    return results


SUITE_CONFIGS = {
    # Original mixed suite (medium → very_hard)
    "default": [
        {"n_rules": 6,  "n_updates": 4,  "label": "medium",     "interaction_bias": 0.3},
        {"n_rules": 8,  "n_updates": 6,  "label": "hard",       "interaction_bias": 0.6},
        {"n_rules": 10, "n_updates": 7,  "label": "hard",       "interaction_bias": 0.7},
        {"n_rules": 12, "n_updates": 8,  "label": "very_hard",  "interaction_bias": 0.8},
    ],
    # Hard-only suite targeting 10-50% aggregate success (no medium padding)
    "hard_only": [
        {"n_rules": 8,  "n_updates": 6,  "label": "hard",       "interaction_bias": 0.6},
        {"n_rules": 12, "n_updates": 8,  "label": "very_hard",  "interaction_bias": 0.8},
        {"n_rules": 15, "n_updates": 10, "label": "ultra_hard", "interaction_bias": 0.9},
    ],
    # Ultra-only suite: all tasks are ultra_hard with full complexity mechanisms.
    # n_rules and n_updates vary per task seed to prevent pattern exploitation.
    # Targets 10-50% aggregate success on frontier models.
    "ultra_only": [
        {
            "n_rules_range": (12, 16),
            "n_updates_range": (8, 10),
            "label": "ultra_hard",
            "interaction_bias": 0.95,
            "ultra_hard_mode": True,
        },
    ],
}


def generate_benchmark_suite(n_tasks: int = 20, seed_start: int = 0,
                              suite: str = "ultra_only") -> list[dict]:
    """
    Generate a benchmark suite across domains and difficulties.

    suite="ultra_only" → all ultra_hard, varied n_rules/n_updates per task seed
                         Full complexity: no-ops, multi-part, partial undos, chains
                         Targets 10-50% aggregate success on frontier models.
    suite="hard_only"  → hard / very_hard / ultra_hard (equal thirds)
    suite="default"    → medium / hard / very_hard (original mixed suite)
    """
    domains = list(DOMAINS.keys())
    tasks = []

    difficulty_configs = SUITE_CONFIGS[suite]

    task_id = 0
    for seed in range(seed_start, seed_start + n_tasks):
        domain = domains[seed % len(domains)]
        config = difficulty_configs[seed % len(difficulty_configs)]

        # Resolve n_rules and n_updates — fixed or seed-varied range
        if "n_rules_range" in config:
            lo, hi = config["n_rules_range"]
            n_rules = lo + (seed % (hi - lo + 1))
        else:
            n_rules = config["n_rules"]

        if "n_updates_range" in config:
            lo, hi = config["n_updates_range"]
            n_updates = lo + (seed % (hi - lo + 1))
        else:
            n_updates = config["n_updates"]

        ultra_hard_mode = config.get("ultra_hard_mode", False)

        try:
            task = generate_task(
                domain=domain,
                n_rules=n_rules,
                n_updates=n_updates,
                seed=seed,
                interaction_bias=config["interaction_bias"],
                ultra_hard_mode=ultra_hard_mode,
            )

            # Verify gold is valid
            compile_policy(task["gold_policy"])
            static_issues = run_static_checks(task["gold_policy"])

            # Measure behavioral diff
            result = verify_behavioral_equivalence(
                task["gold_policy"], task["initial_policy"],
                n_scenarios=500, seed=seed
            )

            behavioral_diff = round(1.0 - result.score, 3)

            # Skip tasks where the initial policy is already nearly correct —
            # a model that submits unchanged would trivially pass (gap < 15%).
            if behavioral_diff < 0.15:
                print(f"  Skipping seed {seed}: behavioral gap too low ({behavioral_diff:.1%})")
                continue

            task["task_id"] = f"task_{task_id:04d}"
            task["difficulty"] = config["label"]
            task["behavioral_diff"] = behavioral_diff
            task["static_issues"] = static_issues
            task["failure_breakdown"] = result.summary()["failure_breakdown"]

            tasks.append(task)
            task_id += 1

        except Exception as e:
            print(f"  Skipping seed {seed}: {e}")

    if len(tasks) < n_tasks:
        # Back-fill skipped tasks by scanning forward seeds
        extra_seed = seed_start + n_tasks
        while len(tasks) < n_tasks:
            domain = domains[extra_seed % len(domains)]
            config = difficulty_configs[extra_seed % len(difficulty_configs)]
            if "n_rules_range" in config:
                lo, hi = config["n_rules_range"]
                n_rules = lo + (extra_seed % (hi - lo + 1))
            else:
                n_rules = config["n_rules"]
            if "n_updates_range" in config:
                lo, hi = config["n_updates_range"]
                n_updates = lo + (extra_seed % (hi - lo + 1))
            else:
                n_updates = config["n_updates"]
            ultra_hard_mode = config.get("ultra_hard_mode", False)
            try:
                task = generate_task(
                    domain=domain, n_rules=n_rules, n_updates=n_updates,
                    seed=extra_seed, interaction_bias=config["interaction_bias"],
                    ultra_hard_mode=ultra_hard_mode,
                )
                compile_policy(task["gold_policy"])
                static_issues = run_static_checks(task["gold_policy"])
                result = verify_behavioral_equivalence(
                    task["gold_policy"], task["initial_policy"], n_scenarios=500, seed=extra_seed
                )
                behavioral_diff = round(1.0 - result.score, 3)
                if behavioral_diff >= 0.15:
                    task["task_id"] = f"task_{task_id:04d}"
                    task["difficulty"] = config["label"]
                    task["behavioral_diff"] = behavioral_diff
                    task["static_issues"] = static_issues
                    task["failure_breakdown"] = result.summary()["failure_breakdown"]
                    tasks.append(task)
                    task_id += 1
            except Exception:
                pass
            extra_seed += 1
            if extra_seed > seed_start + n_tasks * 10:
                break  # safety valve

    return tasks


if __name__ == "__main__":
    print("=" * 60)
    print("DIFFICULTY CALIBRATION: refund domain")
    print("=" * 60)

    results = calibrate_difficulty("refund")
    print(f"\n{'Rules':>5} {'Updates':>7} {'AvgDiff':>8} {'MinDiff':>8} {'MaxDiff':>8} {'Failures':>8}")
    print("-" * 50)
    for r in results:
        print(f"{r['n_rules']:>5} {r['n_updates']:>7} {r['avg_behavioral_diff']:>8.3f} "
              f"{r['min_diff']:>8.3f} {r['max_diff']:>8.3f} {r['compile_failures']:>8}")

    print("\n" + "=" * 60)
    print("MULTI-DOMAIN BENCHMARK SUITE (20 tasks)")
    print("=" * 60)

    tasks = generate_benchmark_suite(n_tasks=20)
    print(f"\nGenerated {len(tasks)} tasks")
    print(f"\n{'ID':>10} {'Domain':>15} {'Difficulty':>10} {'Rules':>6} {'Updates':>7} {'BehDiff':>8}")
    print("-" * 65)
    for t in tasks:
        print(f"{t['task_id']:>10} {t['domain']:>15} {t['difficulty']:>10} "
              f"{t['metadata']['n_rules_initial']:>6} {t['metadata']['n_updates']:>7} "
              f"{t['behavioral_diff']:>8.3f}")

    # Show a concrete task example
    print("\n" + "=" * 60)
    print("EXAMPLE TASK (medium difficulty, refund domain)")
    print("=" * 60)
    task = tasks[0]
    print(f"\n--- Initial Policy ---")
    print(task["initial_policy"][:600])
    print(f"\n--- Updates ({len(task['update_stream'])}) ---")
    for u in task["update_stream"]:
        print(f"  [{u['type']}] {u['description']}")
    print(f"\n--- Gold Policy (first 600 chars) ---")
    print(task["gold_policy"][:600])
    print(f"\n--- Behavioral Difference ---")
    print(f"  {task['behavioral_diff']*100:.1f}% of scenarios produce different decisions")
    print(f"  Failure breakdown: {task['failure_breakdown']}")
