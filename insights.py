import json
import os
from datetime import date, datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL      = "claude-sonnet-4-6"
MAX_TOKENS = 1024

CACHE_PATH       = Path(__file__).parent / "data" / "insights_cache.json"
TODAY_CACHE_PATH = Path(__file__).parent / "data" / "today_cache.json"


def _patterns_cache_path(days: int) -> Path:
    return Path(__file__).parent / "data" / f"patterns_cache_{days}.json"


def _make_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=api_key)


# ---------------------------------------------------------------------------
# Data formatting
# ---------------------------------------------------------------------------

def _fmt(value, spec=".0f") -> str:
    return format(value, spec) if value is not None else "—"


def _build_data_summary(summary: list[dict], activities: list[dict]) -> str:
    rhr_vals   = [r["resting_hr"]          for r in summary if r.get("resting_hr")]
    score_vals = [r["sleep_score"]         for r in summary if r.get("sleep_score")]
    dur_vals   = [r["total_sleep_seconds"] / 3600 for r in summary if r.get("total_sleep_seconds")]
    total_km   = sum((a.get("distance_meters") or 0) / 1000 for a in activities)
    weeks      = max(len(summary) / 7, 1)
    nutr_days  = sum(1 for r in summary if r.get("nutrition_calories"))

    def avg(vals):
        return sum(vals) / len(vals) if vals else None

    lines = [f"=== AGGREGATE STATS (last {len(summary)} days) ==="]
    lines.append(f"Average resting HR:       {_fmt(avg(rhr_vals))} bpm")
    lines.append(f"Average sleep score:      {_fmt(avg(score_vals))}")
    lines.append(f"Average sleep duration:   {_fmt(avg(dur_vals), '.1f')} hours")
    lines.append(f"Total activities logged:  {len(activities)}")
    lines.append(f"Avg weekly running km:    {_fmt(total_km / weeks, '.1f')}")
    lines.append(f"Nutrition data coverage:  {nutr_days} of {len(summary)} days")
    lines.append("")
    lines.append("=== DAILY DATA (newest first) ===")
    hdr = "Date       | RHR | Score | Sleep h | Deep h | Stress | Steps  | kcal | Pro | Carb | Fat | Last meal"
    lines.append(hdr)
    lines.append("-" * len(hdr))

    for r in summary:
        sleep_h   = r["total_sleep_seconds"] / 3600 if r.get("total_sleep_seconds") else None
        deep_h    = r["deep_sleep_seconds"]  / 3600 if r.get("deep_sleep_seconds")  else None
        last_meal = r.get("last_meal_time") or "—"
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


def _parse_json_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) >= 2 else text
        if text.startswith("json"):
            text = text[4:]
    text = text.strip().rstrip("`").strip()
    return json.loads(text)


# ---------------------------------------------------------------------------
# Today briefing
# ---------------------------------------------------------------------------

def generate_today_briefing(summary: list[dict], activities: list[dict]) -> dict:
    if TODAY_CACHE_PATH.exists():
        try:
            cached = json.loads(TODAY_CACHE_PATH.read_text())
            data = cached.get("data", {})
            # Require new structure — old "briefing" format triggers regeneration
            if (cached.get("date") == date.today().isoformat()
                    and isinstance(data.get("insights"), list)
                    and len(data["insights"]) > 0):
                return data
        except Exception:
            pass
    return refresh_today_briefing(summary, activities)


def refresh_today_briefing(summary: list[dict], activities: list[dict]) -> dict:
    data_block = _build_data_summary(summary[:7], activities[:10])
    prompt = f"""You are a personal health coach. Analyze this health data and return a structured JSON response.

{data_block}

Return a JSON object with exactly two keys:
- "insights": array of exactly 4 objects, in this order: Recovery, Training, Nutrition, Watch today.
  Each object has exactly three keys:
  - "title": one of "Recovery", "Training", "Nutrition", "Watch today"
  - "summary": one sentence under 20 words — the single most important finding for that category
  - "detail": 2-3 sentences referencing specific numbers from the data with actionable guidance
- "suggested_questions": array of exactly 3 strings, each under 12 words

Return ONLY valid JSON. No markdown. No code blocks. No explanation before or after."""

    client = _make_client()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        data = _parse_json_response(resp.content[0].text)
        if not isinstance(data.get("insights"), list) or len(data["insights"]) == 0:
            raise ValueError("missing insights array")
    except Exception:
        # Fallback: wrap raw text as a single insight card
        data = {
            "insights": [{"title": "Analysis", "summary": "See detail.", "detail": resp.content[0].text.strip()}],
            "suggested_questions": [],
        }

    TODAY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TODAY_CACHE_PATH.write_text(json.dumps({"date": date.today().isoformat(), "data": data}))
    return data


# ---------------------------------------------------------------------------
# Pattern analysis
# ---------------------------------------------------------------------------

def generate_pattern_analysis(summary: list[dict], activities: list[dict], days: int) -> dict:
    cache_path = _patterns_cache_path(days)
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text())
            age_hours = (datetime.now().timestamp() - cached.get("ts", 0)) / 3600
            if age_hours < 6:
                return cached["data"]
        except Exception:
            pass
    return refresh_pattern_analysis(summary, activities, days)


def refresh_pattern_analysis(summary: list[dict], activities: list[dict], days: int) -> dict:
    focus_map = {
        7:   "acute patterns and this week's trends — what happened and why",
        30:  "cross-variable correlations: how sleep, nutrition, stress, and training interact",
        180: "6-month arc: seasonal trends, fitness trajectory, persistent patterns",
        365: "12-month view: biggest improvements, persistent weaknesses, year-level lifestyle shifts",
    }
    focus = focus_map.get(days, "cross-variable health patterns")
    data_block = _build_data_summary(summary, activities)

    prompt = f"""You are analyzing {days} days of personal health data from a Garmin tracker and nutrition app.
Focus: {focus}.

{data_block}

Rules: reference actual numbers, identify cross-variable relationships, flag anomalies.

Return a JSON object with exactly two keys:
- "analysis": 200-250 words with 3-5 numbered findings in format "1. Label: explanation." No markdown headers, no bullet points.
- "suggested_questions": list of exactly 3 follow-up questions relevant to the patterns found (under 15 words each).

Return only valid JSON, no markdown code blocks."""

    client = _make_client()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=768,
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        data = _parse_json_response(resp.content[0].text)
        if "analysis" not in data:
            raise ValueError("missing analysis key")
    except Exception:
        data = {"analysis": resp.content[0].text.strip(), "suggested_questions": []}

    cache_path = _patterns_cache_path(days)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"ts": datetime.now().timestamp(), "data": data}))
    return data


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

def chat_with_data(
    messages: list[dict],
    new_message: str,
    summary: list[dict],
    activities: list[dict],
    mode: str = "today",
) -> str:
    data_block = _build_data_summary(summary[:14], activities[:20])

    if mode == "today":
        system = (
            "You are a personal health coach with access to the user's recent health data. "
            "Be conversational, specific to their numbers, and actionable. Under 200 words.\n\n"
            + data_block
        )
    else:
        system = (
            "You are a personal health analyst. Focus on long-term trends, training periodization, "
            "and lifestyle patterns. Reference specific data points. Under 250 words.\n\n"
            + data_block
        )

    api_messages = list(messages[-18:])
    while api_messages and api_messages[0]["role"] != "user":
        api_messages.pop(0)
    api_messages.append({"role": "user", "content": new_message})

    client = _make_client()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=512,
        system=system,
        messages=api_messages,
    )
    return resp.content[0].text


# ---------------------------------------------------------------------------
# Legacy cache helpers (kept for compatibility)
# ---------------------------------------------------------------------------

def _build_prompt(summary: list[dict], activities: list[dict]) -> str:
    data = _build_data_summary(summary, activities)
    return f"""You are analyzing 30 days of personal health data from a Garmin fitness tracker and nutrition tracking. Find patterns that cross multiple variables.

{data}

Identify 3 to 5 specific, data-backed findings. Rules:
- Reference actual numbers — never give generic health advice
- Focus on cross-variable relationships
- If nutrition data covers fewer than 10 days, note that and focus on Garmin variables
- Format as numbered findings: "1. Short Label: 2-3 sentences." — no markdown, no bullets
- Total response under 400 words"""


def generate_insights(summary: list[dict], activities: list[dict]) -> str:
    client = _make_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": _build_prompt(summary, activities)}],
    )
    return message.content[0].text


def _save_cache(text: str) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps({"date": date.today().isoformat(), "insights": text}))


def has_fresh_cache() -> bool:
    if not CACHE_PATH.exists():
        return False
    try:
        return json.loads(CACHE_PATH.read_text()).get("date") == date.today().isoformat()
    except Exception:
        return False


def get_cached_insights(summary: list[dict], activities: list[dict]) -> str:
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
    text = generate_insights(summary, activities)
    _save_cache(text)
    return text
