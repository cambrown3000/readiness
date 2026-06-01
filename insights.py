# insights.py — AI insights engine powered by the Anthropic Claude API.
# Queries the SQLite database for recent Garmin and nutrition data, constructs
# a structured prompt, and calls Claude to surface cross-variable patterns
# (e.g., sleep quality vs. protein intake, HRV vs. carb timing). Returns
# formatted insight text for display in the Streamlit dashboard.

import html
import json
import os
from datetime import date
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

CACHE_PATH = Path(__file__).parent / "data" / "insights_cache.json"
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1024


# ---------------------------------------------------------------------------
# Data formatting
# ---------------------------------------------------------------------------

def _fmt(value, spec=".0f") -> str:
    return format(value, spec) if value is not None else "—"


def _build_data_summary(summary: list[dict], activities: list[dict]) -> str:
    """Render the 30-day dataset as a readable plain-text block for Claude."""

    # Aggregate stats
    rhr_vals    = [r["resting_hr"]          for r in summary if r.get("resting_hr")]
    score_vals  = [r["sleep_score"]         for r in summary if r.get("sleep_score")]
    dur_vals    = [r["total_sleep_seconds"] / 3600 for r in summary if r.get("total_sleep_seconds")]
    total_km    = sum((a.get("distance_meters") or 0) / 1000 for a in activities)
    weeks       = max(len(summary) / 7, 1)
    nutr_days   = sum(1 for r in summary if r.get("nutrition_calories"))

    def avg(vals):
        return sum(vals) / len(vals) if vals else None

    lines = ["=== AGGREGATE STATS (last 30 days) ==="]
    lines.append(f"Average resting HR:       {_fmt(avg(rhr_vals))} bpm")
    lines.append(f"Average sleep score:      {_fmt(avg(score_vals))}")
    lines.append(f"Average sleep duration:   {_fmt(avg(dur_vals), '.1f')} hours")
    lines.append(f"Total activities logged:  {len(activities)}")
    lines.append(f"Avg weekly running km:    {_fmt(total_km / weeks, '.1f')}")
    lines.append(f"Nutrition data coverage:  {nutr_days} of {len(summary)} days")
    lines.append("")

    # Daily table
    lines.append("=== DAILY DATA (newest first) ===")
    hdr = "Date       | RHR | Score | Sleep h | Deep h | Stress | Steps  | kcal | Pro | Carb | Fat | Last meal"
    lines.append(hdr)
    lines.append("-" * len(hdr))

    for r in summary[:30]:
        sleep_h = r["total_sleep_seconds"] / 3600 if r.get("total_sleep_seconds") else None
        deep_h  = r["deep_sleep_seconds"]  / 3600 if r.get("deep_sleep_seconds")  else None

        last_meal = r.get("last_meal_time") or "—"
        # Trim "YYYY-MM-DD HH:MM:SS" → "HH:MM"
        if last_meal != "—" and len(last_meal) >= 16:
            last_meal = last_meal[11:16]

        lines.append(
            f"{r['date']} | {_fmt(r.get('resting_hr')):3} | {_fmt(r.get('sleep_score')):5} | "
            f"{_fmt(sleep_h, '.1f'):7} | {_fmt(deep_h, '.1f'):6} | "
            f"{_fmt(r.get('stress_avg')):6} | {_fmt(r.get('steps')):6} | "
            f"{_fmt(r.get('nutrition_calories')):4} | {_fmt(r.get('protein_g')):3} | "
            f"{_fmt(r.get('carbs_g')):4} | {_fmt(r.get('fat_g')):3} | {last_meal}"
        )

    lines.append("")

    # Activity table
    lines.append("=== ACTIVITIES ===")
    if activities:
        lines.append("Date       | Type      | km    | min | Avg HR | Pace")
        lines.append("-" * 55)
        for a in activities:
            act_date = (a.get("start_time") or "")[:10]
            act_type = (a.get("type") or "—").replace("_", " ").title()
            km       = (a.get("distance_meters") or 0) / 1000
            mins     = (a.get("duration_seconds") or 0) / 60
            pace     = _fmt(a.get("average_pace"), ".2f") if a.get("average_pace") else "—"
            lines.append(
                f"{act_date} | {act_type:9} | {km:5.2f} | {mins:3.0f} | "
                f"{_fmt(a.get('average_hr')):6} | {pace}"
            )
    else:
        lines.append("No activities in this period.")

    return "\n".join(lines)


def _build_prompt(summary: list[dict], activities: list[dict]) -> str:
    data = _build_data_summary(summary, activities)
    return f"""You are analyzing 30 days of personal health data from a Garmin fitness tracker and nutrition tracking. Find patterns that cross multiple variables — the kind of signal the user cannot see by looking at a single metric in isolation.

{data}

Identify 3 to 5 specific, data-backed findings. Rules:
- Reference actual numbers from the data — never give generic health advice
- Focus on cross-variable relationships: e.g. how sleep quality the night before an activity affects pace or HR, whether last meal timing correlates with next-day resting HR, how stress averages track with step counts or recovery
- If nutrition data covers fewer than 10 days, note that briefly and spend the rest of the analysis on Garmin variables
- Flag any anomalies or values that stand out and are worth monitoring
- Format as numbered findings: "1. Short Label: 2-3 sentences." — no markdown headers, no dashes, no bullet points
- Total response must be under 400 words"""


# ---------------------------------------------------------------------------
# Core API call
# ---------------------------------------------------------------------------

def generate_insights(summary: list[dict], activities: list[dict]) -> str:
    """Call Claude with 30 days of health data. Returns the plain-text response."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set in .env")

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": _build_prompt(summary, activities)}],
    )
    return message.content[0].text


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _save_cache(text: str) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps({"date": date.today().isoformat(), "insights": text}))


def has_fresh_cache() -> bool:
    """Return True if today's insights are already cached on disk."""
    if not CACHE_PATH.exists():
        return False
    try:
        return json.loads(CACHE_PATH.read_text()).get("date") == date.today().isoformat()
    except Exception:
        return False


def get_cached_insights(summary: list[dict], activities: list[dict]) -> str:
    """Return today's cached insights, generating them if not yet cached."""
    if CACHE_PATH.exists():
        try:
            cached = json.loads(CACHE_PATH.read_text())
            if cached.get("date") == date.today().isoformat():
                return cached["insights"]
        except Exception:
            pass

    text = generate_insights(summary, activities)
    _save_cache(text)
    return text


def refresh_insights(summary: list[dict], activities: list[dict]) -> str:
    """Bypass cache, generate fresh insights, persist, and return."""
    text = generate_insights(summary, activities)
    _save_cache(text)
    return text


# ---------------------------------------------------------------------------
# Test block
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import database

    print("Loading data from database…")
    summary    = database.get_daily_summary(days=30)
    activities = database.get_activities(days=30)
    print(f"  {len(summary)} daily records, {len(activities)} activities\n")

    print("Calling Claude API (bypassing cache)…")
    api_key = os.getenv("ANTHROPIC_API_KEY")
    client  = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": _build_prompt(summary, activities)}],
    )

    text = message.content[0].text
    print("=" * 60)
    print(text)
    print("=" * 60)
    print(f"\nTokens — input: {message.usage.input_tokens:,}  output: {message.usage.output_tokens:,}")

    # Save to cache so the dashboard picks it up immediately
    _save_cache(text)
    print("Saved to cache.")
