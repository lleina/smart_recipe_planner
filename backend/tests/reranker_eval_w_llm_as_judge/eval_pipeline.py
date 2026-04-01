"""
Recipe Ranking Eval Pipeline
═════════════════════════════
Tests whether the rule scorer and LLM reranker are actually producing good results
by running a set of user scenarios through the live ranking code, then having an
LLM judge evaluate the results.

WHAT THIS TESTS
───────────────
1. Rule scorer hard filters   — are dietary/equipment/time constraints correctly blocking recipes?
2. Rule scorer soft scores    — are ingredient match, urgency boost, cuisine affinity working?
3. LLM reranker               — does it improve the order beyond raw rule scores?
4. LLM judge calibration      — does the judge agree with what you (Leina) would expect?

HOW TO RUN
──────────
  # From the backend directory:
  cd /home/leina/recipe_generator/backend

  # Quick test with static scenarios, rules-only (no Ollama needed for ranking):
  python -m tests.eval.eval_pipeline --static --ranking-mode rules_only --skip-judge

  # Full test with static scenarios + LLM reranker + judge:
  python -m tests.eval.eval_pipeline --static

  # Generate fresh LLM scenarios and run full eval:
  python -m tests.eval.eval_pipeline --n-scenarios 10

  # Run only specific scenario IDs (e.g. scenarios 1, 3, 5):
  python -m tests.eval.eval_pipeline --static --scenario-ids 1 3 5

OUTPUT
──────
  tests/eval/results/run_YYYYMMDD_HHMMSS.json   — full eval results
  tests/eval/results/run_YYYYMMDD_HHMMSS_summary.txt — human-readable summary

JSON STRUCTURE (per scenario):
  {
    "scenario_id": int,
    "persona_description": str,
    "user_preferences": {...},
    "session_context": {...},
    "rule_scores": [
      {
        "recipe_id": str, "title": str,
        "rule_score": float,          # -inf if hard filtered
        "hard_filtered": bool,
        "filter_reason": str | null,
        "ingredient_match_pct": float,
        "matched_ingredient_count": int,
        "total_ingredient_count": int,
        "missing_key_ingredients": list[str],
        "urgency_boost_applied": bool,
        "cuisine": str, "total_time": int
      }
    ],
    "llm_rerank_sent": list[str] | null,  # recipe IDs sent to LLM reranker
    "final_ranked": [
      {
        "rank": int,
        "rule_rank": int,
        "rerank_delta": int,          # positive = moved up
        "recipe_id": str, "title": str,
        "rule_score": float,
        "ingredient_match_pct": float,
        "missing_key_ingredients": list[str],
        "cuisine": str, "total_time": int, "rating": float
      }
    ],
    "judge": { ... }                  # from judge.py; null if --skip-judge
  }
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# ── Bootstrap path so `app.*` imports work ────────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
sys.path.insert(0, str(_BACKEND_DIR))

# ── Config ────────────────────────────────────────────────────────────────────
_DEFAULT_OLLAMA_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
_DEFAULT_MODEL = os.getenv("LLM_MODEL", "qwen3:4b")
_RESULTS_DIR = Path(__file__).parent / "results"

# How many top rule-scored recipes to send to the LLM reranker (mirrors prod)
_HYBRID_LLM_INPUT_SIZE = 15


# ── Core pipeline ─────────────────────────────────────────────────────────────

def _build_session_context(ctx_dict: dict):
    """Convert a scenario's session_context dict to a SessionContextRequest."""
    from app.schemas import SessionContextRequest, IngredientItem

    ingredients = []
    for ing in ctx_dict.get("available_ingredients", []):
        ingredients.append(
            IngredientItem(
                name=ing["name"],
                estimated_quantity=float(ing.get("quantity", 1.0)),
                unit=ing.get("unit", "pieces"),
                urgency=ing.get("urgency"),
            )
        )

    return SessionContextRequest(
        meal_type=ctx_dict.get("meal_type", "dinner"),
        serving_count=ctx_dict.get("serving_count", 2),
        available_time_minutes=ctx_dict.get("available_time_minutes", 45),
        occasion=ctx_dict.get("occasion"),
        available_ingredients=ingredients,
    )


def _detect_filter_reason(
    recipe: dict,
    context,  # SessionContextRequest
    dietary_restrictions: list[str],
    cooking_equipment: list[str],
) -> str:
    """Best-effort human-readable reason for a hard filter."""
    time_budget = context.available_time_minutes
    total_time = recipe.get("total_time", 0)

    if total_time > time_budget + 15:
        return f"time {total_time}min > budget {time_budget}min + 15"

    ingredients_lower = " ".join(
        i.get("name", "").lower() for i in recipe.get("ingredients", [])
    )
    title_lower = recipe.get("title", "").lower()

    for dr in dietary_restrictions:
        dr = dr.lower()
        if dr == "gluten-free" and any(
            w in ingredients_lower or w in title_lower
            for w in ["flour", "wheat", "gluten", "bread crumb", "soy sauce"]
            # Note: soy sauce contains wheat — approximation for display only
        ):
            return f"potential gluten ingredient detected (restriction: {dr})"
        if dr == "vegan" and any(
            w in ingredients_lower or w in title_lower
            for w in ["chicken", "beef", "pork", "lamb", "fish", "shrimp", "salmon",
                       "tuna", "egg", "milk", "butter", "cream", "cheese", "yogurt", "honey"]
        ):
            return f"non-vegan ingredient detected (restriction: {dr})"
        if dr == "vegetarian" and any(
            w in ingredients_lower or w in title_lower
            for w in ["chicken", "beef", "pork", "lamb", "fish", "shrimp", "salmon", "tuna"]
        ):
            return f"meat ingredient detected (restriction: {dr})"
        if dr == "nut-free" and any(
            w in ingredients_lower or w in title_lower
            for w in ["almond", "peanut", "walnut", "cashew", "pecan", "pistachio", "nut"]
        ):
            return f"nut ingredient detected (restriction: {dr})"
        if dr == "dairy-free" and any(
            w in ingredients_lower or w in title_lower
            for w in ["milk", "butter", "cream", "cheese", "yogurt", "mozzarella",
                       "parmesan", "ricotta", "cheddar", "feta", "pecorino"]
        ):
            return f"dairy ingredient detected (restriction: {dr})"

    # Equipment check
    required_equip = {
        "oven": ["bake", "roast", "broil", "oven"],
        "grill": ["grill"],
        "blender": ["blend"],
        "air fryer": ["air fry", "air-fry", "airfry"],
        "slow cooker": ["slow cook", "slow-cook", "crockpot"],
    }
    instructions_text = " ".join(
        step.get("text", "").lower() for step in recipe.get("instructions", [])
    )
    for appliance, keywords in required_equip.items():
        if appliance not in [e.lower() for e in cooking_equipment]:
            if any(kw in instructions_text or kw in title_lower for kw in keywords):
                return f"requires {appliance} (not in user's equipment)"

    return "rule scorer hard filter (see ranking_service for exact reason)"


async def run_scenario(
    scenario: dict,
    recipe_pool: list[dict],
    ranking_mode: str,
    ollama_url: str,
    model: str,
    skip_judge: bool,
) -> dict:
    """Run one scenario through the full eval pipeline."""
    from app.services.ranking_service import rank_recipes, score_rules, compute_ingredient_match

    prefs = scenario.get("user_preferences", {})
    ctx_dict = scenario.get("session_context", {})

    context = _build_session_context(ctx_dict)
    dietary_restrictions = prefs.get("dietary_restrictions", [])
    cuisine_preferences = prefs.get("cuisine_preferences", [])
    cooking_equipment = prefs.get("cooking_equipment", ["stove"])

    # ── Step 1: Rule score every recipe ──────────────────────────────────────
    rule_score_rows = []
    for recipe in recipe_pool:
        match_info = compute_ingredient_match(recipe, context)
        score = score_rules(
            recipe=recipe,
            context=context,
            dietary_restrictions=dietary_restrictions,
            cuisine_preferences=cuisine_preferences,
            cooking_equipment=cooking_equipment,
            match_info=match_info,
        )

        # Detect urgency boost (if any urgent ingredient is in this recipe's ingredients)
        urgent_names = {
            ing["name"].lower()
            for ing in ctx_dict.get("available_ingredients", [])
            if ing.get("urgency") is not None and ing["urgency"] <= 3
        }
        recipe_ingredient_names = {
            i.get("name", "").lower() for i in recipe.get("ingredients", [])
        }
        urgency_boost_applied = bool(urgent_names & recipe_ingredient_names)

        is_filtered = score == float("-inf")
        row = {
            "recipe_id": recipe["id"],
            "title": recipe["title"],
            "cuisine": recipe.get("cuisine", ""),
            "total_time": recipe.get("total_time", 0),
            "rating": recipe.get("rating", 0),
            "rule_score": score if not is_filtered else "-inf",
            "hard_filtered": is_filtered,
            "filter_reason": (
                _detect_filter_reason(recipe, context, dietary_restrictions, cooking_equipment)
                if is_filtered else None
            ),
            "ingredient_match_pct": match_info.get("ingredient_match_pct", 0),
            "matched_ingredient_count": match_info.get("matched_ingredient_count", 0),
            "total_ingredient_count": match_info.get("total_ingredient_count", 0),
            "missing_key_ingredients": match_info.get("missing_key_ingredients", []),
            "urgency_boost_applied": urgency_boost_applied,
        }
        rule_score_rows.append(row)

    # Sort for display: passing recipes by score desc, filtered at bottom
    rule_score_rows.sort(
        key=lambda r: (
            0 if r["hard_filtered"] else 1,
            -(r["rule_score"] if not r["hard_filtered"] else float("inf")),
        )
    )

    # ── Step 2: Full ranking (rule + optional LLM rerank) ────────────────────
    # Pass all recipes to rank_recipes — it handles filtering internally
    ranked_output = await rank_recipes(
        recipes=recipe_pool,
        context=context,
        dietary_restrictions=dietary_restrictions,
        cuisine_preferences=cuisine_preferences,
        cooking_equipment=cooking_equipment,
        mode=ranking_mode,
    )

    # Build a rule_rank lookup (rank by score before LLM reranking)
    eligible_by_score = [
        r for r in rule_score_rows
        if not r["hard_filtered"]
    ]
    rule_rank_map = {r["recipe_id"]: idx + 1 for idx, r in enumerate(eligible_by_score)}

    # Which IDs were sent to LLM reranker?
    llm_rerank_sent = None
    if ranking_mode in ("hybrid", "llm_only"):
        llm_rerank_sent = [r["recipe_id"] for r in eligible_by_score[:_HYBRID_LLM_INPUT_SIZE]]

    # Build final ranked list with before/after positions
    final_ranked = []
    for final_rank, recipe in enumerate(ranked_output, start=1):
        rid = recipe.get("id", "")
        rule_rank = rule_rank_map.get(rid, None)
        rerank_delta = (rule_rank - final_rank) if rule_rank is not None else 0

        score = recipe.get("score", 0)
        final_ranked.append({
            "rank": final_rank,
            "rule_rank": rule_rank,
            "rerank_delta": rerank_delta,
            "recipe_id": rid,
            "title": recipe.get("title", ""),
            "cuisine": recipe.get("cuisine", ""),
            "total_time": recipe.get("total_time", 0),
            "rating": recipe.get("rating", 0),
            "rule_score": score if score != float("-inf") else "-inf",
            "ingredient_match_pct": recipe.get("ingredient_match_pct", 0),
            "matched_ingredient_count": recipe.get("matched_ingredient_count", 0),
            "total_ingredient_count": recipe.get("total_ingredient_count", 0),
            "missing_key_ingredients": recipe.get("missing_key_ingredients", []),
        })

    # ── Step 3: LLM Judge ────────────────────────────────────────────────────
    judge_result = None
    if not skip_judge:
        from tests.eval.judge import judge_scenario
        print(f"    [judge] Evaluating scenario {scenario.get('id', '?')}...", flush=True)
        judge_result = await judge_scenario(
            scenario=scenario,
            ranked_results=final_ranked,
            all_rule_scores=rule_score_rows,
            pool_size=len(recipe_pool),
            ollama_url=ollama_url,
            model=model,
        )

    return {
        "scenario_id": scenario.get("id"),
        "persona_description": scenario.get("persona_description", ""),
        "user_preferences": prefs,
        "session_context": ctx_dict,
        "ranking_mode": ranking_mode,
        "pool_size": len(recipe_pool),
        "hard_filtered_count": sum(1 for r in rule_score_rows if r["hard_filtered"]),
        "eligible_count": sum(1 for r in rule_score_rows if not r["hard_filtered"]),
        "rule_scores": rule_score_rows,
        "llm_rerank_sent": llm_rerank_sent,
        "final_ranked": final_ranked,
        "judge": judge_result,
    }


# ── Aggregate stats ───────────────────────────────────────────────────────────

def compute_aggregate_stats(results: list[dict]) -> dict:
    scores = [
        r["judge"]["overall_score"]
        for r in results
        if r.get("judge") and r["judge"].get("overall_score") is not None
    ]
    avg_hard_filtered = (
        sum(r["hard_filtered_count"] for r in results) / len(results)
        if results else 0
    )
    avg_eligible = (
        sum(r["eligible_count"] for r in results) / len(results)
        if results else 0
    )
    avg_top1_match = 0
    top1_match_count = 0
    for r in results:
        if r["final_ranked"]:
            avg_top1_match += r["final_ranked"][0].get("ingredient_match_pct", 0)
            top1_match_count += 1
    if top1_match_count:
        avg_top1_match /= top1_match_count

    # Count constraint violations found by judge
    violation_count = 0
    for r in results:
        if r.get("judge") and "dimensions" in r["judge"]:
            violations = r["judge"]["dimensions"].get(
                "hard_constraint_compliance", {}
            ).get("violations_found", [])
            violation_count += len(violations)

    return {
        "scenarios_run": len(results),
        "scenarios_with_judge": len(scores),
        "avg_judge_score": round(sum(scores) / len(scores), 1) if scores else None,
        "min_judge_score": min(scores) if scores else None,
        "max_judge_score": max(scores) if scores else None,
        "avg_hard_filtered_per_scenario": round(avg_hard_filtered, 1),
        "avg_eligible_per_scenario": round(avg_eligible, 1),
        "avg_top1_ingredient_match_pct": round(avg_top1_match, 1),  # 0–100 scale
        "total_constraint_violations_found_by_judge": violation_count,
        "score_distribution": {
            "excellent_85_plus": sum(1 for s in scores if s >= 85),
            "good_70_84": sum(1 for s in scores if 70 <= s < 85),
            "mediocre_55_69": sum(1 for s in scores if 55 <= s < 70),
            "poor_below_55": sum(1 for s in scores if s < 55),
        },
    }


# ── Human-readable summary ───────────────────────────────────────────────────

def write_summary(results: list[dict], stats: dict, output_path: Path, ranking_mode: str):
    lines = [
        "═" * 70,
        "RECIPE RANKING EVAL SUMMARY",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Ranking mode: {ranking_mode}",
        "═" * 70,
        "",
        "AGGREGATE STATS",
        "─" * 40,
        f"Scenarios run:              {stats['scenarios_run']}",
        f"Avg judge score:            {stats['avg_judge_score']} / 100",
        f"Score range:                {stats['min_judge_score']} – {stats['max_judge_score']}",
        f"Avg recipes hard-filtered:  {stats['avg_hard_filtered_per_scenario']} / {stats['avg_hard_filtered_per_scenario'] + stats['avg_eligible_per_scenario']:.0f}",
        f"Avg top-1 ingredient match: {stats['avg_top1_ingredient_match_pct']:.1f}%",
        f"Constraint violations found by judge: {stats['total_constraint_violations_found_by_judge']}",
        "",
        "SCORE DISTRIBUTION",
        "─" * 40,
        f"  Excellent (85+): {stats['score_distribution']['excellent_85_plus']}",
        f"  Good     (70-84): {stats['score_distribution']['good_70_84']}",
        f"  Mediocre (55-69): {stats['score_distribution']['mediocre_55_69']}",
        f"  Poor     (<55):   {stats['score_distribution']['poor_below_55']}",
        "",
        "PER-SCENARIO RESULTS",
        "─" * 40,
    ]

    for r in results:
        judge = r.get("judge") or {}
        score = judge.get("overall_score", "N/A")
        top3 = [f["title"] for f in r["final_ranked"][:3]]
        top3_str = " | ".join(top3) if top3 else "(none)"

        violations = []
        if "dimensions" in judge:
            violations = judge["dimensions"].get(
                "hard_constraint_compliance", {}
            ).get("violations_found", [])

        lines += [
            f"",
            f"Scenario {r['scenario_id']}: {r['persona_description']}",
            f"  Judge score: {score}/100",
            f"  Hard filtered: {r['hard_filtered_count']}/{r['pool_size']} recipes",
            f"  Top 3: {top3_str}",
        ]
        if violations:
            lines.append(f"  ⚠️  VIOLATIONS: {'; '.join(violations)}")
        if "overall_summary" in judge:
            lines.append(f"  Summary: {judge['overall_summary']}")
        if "top_improvement" in judge:
            lines.append(f"  Top improvement: {judge['top_improvement']}")
        if "rule_scorer_assessment" in judge:
            lines.append(f"  Rule scorer: {judge['rule_scorer_assessment']}")
        if "llm_reranker_assessment" in judge:
            lines.append(f"  LLM reranker: {judge['llm_reranker_assessment']}")

    lines += ["", "═" * 70]

    summary_text = "\n".join(lines)
    summary_path = output_path.with_suffix("").with_name(output_path.stem + "_summary.txt")
    summary_path.write_text(summary_text)
    print(summary_text)
    return summary_path


# ── Main ─────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(
        description="Recipe ranking eval pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--n-scenarios", type=int, default=10,
        help="Number of LLM-generated scenarios (ignored if --static)",
    )
    parser.add_argument(
        "--static", action="store_true",
        help="Use the 20 hand-crafted static scenarios instead of LLM generation",
    )
    parser.add_argument(
        "--scenario-ids", type=int, nargs="+",
        help="Only run these scenario IDs (e.g. --scenario-ids 1 3 5)",
    )
    parser.add_argument(
        "--ranking-mode", default="hybrid",
        choices=["hybrid", "rules_only", "llm_only"],
        help="Ranking mode to use (default: hybrid)",
    )
    parser.add_argument(
        "--skip-judge", action="store_true",
        help="Skip LLM judge step (faster, no Ollama needed for judging)",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output JSON path (default: tests/eval/results/run_TIMESTAMP.json)",
    )
    parser.add_argument(
        "--ollama-url", default=_DEFAULT_OLLAMA_URL,
        help=f"Ollama base URL (default: {_DEFAULT_OLLAMA_URL})",
    )
    parser.add_argument(
        "--model", default=_DEFAULT_MODEL,
        help=f"Model for judge/scenario generation (default: {_DEFAULT_MODEL})",
    )
    args = parser.parse_args()

    # Determine output path
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(args.output) if args.output else (
        _RESULTS_DIR / f"run_{timestamp}.json"
    )

    print("=" * 60)
    print("RECIPE RANKING EVAL PIPELINE")
    print("=" * 60)
    print(f"Ranking mode:  {args.ranking_mode}")
    print(f"Judge enabled: {not args.skip_judge}")
    print(f"Output:        {output_path}")
    print()

    # ── Load recipe pool ──────────────────────────────────────────────────────
    from tests.eval.recipe_pool import RECIPE_POOL
    print(f"Recipe pool: {len(RECIPE_POOL)} recipes loaded")

    # ── Generate or load scenarios ────────────────────────────────────────────
    from tests.eval.scenario_generator import get_static_scenarios, generate_scenarios_llm

    if args.static:
        scenarios = get_static_scenarios()
        print(f"Scenarios: {len(scenarios)} static scenarios loaded")
    else:
        print(f"Generating {args.n_scenarios} scenarios via LLM...")
        scenarios = await generate_scenarios_llm(
            n=args.n_scenarios,
            ollama_url=args.ollama_url,
            model=args.model,
        )

    # Filter by ID if requested
    if args.scenario_ids:
        scenarios = [s for s in scenarios if s.get("id") in args.scenario_ids]
        print(f"Filtered to scenario IDs {args.scenario_ids}: {len(scenarios)} scenarios")

    print()

    # ── Run each scenario ─────────────────────────────────────────────────────
    results = []
    for i, scenario in enumerate(scenarios, start=1):
        scenario_id = scenario.get("id", i)
        print(f"[{i}/{len(scenarios)}] Scenario {scenario_id}: {scenario.get('persona_description', '')}")
        try:
            result = await run_scenario(
                scenario=scenario,
                recipe_pool=RECIPE_POOL,
                ranking_mode=args.ranking_mode,
                ollama_url=args.ollama_url,
                model=args.model,
                skip_judge=args.skip_judge,
            )
            results.append(result)

            # Quick inline status
            top1 = result["final_ranked"][0]["title"] if result["final_ranked"] else "(none)"
            filtered = result["hard_filtered_count"]
            judge_score = (
                result["judge"]["overall_score"]
                if result.get("judge") and result["judge"].get("overall_score") is not None
                else "N/A"
            )
            print(f"    → Top-1: {top1}")
            print(f"    → Hard filtered: {filtered}/{len(RECIPE_POOL)} | Judge: {judge_score}/100")
        except Exception as e:
            import traceback
            print(f"    ERROR: {e}")
            traceback.print_exc()
            results.append({
                "scenario_id": scenario_id,
                "persona_description": scenario.get("persona_description", ""),
                "error": str(e),
            })
        print()

    # ── Aggregate and write output ────────────────────────────────────────────
    stats = compute_aggregate_stats(results)

    output_data = {
        "run_id": timestamp,
        "generated_at": datetime.now().isoformat(),
        "config": {
            "ranking_mode": args.ranking_mode,
            "judge_enabled": not args.skip_judge,
            "ollama_url": args.ollama_url,
            "model": args.model,
            "pool_size": len(RECIPE_POOL),
            "scenario_source": "static" if args.static else "llm_generated",
        },
        "aggregate_stats": stats,
        "scenarios": results,
    }

    output_path.write_text(json.dumps(output_data, indent=2, default=str))
    print(f"\nResults written to: {output_path}")

    # Write human-readable summary
    summary_path = write_summary(results, stats, output_path, args.ranking_mode)
    print(f"Summary written to: {summary_path}")


if __name__ == "__main__":
    asyncio.run(main())
