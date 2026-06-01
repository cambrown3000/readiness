import os
import re

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import date, datetime
from dotenv import load_dotenv

import auth
import database
import garmin_sync
import insights

load_dotenv()

try:
    for _k, _v in st.secrets.items():
        os.environ.setdefault(_k, str(_v))
except Exception:
    pass

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Readiness",
    page_icon="📊",
    layout="centered",
    initial_sidebar_state="collapsed",
    menu_items={"About": "Personal health dashboard combining Garmin + nutrition data."},
)

# ---------------------------------------------------------------------------
# Background Garmin sync — once per session, every 30 minutes
# ---------------------------------------------------------------------------

def _background_garmin_sync():
    try:
        client = garmin_sync.get_client()
        database.upsert_activities(garmin_sync.fetch_activities(client, days=7))
        database.upsert_sleep(garmin_sync.fetch_sleep(client, days=7))
        database.upsert_hrv(garmin_sync.fetch_hrv(client, days=7))
        database.upsert_daily_stats(garmin_sync.fetch_daily_stats(client, days=7))
        print("[scheduler] Garmin sync complete")
    except Exception as e:
        print(f"[scheduler] Garmin sync failed: {e}")


if "scheduler_started" not in st.session_state:
    database.init_db()
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _background_garmin_sync,
        "interval",
        minutes=30,
        next_run_time=datetime.now(),
    )
    _scheduler.start()
    st.session_state["scheduler_started"] = True

_qp = st.query_params

# ---------------------------------------------------------------------------
# Nutrition intake via GET query params (Apple Shortcuts)
# ---------------------------------------------------------------------------

if "nutrition" in _qp:
    _secret = os.getenv("WEBHOOK_SECRET", "")
    if _secret and _qp.get("secret") != _secret:
        st.error("Unauthorized — wrong or missing secret.")
        st.stop()
    _today = date.today().isoformat()
    _date  = _qp.get("date", _today)
    _meal  = _qp.get("last_meal_time")
    if _meal and " " not in _meal:
        _seconds = "" if _meal.count(":") >= 2 else ":00"
        _meal = f"{_date} {_meal}{_seconds}"
    _rec = {
        "date":           _date,
        "calories":       float(_qp["calories"])   if "calories"   in _qp else None,
        "protein_g":      float(_qp["protein_g"])  if "protein_g"  in _qp else None,
        "carbs_g":        float(_qp["carbs_g"])     if "carbs_g"    in _qp else None,
        "fat_g":          float(_qp["fat_g"])       if "fat_g"      in _qp else None,
        "fiber_g":        float(_qp["fiber_g"])     if "fiber_g"    in _qp else None,
        "water_ml":       float(_qp["water_ml"])    if "water_ml"   in _qp else None,
        "last_meal_time": _meal,
    }
    database.upsert_nutrition([_rec])
    st.success(f"Nutrition logged for {_rec['date']}")
    st.stop()

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

if "code" in _qp and "user" not in st.session_state:
    with st.spinner("Signing in…"):
        _user = auth.exchange_code_for_user_info(_qp["code"], _qp.get("state"))
    st.query_params.clear()
    if _user:
        st.session_state["user"] = _user
        st.rerun()
    else:
        st.error("Sign-in failed — please try again.")

if "user" not in st.session_state:
    st.markdown(
        """
        <div style="
            display:flex;flex-direction:column;align-items:center;
            justify-content:center;min-height:70vh;gap:0;
            text-align:center;padding:4rem 1rem 2rem;
            font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display','Segoe UI',sans-serif;
        ">
            <div style="font-size:3rem;margin-bottom:0.75rem;line-height:1;">&#x1F4CA;</div>
            <h1 style="font-size:clamp(2rem,6vw,3rem);font-weight:700;
                margin:0 0 0.5rem 0;letter-spacing:-0.5px;">Readiness</h1>
            <p style="color:#64748b;font-size:1.05rem;margin:0 0 1.5rem 0;font-weight:400;">
                Your personal health intelligence dashboard
            </p>
            <div style="width:40px;height:2px;background:#1e1e1e;margin:0 auto 1.5rem;"></div>
            <p style="color:#475569;font-size:0.88rem;max-width:380px;
                line-height:1.7;margin:0 0 2.5rem 0;">
                Combines Garmin training data and nutrition to surface patterns
                about your health that no single app can show you.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _c1, _c2, _c3 = st.columns([1, 1, 1])
    with _c2:
        st.link_button("Sign in with Google", auth.get_authorization_url(), use_container_width=True)
    st.markdown(
        "<p style='text-align:center;color:#334155;font-size:0.75rem;margin-top:1.25rem;'>"
        "Your data stays yours — secured with Google OAuth</p>",
        unsafe_allow_html=True,
    )
    st.stop()

_user = st.session_state["user"]

# ---------------------------------------------------------------------------
# Global design system CSS
# ---------------------------------------------------------------------------

st.markdown("""
<style>
/* === Reset & base === */
html, body, [class*="css"], .stMarkdown, p, span, div, button {
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text",
                 "Segoe UI", system-ui, sans-serif !important;
}

/* === Page background === */
.stApp, [data-testid="stAppViewContainer"] {
    background-color: #0a0a0a !important;
}
[data-testid="stAppViewBlockContainer"] {
    background-color: #0a0a0a !important;
}

/* === Hide Streamlit chrome === */
[data-testid="stHeader"] { display: none !important; }
[data-testid="stToolbar"] { display: none !important; }
#MainMenu { visibility: hidden !important; }
footer { visibility: hidden !important; }
[data-testid="collapsedControl"] { display: none !important; }

/* === Layout === */
.block-container {
    padding-top: 1.5rem !important;
    padding-bottom: 80px !important;
    max-width: 480px !important;
}

/* === Section labels === */
.section-label {
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #475569;
    margin: 1.5rem 0 0.6rem 0;
}

/* === Cards === */
.r-card {
    background: #111111;
    border: 1px solid #1f1f1f;
    border-radius: 14px;
    padding: 18px 20px;
    margin-bottom: 0.6rem;
    color: #e2e8f0;
    line-height: 1.7;
    font-size: 0.88rem;
}

/* === Metric pills === */
.pill-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin: 0.5rem 0 1.1rem;
}
.pill {
    display: inline-flex;
    align-items: center;
    gap: 0.3em;
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 0.7rem;
    font-weight: 500;
    white-space: nowrap;
    border: 1px solid;
}
.pill-label {
    opacity: 0.55;
    font-weight: 400;
}
.pill-good  { background: rgba(74,222,128,0.08); border-color: rgba(74,222,128,0.2); color: #4ade80; }
.pill-warn  { background: rgba(245,158,11,0.08); border-color: rgba(245,158,11,0.2); color: #f59e0b; }
.pill-neutral { background: #111111; border-color: #1f1f1f; color: #94a3b8; }

/* === Insight cards === */
.insight-card {
    background: #111111;
    border: 1px solid #1f1f1f;
    border-radius: 14px;
    padding: 16px 18px;
    margin-bottom: 0.6rem;
    border-left-width: 3px;
}
.insight-title {
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 0.4rem;
}
.insight-summary {
    font-size: 0.93rem;
    font-weight: 600;
    color: #f1f5f9;
    line-height: 1.4;
    margin-bottom: 0.5rem;
}
.insight-detail {
    font-size: 0.83rem;
    color: #94a3b8;
    line-height: 1.7;
    margin: 0;
}

/* === Finding cards === */
.finding-card {
    background: #111111;
    border: 1px solid #1f1f1f;
    border-radius: 14px;
    padding: 14px 18px;
    margin-bottom: 0.5rem;
    border-left-width: 3px;
}
.finding-label {
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 0.35rem;
}
.finding-body {
    font-size: 0.85rem;
    color: #94a3b8;
    line-height: 1.65;
    margin: 0;
}

/* === Nav tab bar ===
   Targets ONLY the column block that has both a primary AND secondary button
   (the 3-tab nav row). Chip columns are all-secondary and are excluded. */
[data-testid="stHorizontalBlock"]:has([data-testid="baseButton-primary"]):has([data-testid="baseButton-secondary"]) [data-testid^="stColumn"] {
    padding: 0 2px !important;
}
[data-testid="stHorizontalBlock"]:has([data-testid="baseButton-primary"]):has([data-testid="baseButton-secondary"]) button {
    background: transparent !important;
    border: none !important;
    border-bottom: 2px solid transparent !important;
    border-radius: 0 !important;
    color: #4b5563 !important;
    font-size: 0.68rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.1em !important;
    text-transform: uppercase !important;
    padding: 8px 4px 10px !important;
    box-shadow: none !important;
    transition: color 0.15s, border-color 0.15s !important;
}
[data-testid="stHorizontalBlock"]:has([data-testid="baseButton-primary"]):has([data-testid="baseButton-secondary"]) [data-testid="baseButton-primary"] {
    color: #f1f5f9 !important;
    border-bottom-color: #3b82f6 !important;
}
[data-testid="stHorizontalBlock"]:has([data-testid="baseButton-primary"]):has([data-testid="baseButton-secondary"]) button:hover {
    color: #cbd5e1 !important;
}

/* === Question chips === */
[data-testid="stHorizontalBlock"]:not(:has([data-testid="baseButton-primary"])) button,
.stButton:not(:has([data-testid="baseButton-primary"])) button[data-testid="baseButton-secondary"] {
    background: #111111 !important;
    border: 1px solid #1f1f1f !important;
    border-radius: 20px !important;
    color: #64748b !important;
    font-size: 0.78rem !important;
    font-weight: 400 !important;
    padding: 6px 14px !important;
    text-transform: none !important;
    letter-spacing: normal !important;
    box-shadow: none !important;
}

/* === Divider === */
hr { border-color: #1a1a1a !important; }

/* === Chat === */
[data-testid="stChatMessage"] {
    background: #111111 !important;
    border: 1px solid #1f1f1f !important;
    border-radius: 12px !important;
    margin-bottom: 0.4rem !important;
}
[data-testid="stChatInputContainer"] {
    background: #111111 !important;
    border: 1px solid #1f1f1f !important;
    border-radius: 12px !important;
}

/* === Dataframe === */
[data-testid="stDataFrame"] {
    border-radius: 12px !important;
    overflow: hidden;
}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------

for _key, _default in [
    ("active_tab",       "today"),
    ("today_messages",   []),
    ("pattern_messages", []),
    ("pattern_window",   30),
]:
    if _key not in st.session_state:
        st.session_state[_key] = _default

active_tab = st.session_state["active_tab"]

# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def load_summary(days: int) -> list[dict]:
    return database.get_daily_summary(days=days)

@st.cache_data(ttl=300)
def load_activities(days: int) -> list[dict]:
    return database.get_activities(days=days)

# ---------------------------------------------------------------------------
# Tab callback and navigation
# ---------------------------------------------------------------------------

def _set_tab(tab: str):
    st.session_state["active_tab"] = tab


_nc1, _nc2, _nc3 = st.columns(3)
with _nc1:
    st.button(
        "Today",
        key="nav_today",
        on_click=_set_tab, args=("today",),
        use_container_width=True,
        type="primary" if active_tab == "today" else "secondary",
    )
with _nc2:
    st.button(
        "Patterns",
        key="nav_patterns",
        on_click=_set_tab, args=("patterns",),
        use_container_width=True,
        type="primary" if active_tab == "patterns" else "secondary",
    )
with _nc3:
    st.button(
        "History",
        key="nav_history",
        on_click=_set_tab, args=("history",),
        use_container_width=True,
        type="primary" if active_tab == "history" else "secondary",
    )

st.divider()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def field_avg(rows: list[dict], key: str) -> float | None:
    vals = [r[key] for r in rows if r.get(key) is not None]
    return sum(vals) / len(vals) if vals else None


_CHART = dict(
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=4, r=4, t=36, b=4),
    font=dict(color="#64748b", size=11),
    xaxis=dict(showgrid=False, zeroline=False, showline=False),
    yaxis=dict(showgrid=False, zeroline=False, showline=False),
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)


def line_chart(x, y, color: str, title: str, y_range=None) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=y,
        mode="lines+markers",
        line=dict(color=color, width=2),
        marker=dict(size=4),
        showlegend=False,
    ))
    layout = dict(**_CHART, title=dict(text=title, font=dict(size=12, color="#94a3b8")))
    if y_range:
        layout["yaxis"] = dict(showgrid=False, zeroline=False, showline=False, range=y_range)
    fig.update_layout(**layout)
    return fig


def _pill_html(label: str, value: str, state: str = "neutral") -> str:
    return (
        f'<div class="pill pill-{state}">'
        f'<span class="pill-label">{label}</span>'
        f'<span>{value}</span>'
        f'</div>'
    )


def _insight_colors() -> dict:
    return {
        "Recovery":   "#4ade80",
        "Training":   "#3b82f6",
        "Nutrition":  "#f59e0b",
        "Watch today": "#a78bfa",
    }


def _insight_card_html(title: str, summary: str, detail: str) -> str:
    colors = _insight_colors()
    accent = colors.get(title, "#3b82f6")
    return (
        f'<div class="insight-card" style="border-left-color:{accent};">'
        f'<div class="insight-title" style="color:{accent};">{title}</div>'
        f'<div class="insight-summary">{summary}</div>'
        f'<p class="insight-detail">{detail}</p>'
        f'</div>'
    )


_FINDING_COLORS = ["#3b82f6", "#4ade80", "#f59e0b", "#a78bfa"]


def _parse_findings(text: str) -> list[str]:
    parts = re.split(r'(?=\b\d+\.\s)', text.strip())
    return [p.strip() for p in parts if p.strip()]


def _finding_card_html(index: int, text: str) -> str:
    accent = _FINDING_COLORS[index % len(_FINDING_COLORS)]
    label_match = re.match(r'^\d+\.\s+([^:]+):(.*)', text, re.DOTALL)
    if label_match:
        label = label_match.group(1).strip()
        body  = label_match.group(2).strip()
    else:
        label = f"Finding {index + 1}"
        body  = re.sub(r'^\d+\.\s*', '', text).strip()
    return (
        f'<div class="finding-card" style="border-left-color:{accent};">'
        f'<div class="finding-label" style="color:{accent};">{label}</div>'
        f'<p class="finding-body">{body}</p>'
        f'</div>'
    )


def _greeting() -> str:
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning"
    elif hour < 17:
        return "Good afternoon"
    return "Good evening"


def _send_chat(msg_key: str, new_message: str, summary, activities, mode: str):
    history = list(st.session_state[msg_key])
    st.session_state[msg_key].append({"role": "user", "content": new_message})
    try:
        response = insights.chat_with_data(history, new_message, summary, activities, mode=mode)
    except Exception as e:
        response = f"Unable to process that request right now. ({e})"
    st.session_state[msg_key].append({"role": "assistant", "content": response})
    st.rerun()


def _render_chat(msg_key: str, summary, activities, mode: str, input_key: str):
    for msg in st.session_state[msg_key][-20:]:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
    user_input = st.chat_input("Ask about your health data…", key=input_key)
    if user_input:
        _send_chat(msg_key, user_input, summary, activities, mode)


def _render_chips(questions: list, msg_key: str, prefix: str, summary, activities, mode: str):
    if not questions:
        return
    for i, q in enumerate(questions[:3]):
        if st.button(q, key=f"{prefix}_{i}", use_container_width=True):
            _send_chat(msg_key, q, summary, activities, mode)


# ---------------------------------------------------------------------------
# Screen: Today
# ---------------------------------------------------------------------------

def render_today():
    summary_7    = load_summary(7)
    activities_7 = load_activities(7)
    today_str    = date.today().isoformat()
    today_row    = next((r for r in summary_7 if r["date"] == today_str),
                        summary_7[0] if summary_7 else {})

    # Time-of-day greeting
    first_name = (_user.get("name") or "").split()[0]
    st.markdown(
        f'<h2 style="font-size:clamp(1.5rem,4vw,2rem);font-weight:700;'
        f'letter-spacing:-0.4px;margin:0 0 0.1rem 0;line-height:1.2;color:#f1f5f9;">'
        f'{_greeting()}, {first_name}</h2>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p class="section-label" style="margin-top:0.15rem;">'
        f'{date.today().strftime("%A, %B %-d, %Y")}</p>',
        unsafe_allow_html=True,
    )

    # Metric pills with conditional coloring
    def fv(key): return today_row.get(key)

    def _hr_state(v):
        if v is None: return "neutral"
        return "good" if v <= 58 else ("warn" if v > 68 else "neutral")

    def _sleep_state(v):
        if v is None: return "neutral"
        return "good" if v >= 80 else ("warn" if v < 60 else "neutral")

    def _hrv_state(v):
        if v is None: return "neutral"
        return "good" if v >= 50 else ("warn" if v < 30 else "neutral")

    def _battery_state(v):
        if v is None: return "neutral"
        return "good" if v >= 60 else ("warn" if v < 30 else "neutral")

    def _steps_state(v):
        if v is None: return "neutral"
        return "good" if v >= 8000 else ("warn" if v < 4000 else "neutral")

    pills = []
    if fv("resting_hr"):
        pills.append(_pill_html("HR", f"{int(fv('resting_hr'))} bpm", _hr_state(fv("resting_hr"))))
    if fv("sleep_score"):
        pills.append(_pill_html("Sleep", str(int(fv("sleep_score"))), _sleep_state(fv("sleep_score"))))
    if fv("hrv_last_night"):
        pills.append(_pill_html("HRV", f"{int(fv('hrv_last_night'))}ms", _hrv_state(fv("hrv_last_night"))))
    if fv("body_battery_high"):
        pills.append(_pill_html("Battery", str(int(fv("body_battery_high"))), _battery_state(fv("body_battery_high"))))
    if fv("steps"):
        pills.append(_pill_html("Steps", f"{int(fv('steps')):,}", _steps_state(fv("steps"))))
    if pills:
        st.markdown('<div class="pill-row">' + "".join(pills) + "</div>",
                    unsafe_allow_html=True)

    if not summary_7:
        st.info("No health data yet — sync Garmin from the History tab to get started.")
        return

    # Briefing header
    col_title, col_btn = st.columns([5, 1])
    with col_title:
        st.markdown('<p class="section-label">Today\'s Briefing</p>', unsafe_allow_html=True)
    with col_btn:
        refresh_clicked = st.button("↺", key="refresh_today", help="Regenerate briefing")

    # Load or generate briefing
    if refresh_clicked:
        with st.spinner("Regenerating…"):
            try:
                briefing_data = insights.refresh_today_briefing(summary_7, activities_7)
                st.session_state["today_briefing"] = briefing_data
            except Exception as e:
                st.error(f"Could not refresh: {e}")
                briefing_data = st.session_state.get("today_briefing", {})
    elif "today_briefing" not in st.session_state:
        with st.spinner("Generating your daily briefing…"):
            try:
                briefing_data = insights.generate_today_briefing(summary_7, activities_7)
                st.session_state["today_briefing"] = briefing_data
            except Exception as e:
                st.markdown(
                    f'<div class="r-card" style="color:#ef4444;border-left:3px solid #ef4444;">'
                    f'Could not generate briefing: {e}</div>',
                    unsafe_allow_html=True,
                )
                briefing_data = {}
    else:
        briefing_data = st.session_state["today_briefing"]

    # Insight cards — custom HTML, always expanded
    insight_list = briefing_data.get("insights", [])
    if insight_list:
        cards_html = "".join(
            _insight_card_html(
                card.get("title", "Insight"),
                card.get("summary", ""),
                card.get("detail", ""),
            )
            for card in insight_list
        )
        st.markdown(cards_html, unsafe_allow_html=True)

    # Suggested follow-up chips
    questions = briefing_data.get("suggested_questions", [])
    if questions:
        st.markdown('<p class="section-label" style="margin-top:1rem;">Follow-up</p>',
                    unsafe_allow_html=True)
        _render_chips(questions, "today_messages", "today_chip",
                      summary_7, activities_7, "today")

    st.divider()
    _render_chat("today_messages", summary_7, activities_7, "today", "today_chat")


# ---------------------------------------------------------------------------
# Screen: Patterns
# ---------------------------------------------------------------------------

def render_patterns():
    window_map    = {"7 days": 7, "30 days": 30, "6 months": 180, "12 months": 365}
    window_labels = list(window_map.keys())
    current_days  = st.session_state["pattern_window"]
    current_label = next((k for k, v in window_map.items() if v == current_days), "30 days")

    try:
        selected = st.segmented_control(
            "Time window",
            window_labels,
            default=current_label,
            label_visibility="collapsed",
        )
        if selected is None:
            selected = current_label
    except AttributeError:
        selected = st.radio(
            "Time window",
            window_labels,
            index=window_labels.index(current_label),
            horizontal=True,
            label_visibility="collapsed",
        )

    days = window_map[selected]
    if days != st.session_state["pattern_window"]:
        st.session_state["pattern_window"] = days
        cache_key = f"pattern_analysis_{days}"
        if cache_key in st.session_state:
            del st.session_state[cache_key]

    summary    = load_summary(days)
    activities = load_activities(days)

    if not summary:
        st.info("No data for this window — sync Garmin from the History tab.")
        return

    # Analysis header
    col_title, col_btn = st.columns([5, 1])
    with col_title:
        st.markdown('<p class="section-label">Pattern Analysis</p>', unsafe_allow_html=True)
    with col_btn:
        refresh_clicked = st.button("↺", key="refresh_patterns", help="Regenerate analysis")

    cache_key = f"pattern_analysis_{days}"
    if refresh_clicked:
        with st.spinner("Regenerating…"):
            try:
                analysis_data = insights.refresh_pattern_analysis(summary, activities, days)
                st.session_state[cache_key] = analysis_data
            except Exception as e:
                st.error(f"Could not refresh: {e}")
                analysis_data = st.session_state.get(cache_key, {})
    elif cache_key not in st.session_state:
        with st.spinner(f"Analyzing {selected} of data…"):
            try:
                analysis_data = insights.generate_pattern_analysis(summary, activities, days)
                st.session_state[cache_key] = analysis_data
            except Exception as e:
                st.markdown(
                    f'<div class="r-card" style="color:#ef4444;border-left:3px solid #ef4444;">'
                    f'Could not generate analysis: {e}</div>',
                    unsafe_allow_html=True,
                )
                analysis_data = {}
    else:
        analysis_data = st.session_state[cache_key]

    # Parse numbered findings into individual cards
    analysis_text = analysis_data.get("analysis", "")
    if analysis_text:
        findings = _parse_findings(analysis_text)
        if findings:
            cards_html = "".join(_finding_card_html(i, f) for i, f in enumerate(findings))
            st.markdown(cards_html, unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="r-card">{analysis_text}</div>', unsafe_allow_html=True)

    # Charts
    if summary:
        df    = pd.DataFrame(summary).sort_values("date")
        dates = df["date"]

        st.markdown('<p class="section-label">Sleep</p>', unsafe_allow_html=True)
        st.plotly_chart(
            line_chart(dates, df["sleep_score"], "#818cf8",
                       "Sleep Score", y_range=[0, 100]),
            use_container_width=True,
        )

        st.markdown('<p class="section-label">Training Load</p>', unsafe_allow_html=True)
        act_df = pd.DataFrame(load_activities(days))
        if not act_df.empty:
            act_df["day"] = pd.to_datetime(act_df["start_time"]).dt.date.astype(str)
            daily_km = (
                act_df.groupby("day")["distance_meters"]
                .sum()
                .div(1000)
                .reset_index(name="km")
            )
            fig = go.Figure(go.Bar(
                x=daily_km["day"], y=daily_km["km"],
                marker_color="#10b981", showlegend=False,
            ))
            fig.update_layout(
                **_CHART,
                title=dict(text="Activity Distance (km)", font=dict(size=12, color="#94a3b8")),
                bargap=0.2,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.markdown('<p class="section-label" style="color:#374151;">No activities in this period.</p>',
                        unsafe_allow_html=True)

        st.markdown('<p class="section-label">Recovery</p>', unsafe_allow_html=True)
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=dates, y=df["resting_hr"], mode="lines+markers",
            name="Resting HR", line=dict(color="#ef4444", width=2),
            marker=dict(size=4),
        ))
        if df["hrv_last_night"].notna().any():
            fig.add_trace(go.Scatter(
                x=dates, y=df["hrv_last_night"], mode="lines+markers",
                name="HRV", line=dict(color="#3b82f6", width=2, dash="dot"),
                marker=dict(size=4), yaxis="y2",
            ))
            fig.update_layout(
                yaxis2=dict(overlaying="y", side="right",
                            showgrid=False, zeroline=False, showline=False),
            )
        fig.update_layout(
            **_CHART,
            title=dict(text="Resting HR & HRV", font=dict(size=12, color="#94a3b8")),
        )
        st.plotly_chart(fig, use_container_width=True)

        if df["nutrition_calories"].notna().any():
            st.markdown('<p class="section-label">Nutrition</p>', unsafe_allow_html=True)
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=dates, y=df["nutrition_calories"], mode="lines+markers",
                name="Calories", line=dict(color="#f59e0b", width=2),
                marker=dict(size=4),
            ))
            fig.add_trace(go.Scatter(
                x=dates, y=df["protein_g"].apply(lambda x: x * 4 if x else None),
                mode="lines+markers", name="Protein kcal",
                line=dict(color="#818cf8", width=1, dash="dot"),
                marker=dict(size=3),
            ))
            fig.update_layout(
                **_CHART,
                title=dict(text="Calories & Protein", font=dict(size=12, color="#94a3b8")),
            )
            st.plotly_chart(fig, use_container_width=True)

    # Follow-up chips + chat
    questions = analysis_data.get("suggested_questions", [])
    if questions:
        st.markdown('<p class="section-label" style="margin-top:0.5rem;">Follow-up</p>',
                    unsafe_allow_html=True)
        _render_chips(questions, "pattern_messages", "pattern_chip",
                      summary, activities, "patterns")

    st.divider()
    _render_chat("pattern_messages", summary, activities, "patterns", "patterns_chat")


# ---------------------------------------------------------------------------
# Screen: History
# ---------------------------------------------------------------------------

def render_history():
    summary_30    = load_summary(30)
    activities_30 = load_activities(30)

    # Sync controls
    sync_col, info_col = st.columns([2, 3])
    with sync_col:
        if st.button("Sync Garmin", type="primary", use_container_width=True):
            with st.spinner("Connecting to Garmin Connect…"):
                try:
                    gc = garmin_sync.get_client()
                    database.upsert_activities(garmin_sync.fetch_activities(gc, days=30))
                    database.upsert_sleep(garmin_sync.fetch_sleep(gc, days=30))
                    database.upsert_hrv(garmin_sync.fetch_hrv(gc, days=30))
                    database.upsert_daily_stats(garmin_sync.fetch_daily_stats(gc, days=30))
                    st.cache_data.clear()
                    st.success("Synced 30 days of data")
                    st.rerun()
                except Exception as e:
                    st.error(f"Sync failed: {e}")
    with info_col:
        st.markdown(
            f'<p class="section-label" style="padding-top:0.55rem;">'
            f'Updated {datetime.now().strftime("%-I:%M %p")}</p>',
            unsafe_allow_html=True,
        )

    # Activities
    st.markdown('<p class="section-label">Activities</p>', unsafe_allow_html=True)
    if activities_30:
        act = pd.DataFrame(activities_30).copy()
        act["Date"]           = pd.to_datetime(act["start_time"]).dt.strftime("%b %-d")
        act["Type"]           = act["type"].str.replace("_", " ").str.title()
        act["Distance (km)"]  = act["distance_meters"].apply(
            lambda x: f"{x/1000:.2f}" if pd.notna(x) and x else "—"
        )
        act["Duration (min)"] = act["duration_seconds"].apply(
            lambda x: int(x / 60) if pd.notna(x) and x else "—"
        )
        act["Avg HR"]         = act["average_hr"].apply(
            lambda x: int(x) if pd.notna(x) and x else "—"
        )
        act["Pace"]           = act["average_pace"].apply(
            lambda x: f"{x:.2f}" if pd.notna(x) and x else "—"
        )
        act["Calories"]       = act["calories"].apply(
            lambda x: int(x) if pd.notna(x) and x else "—"
        )
        st.dataframe(
            act[["Date", "Type", "Distance (km)", "Duration (min)",
                 "Avg HR", "Pace", "Calories"]].head(30),
            use_container_width=True, hide_index=True,
        )
    else:
        st.markdown('<p style="color:#374151;font-size:0.85rem;">No activities found.</p>',
                    unsafe_allow_html=True)

    # Daily stats
    st.markdown('<p class="section-label">Daily Stats</p>', unsafe_allow_html=True)
    if summary_30:
        df = pd.DataFrame(summary_30)[
            ["date", "resting_hr", "sleep_score", "stress_avg",
             "steps", "active_calories", "hrv_last_night", "body_battery_high"]
        ].copy()
        df.columns = ["Date", "RHR", "Sleep", "Stress", "Steps",
                      "Active kcal", "HRV", "Battery"]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.markdown('<p style="color:#374151;font-size:0.85rem;">No stats found.</p>',
                    unsafe_allow_html=True)

    # Sleep log
    st.markdown('<p class="section-label">Sleep Log</p>', unsafe_allow_html=True)
    if summary_30:
        df = pd.DataFrame(summary_30)[
            ["date", "sleep_score", "total_sleep_seconds",
             "deep_sleep_seconds", "rem_sleep_seconds", "awake_seconds"]
        ].copy()
        for col in ["total_sleep_seconds", "deep_sleep_seconds",
                    "rem_sleep_seconds", "awake_seconds"]:
            df[col] = df[col].apply(
                lambda x: round(x / 3600, 1) if pd.notna(x) and x else None
            )
        df.columns = ["Date", "Score", "Total h", "Deep h", "REM h", "Awake h"]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.markdown('<p style="color:#374151;font-size:0.85rem;">No sleep data found.</p>',
                    unsafe_allow_html=True)

    # Nutrition log
    nutr = [r for r in summary_30 if r.get("nutrition_calories")]
    st.markdown('<p class="section-label">Nutrition Log</p>', unsafe_allow_html=True)
    if nutr:
        df = pd.DataFrame(nutr)[
            ["date", "nutrition_calories", "protein_g",
             "carbs_g", "fat_g", "fiber_g", "water_ml"]
        ].copy()
        df.columns = ["Date", "Calories", "Protein g", "Carbs g",
                      "Fat g", "Fiber g", "Water ml"]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.markdown('<p style="color:#374151;font-size:0.85rem;">No nutrition data logged yet.</p>',
                    unsafe_allow_html=True)

    st.divider()
    st.markdown(
        f'<p class="section-label">Signed in as {_user.get("email", "")}</p>',
        unsafe_allow_html=True,
    )
    if st.button("Sign out", use_container_width=True):
        del st.session_state["user"]
        st.rerun()


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

if active_tab == "today":
    render_today()
elif active_tab == "patterns":
    render_patterns()
else:
    render_history()
