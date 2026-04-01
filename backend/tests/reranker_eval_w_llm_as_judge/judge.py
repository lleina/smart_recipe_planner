"""
LLM-as-Judge for recipe ranking evaluation.

The judge evaluates the final ranked recipe list against the user scenario and
scores the pipeline across 5 dimensions. The goal is for the judge to approximate
how *you* (the primary user) would feel about these results.

CALIBRATING THE JUDGE
─────────────────────
Edit JUDGE_PERSONA_NOTES below to reflect your personal preferences.
After running the eval, compare judge scores to your own manual review.
When you disagree with the judge, update these notes and re-run.

Scoring dimensions (total 100 pts):
  1. Hard Constraint Compliance  (20 pts) — dietary, equipment, time
  2. Ingredient Utilization      (20 pts) — uses available/expiring ingredients
  3. Cuisine & Context Fit       (15 pts) — matches stated preferences and occasion
  4. Variety & Novelty           (15 pts) — top 7 cards are distinct, not repetitive
  5. Appeal & Craveworthiness    (30 pts) — would a real person actually want to make this?
"""

import json
import os
import sys

# ── Calibration: edit this to match your personal taste ──────────────────────
JUDGE_PERSONA_NOTES = """
You are judging as Leina, the app's primary user. Here is what Leina cares about:

WHAT LEINA VALUES MOST:
- Recipes that feel exciting and crave-worthy, not boring or generic.
  "Chicken and rice" is fine, but "Gochujang Butter Chicken over Crispy Rice" is great.
- Using up ingredients that are about to expire — this is a core feature of the app.
  If there's an ingredient with urgency <= 3 days and the top recipe doesn't use it,
  that's a meaningful failure.
- Cuisine authenticity matters. If the user said Korean, the top result should feel
  genuinely Korean, not just "Asian fusion" vagueness.
- Practical feasibility: if the user only has a stove, oven recipes shouldn't appear.
  If the user has 25 minutes, a 45-minute recipe at rank #1 is a hard failure.

WHAT LEINA DOES NOT WANT:
- Repetition in the top 7 cards. Two pasta dishes back-to-back, or three chicken stir
  frys, feels like the pipeline failed.
- High-rated but irrelevant recipes ranked above lower-rated but highly relevant ones.
  Rating should be a tiebreaker, not the primary signal.
- Recipes that technically pass constraints but feel like a mismatch. Example: a user
  asked for a quick weeknight dinner and got a lamb tagine that takes 2 hours.

SCORING CALIBRATION:
- 85-100: Pipeline nailed it. You'd be happy swiping through these cards.
- 70-84: Mostly good but one or two cards feel off.
- 55-69: Mediocre. Hard constraints respected but the selection isn't exciting.
- 40-54: Clear failures in relevance or variety.
- Below 40: Something went wrong — constraint violation or completely wrong recipes.
"""

# ── Judge prompts ─────────────────────────────────────────────────────────────
_JUDGE_SYSTEM_PROMPT = f"""You are an expert evaluator for a recipe recommendation app.
Your job is to judge whether the pipeline's ranked recipe results are genuinely good
for the user given their scenario.

{JUDGE_PERSONA_NOTES}

You must return ONLY a valid JSON object matching the schema provided. No explanation outside JSON."""

_JUDGE_USER_PROMPT = """Evaluate the following recipe ranking result.

═══════════════════════════════════════════════════════════════
USER SCENARIO
═══════════════════════════════════════════════════════════════
Persona: {persona_description}

User Preferences:
  Cuisines: {cuisine_preferences}
  Dietary restrictions: {dietary_restrictions}
  Health goal: {health_goal}
  Cooking equipment: {cooking_equipment}

Session Context:
  Meal type: {meal_type}
  Serving count: {serving_count}
  Time budget: {available_time_minutes} minutes
  Occasion: {occasion}

Available Ingredients:
{ingredients_list}

═══════════════════════════════════════════════════════════════
RULE SCORING SUMMARY
═══════════════════════════════════════════════════════════════
Total recipes in pool: {pool_size}
Recipes hard-filtered (score = -inf): {hard_filtered_count}
Recipes passing to ranking: {eligible_count}

Hard filter reasons:
{hard_filter_reasons}

═══════════════════════════════════════════════════════════════
FINAL RANKED RESULTS (what the user sees)
═══════════════════════════════════════════════════════════════
{ranked_recipes_text}

═══════════════════════════════════════════════════════════════
RERANKER IMPACT
═══════════════════════════════════════════════════════════════
Recipes that MOVED UP after LLM rerank: {moved_up}
Recipes that MOVED DOWN after LLM rerank: {moved_down}

═══════════════════════════════════════════════════════════════
EVALUATION TASK
═══════════════════════════════════════════════════════════════
Score this result and return a JSON object with EXACTLY this structure:

{{
  "overall_score": <int 0-100>,
  "dimensions": {{
    "hard_constraint_compliance": {{
      "score": <int 0-20>,
      "violations_found": [<list of violation strings, empty if none>],
      "notes": "<1-2 sentences>"
    }},
    "ingredient_utilization": {{
      "score": <int 0-20>,
      "urgent_ingredients_used_in_top3": [<list of ingredient names>],
      "urgent_ingredients_missed": [<list of ingredient names>],
      "notes": "<1-2 sentences>"
    }},
    "cuisine_and_context_fit": {{
      "score": <int 0-15>,
      "notes": "<1-2 sentences>"
    }},
    "variety_and_novelty": {{
      "score": <int 0-15>,
      "notes": "<1-2 sentences>"
    }},
    "appeal_and_craveworthiness": {{
      "score": <int 0-30>,
      "notes": "<2-3 sentences explaining why these recipes are or aren't exciting>"
    }}
  }},
  "recipe_verdicts": [
    {{
      "rank": <int>,
      "title": "<recipe title>",
      "verdict": "<thumbs_up | thumbs_down | neutral>",
      "reason": "<one sentence>"
    }}
  ],
  "rule_scorer_assessment": "<1-2 sentences: did the rule scorer filter and rank correctly?>",
  "llm_reranker_assessment": "<1-2 sentences: did the LLM reranker improve the order?>",
  "top_improvement": "<single most important thing that would improve this result>",
  "overall_summary": "<2-3 sentences overall assessment>"
}}

Return ONLY the JSON object. No other text."""


def _format_ingredients(ingredients: list[dict]) -> str:
    lines = []
    for ing in ingredients:
        urgency = ing.get("urgency")
        name = ing.get("name", "")
        qty = ing.get("quantity", 1)
        unit = ing.get("unit", "")
        if urgency is not None and urgency <= 3:
            lines.append(f"  ⚠️  {name} — {qty} {unit} [URGENT: expires in {urgency} day(s)]")
        else:
            lines.append(f"  • {name} — {qty} {unit}")
    return "\n".join(lines)


def _format_ranked_recipes(ranked: list[dict]) -> str:
    lines = []
    for r in ranked[:10]:  # Show top 10 to judge
        rule_rank = r.get("rule_rank", "?")
        final_rank = r.get("rank", "?")
        score = r.get("rule_score", 0)
        match_pct = r.get("ingredient_match_pct", 0)
        time = r.get("total_time", "?")
        cuisine = r.get("cuisine", "?")
        title = r.get("title", "?")
        missing = r.get("missing_key_ingredients", [])
        missing_str = f" | missing: {', '.join(missing)}" if missing else ""

        if isinstance(score, float) and score == float("-inf"):
            lines.append(f"  #{final_rank} [FILTERED] {title}")
        else:
            rerank_note = ""
            if isinstance(rule_rank, int) and isinstance(final_rank, int):
                delta = rule_rank - final_rank
                if delta > 0:
                    rerank_note = f" ↑{delta}"
                elif delta < 0:
                    rerank_note = f" ↓{abs(delta)}"
            lines.append(
                f"  #{final_rank}{rerank_note} | {title}\n"
                f"      cuisine={cuisine} | time={time}min | rule_score={score:.1f} | "
                f"ingredient_match={match_pct:.0f}%{missing_str}"
            )
    return "\n".join(lines)


async def judge_scenario(
    scenario: dict,
    ranked_results: list[dict],
    all_rule_scores: list[dict],
    pool_size: int,
    ollama_url: str,
    model: str,
) -> dict:
    """
    Run the LLM judge on one scenario's results.

    Args:
        scenario: The test scenario (persona, preferences, context)
        ranked_results: Final ranked recipe list (with rank, rule_rank, scores)
        all_rule_scores: All recipes with their rule scores (including hard-filtered)
        pool_size: Total recipes in pool before filtering
        ollama_url: Ollama base URL
        model: Model to use for judging

    Returns:
        Judge evaluation dict
    """
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
    from app.services.inference_client import ollama_chat

    prefs = scenario.get("user_preferences", {})
    ctx = scenario.get("session_context", {})

    # Count hard-filtered recipes and collect reasons
    hard_filtered = [r for r in all_rule_scores if r.get("rule_score") == float("-inf")]
    hard_filtered_count = len(hard_filtered)
    eligible_count = pool_size - hard_filtered_count

    hard_filter_reasons_text = ""
    if hard_filtered:
        reason_lines = []
        for r in hard_filtered[:8]:  # Cap at 8 to not overflow prompt
            reason = r.get("filter_reason", "unknown")
            reason_lines.append(f"  • {r.get('title', '?')}: {reason}")
        hard_filter_reasons_text = "\n".join(reason_lines)
    else:
        hard_filter_reasons_text = "  (none — all recipes passed hard filters)"

    # Compute reranker impact
    moved_up_list = []
    moved_down_list = []
    for r in ranked_results:
        rule_rank = r.get("rule_rank")
        final_rank = r.get("rank")
        if isinstance(rule_rank, int) and isinstance(final_rank, int):
            delta = rule_rank - final_rank
            if delta > 1:
                moved_up_list.append(f"{r.get('title')} (rule #{rule_rank} → final #{final_rank})")
            elif delta < -1:
                moved_down_list.append(f"{r.get('title')} (rule #{rule_rank} → final #{final_rank})")

    urgent_ingredients = [
        ing for ing in ctx.get("available_ingredients", [])
        if ing.get("urgency") is not None and ing.get("urgency") <= 3
    ]

    messages = [
        {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _JUDGE_USER_PROMPT.format(
                persona_description=scenario.get("persona_description", ""),
                cuisine_preferences=", ".join(prefs.get("cuisine_preferences", [])),
                dietary_restrictions=", ".join(prefs.get("dietary_restrictions", [])) or "none",
                health_goal=prefs.get("health_goal", "none"),
                cooking_equipment=", ".join(prefs.get("cooking_equipment", [])),
                meal_type=ctx.get("meal_type", "dinner"),
                serving_count=ctx.get("serving_count", 2),
                available_time_minutes=ctx.get("available_time_minutes", 45),
                occasion=ctx.get("occasion") or "none",
                ingredients_list=_format_ingredients(ctx.get("available_ingredients", [])),
                pool_size=pool_size,
                hard_filtered_count=hard_filtered_count,
                eligible_count=eligible_count,
                hard_filter_reasons=hard_filter_reasons_text,
                ranked_recipes_text=_format_ranked_recipes(ranked_results),
                moved_up=", ".join(moved_up_list) or "none",
                moved_down=", ".join(moved_down_list) or "none",
            ),
        },
    ]

    raw = await ollama_chat(
        base_url=ollama_url,
        model=model,
        messages=messages,
        max_tokens=2048,
        temperature=0.3,  # Low temp = consistent judgements
        think=False,
        priority="normal",
    )

    # Parse judge output
    raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        return {
            "error": "Judge did not return valid JSON",
            "raw_output": raw[:500],
            "overall_score": None,
        }

    try:
        result = json.loads(raw[start:end])
        result["urgent_ingredients_available"] = [i["name"] for i in urgent_ingredients]
        return result
    except json.JSONDecodeError as e:
        return {
            "error": f"JSON parse error: {e}",
            "raw_output": raw[:500],
            "overall_score": None,
        }
