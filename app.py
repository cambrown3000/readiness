# app.py — Streamlit front-end for the Readiness dashboard.
# Handles Google OAuth login, renders daily readiness scores, activity metrics,
# nutrition data, and AI-generated insights. Pulls data from the SQLite database
# via database.py and calls insights.py for Claude-powered pattern analysis.

import html as html_lib
import os

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, datetime
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

import auth
import database
import garmin_sync
import insights

load_dotenv()

# Inject Streamlit Cloud secrets into os.environ so all os.getenv() calls work
# in production without changing any other file. Locally, .env takes precedence.
try:
    for _k, _v in st.secrets.items():
        os.environ.setdefault(_k, str(_v))
except Exception:
    pass

# ---------------------------------------------------------------------------
# Page config — must be the first Streamlit call
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Readiness",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"About": "Personal health dashboard combining Garmin + nutrition data."},
)

# Auto-refresh every 5 minutes (browser-level, no extra package needed)
st.markdown('<meta http-equiv="refresh" content="300">', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Background Garmin sync — 30-minute interval, started once per session
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
        next_run_time=datetime.now(),  # run immediately on first start
    )
    _scheduler.start()
    st.session_state["scheduler_started"] = True


# ---------------------------------------------------------------------------
# Auth — must run before any dashboard content
# ---------------------------------------------------------------------------

# Step 1: if Google just redirected back with ?code=..., exchange it for user info
_qp = st.query_params
if "code" in _qp and "user" not in st.session_state:
    with st.spinner("Signing in…"):
        _user = auth.exchange_code_for_user_info(_qp["code"], _qp.get("state"))
    st.query_params.clear()
    if _user:
        st.session_state["user"] = _user
        st.rerun()
    else:
        st.error("Sign-in failed — please try again.")

# Step 2: if no user in session yet, show the login page and stop
if "user" not in st.session_state:
    st.markdown(
        """
        <div style="
            display: flex; flex-direction: column;
            align-items: center; justify-content: center;
            height: 55vh; gap: 0.5rem;
        ">
            <h1 style="font-size: 2.5rem; margin: 0;">Readiness</h1>
            <p style="color: #6b7280; margin: 0 0 1.5rem 0; font-size: 1rem;">
                Personal health dashboard
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.link_button("Sign in with Google", auth.get_authorization_url())
    st.stop()

# Authenticated — pull user from session for the rest of the page
_user = st.session_state["user"]


# ---------------------------------------------------------------------------
# Cached data loaders — 5-minute TTL matches auto-refresh cadence
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def load_summary(days: int) -> list[dict]:
    return database.get_daily_summary(days=days)


@st.cache_data(ttl=300)
def load_activities(days: int) -> list[dict]:
    return database.get_activities(days=days)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## Readiness")
    _first_name = (_user.get("name") or "").split()[0]
    st.caption(f"{_first_name} · {_user.get('email', '')}")
    st.divider()

    days = st.selectbox(
        "Date range",
        options=[7, 14, 30, 60, 90],
        index=2,
        format_func=lambda x: f"Last {x} days",
    )

    st.divider()

    if st.button("Sync Garmin now", use_container_width=True, type="primary"):
        with st.spinner("Connecting to Garmin Connect…"):
            try:
                client = garmin_sync.get_client()
                database.upsert_activities(garmin_sync.fetch_activities(client, days=days))
                database.upsert_sleep(garmin_sync.fetch_sleep(client, days=days))
                database.upsert_hrv(garmin_sync.fetch_hrv(client, days=days))
                database.upsert_daily_stats(garmin_sync.fetch_daily_stats(client, days=days))
                st.cache_data.clear()
                st.success(f"Synced {days} days of data")
                st.rerun()
            except Exception as e:
                st.error(f"Sync failed: {e}")

    st.divider()
    st.caption(f"Loaded {datetime.now().strftime('%-I:%M %p')}")
    if st.button("Sign out", use_container_width=True):
        del st.session_state["user"]
        st.rerun()


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

summary = load_summary(days)
activities_raw = load_activities(days)

df = pd.DataFrame(summary) if summary else pd.DataFrame()
df_act = pd.DataFrame(activities_raw) if activities_raw else pd.DataFrame()

today_str = date.today().isoformat()
today_row = next((r for r in summary if r["date"] == today_str), summary[0] if summary else {})
# Use the 7 most recent days (excluding today) for delta baselines
recent_7 = [r for r in summary if r["date"] != today_str][:7]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def field_avg(rows: list[dict], key: str) -> float | None:
    vals = [r[key] for r in rows if r.get(key) is not None]
    return sum(vals) / len(vals) if vals else None


def delta_label(today_val, avg_val, unit: str = "") -> str | None:
    if today_val is None or avg_val is None:
        return None
    diff = today_val - avg_val
    sign = "+" if diff >= 0 else ""
    return f"{sign}{diff:.0f}{unit} vs 7d avg"


# Shared Plotly layout — zero-gridline, transparent background, dark-text-friendly
_CHART = dict(
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=4, r=4, t=40, b=4),
    font=dict(color="#9ca3af", size=12),
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
        marker=dict(size=5),
        showlegend=False,
    ))
    layout = dict(**_CHART, title=dict(text=title, font=dict(size=13)))
    if y_range:
        layout["yaxis"] = dict(showgrid=False, zeroline=False, showline=False, range=y_range)
    fig.update_layout(**layout)
    return fig


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.markdown(f"# Readiness")
st.markdown(f"**{date.today().strftime('%A, %B %-d, %Y')}**")
st.divider()


# ---------------------------------------------------------------------------
# Section 1 — Today's Snapshot
# ---------------------------------------------------------------------------

st.subheader("Today")

c1, c2, c3, c4 = st.columns(4)

rhr      = today_row.get("resting_hr")
rhr_avg  = field_avg(recent_7, "resting_hr")
c1.metric(
    "Resting HR",
    f"{int(rhr)} bpm" if rhr else "—",
    delta=delta_label(rhr, rhr_avg, " bpm"),
    delta_color="inverse",   # lower is better
)

sleep_score = today_row.get("sleep_score")
sleep_avg   = field_avg(recent_7, "sleep_score")
c2.metric(
    "Sleep Score",
    f"{int(sleep_score)}" if sleep_score else "—",
    delta=delta_label(sleep_score, sleep_avg),
    delta_color="normal",
)

steps      = today_row.get("steps")
steps_avg  = field_avg(recent_7, "steps")
c3.metric(
    "Steps",
    f"{int(steps):,}" if steps else "—",
    delta=delta_label(steps, steps_avg),
    delta_color="normal",
)

stress     = today_row.get("stress_avg")
stress_avg = field_avg(recent_7, "stress_avg")
c4.metric(
    "Avg Stress",
    f"{int(stress)}" if stress else "—",
    delta=delta_label(stress, stress_avg),
    delta_color="inverse",   # lower is better
)

st.divider()


# ---------------------------------------------------------------------------
# Section 2 — Trend Charts
# ---------------------------------------------------------------------------

st.subheader("Trends")

if not df.empty:
    df_plot = df.sort_values("date").copy()
    dates = df_plot["date"]

    row1_l, row1_r = st.columns(2)

    with row1_l:
        st.plotly_chart(
            line_chart(dates, df_plot["resting_hr"], "#ef4444", "Resting Heart Rate (bpm)"),
            use_container_width=True,
        )

    with row1_r:
        st.plotly_chart(
            line_chart(dates, df_plot["sleep_score"], "#818cf8", "Sleep Score", y_range=[0, 100]),
            use_container_width=True,
        )

    row2_l, row2_r = st.columns(2)

    with row2_l:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=dates, y=df_plot["nutrition_calories"],
            mode="lines+markers",
            line=dict(color="#f59e0b", width=2),
            marker=dict(size=5),
            name="Food",
        ))
        fig.add_trace(go.Scatter(
            x=dates, y=df_plot["active_calories"],
            mode="lines+markers",
            line=dict(color="#10b981", width=2, dash="dot"),
            marker=dict(size=5),
            name="Active",
        ))
        fig.update_layout(**_CHART, title=dict(text="Calories — Food vs Active", font=dict(size=13)))
        st.plotly_chart(fig, use_container_width=True)

    with row2_r:
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=dates, y=df_plot["steps"],
            marker_color="#3b82f6",
            showlegend=False,
        ))
        fig.update_layout(**_CHART, title=dict(text="Daily Steps", font=dict(size=13)), bargap=0.15)
        st.plotly_chart(fig, use_container_width=True)

else:
    st.info("No trend data available. Run a Garmin sync from the sidebar.")

st.divider()


# ---------------------------------------------------------------------------
# Section 3 — Activity Log
# ---------------------------------------------------------------------------

st.subheader("Recent Activities")

if not df_act.empty:
    act = df_act.copy()
    act["Date"]         = pd.to_datetime(act["start_time"]).dt.strftime("%b %-d")
    act["Type"]         = act["type"].str.replace("_", " ").str.title()
    act["Distance (km)"] = act["distance_meters"].apply(
        lambda x: f"{x / 1000:.2f}" if pd.notna(x) and x else "—"
    )
    act["Duration (min)"] = act["duration_seconds"].apply(
        lambda x: int(x / 60) if pd.notna(x) and x else "—"
    )
    act["Avg HR"]       = act["average_hr"].apply(
        lambda x: int(x) if pd.notna(x) and x else "—"
    )
    act["Pace (min/km)"] = act["average_pace"].apply(
        lambda x: f"{x:.2f}" if pd.notna(x) and x else "—"
    )
    act["Calories"]     = act["calories"].apply(
        lambda x: int(x) if pd.notna(x) and x else "—"
    )

    st.dataframe(
        act[["Date", "Type", "Distance (km)", "Duration (min)", "Avg HR", "Pace (min/km)", "Calories"]].head(10),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.caption("No activities in the selected date range.")

st.divider()


# ---------------------------------------------------------------------------
# Section 4 — Nutrition
# ---------------------------------------------------------------------------

st.subheader("Nutrition — Today")

kcal      = today_row.get("nutrition_calories") or 0
protein   = today_row.get("protein_g") or 0
carbs     = today_row.get("carbs_g") or 0
fat       = today_row.get("fat_g") or 0
fiber     = today_row.get("fiber_g") or 0
water_ml  = today_row.get("water_ml") or 0
last_meal = today_row.get("last_meal_time")

nc1, nc2, nc3, nc4 = st.columns(4)
nc1.metric("Calories",  f"{int(kcal):,} kcal" if kcal else "—")
nc2.metric("Protein",   f"{int(protein)}g"     if protein else "—")
nc3.metric("Carbs",     f"{int(carbs)}g"        if carbs else "—")
nc4.metric("Fat",       f"{int(fat)}g"          if fat else "—")

# Macro split bar (calories from each macro)
macro_kcal = protein * 4 + carbs * 4 + fat * 9
if macro_kcal > 0:
    macros = [
        ("Protein", protein * 4, "#818cf8"),
        ("Carbs",   carbs * 4,   "#f59e0b"),
        ("Fat",     fat * 9,     "#ef4444"),
    ]
    fig = go.Figure()
    for label, val, color in macros:
        pct = round(val / macro_kcal * 100, 1)
        fig.add_trace(go.Bar(
            name=label,
            x=[pct], y=[""],
            orientation="h",
            marker_color=color,
            text=f"{label} {pct:.0f}%",
            textposition="inside",
            insidetextanchor="middle",
            showlegend=False,
        ))
    fig.update_layout(
        barmode="stack",
        height=60,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=4, b=4),
        font=dict(color="#e5e7eb", size=11),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False, range=[0, 100]),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        hovermode=False,
    )
    st.plotly_chart(fig, use_container_width=True)

extra_l, extra_r, extra_meal, _ = st.columns([1, 1, 2, 2])
extra_l.metric("Fiber",  f"{int(fiber)}g"              if fiber    else "—")
extra_r.metric("Water",  f"{water_ml / 1000:.1f} L"    if water_ml else "—")
if last_meal:
    extra_meal.markdown(f"**Last meal:** {last_meal}")
elif kcal == 0:
    st.caption("No nutrition logged for today. Wire up the Apple Shortcut to start populating this panel.")

st.divider()


# ---------------------------------------------------------------------------
# Section 5 — Insights
# ---------------------------------------------------------------------------

st.subheader("Insights")

# Load insights — fast path if cache is fresh, API call otherwise
if insights.has_fresh_cache():
    insights_text = insights.get_cached_insights(summary, activities_raw)
else:
    with st.spinner("Analyzing your data with Claude…"):
        try:
            insights_text = insights.get_cached_insights(summary, activities_raw)
        except Exception as e:
            insights_text = None
            st.error(f"Could not generate insights: {e}")

if insights_text:
    safe = html_lib.escape(insights_text).replace("\n\n", "<br><br>").replace("\n", "<br>")
    st.markdown(
        f"""
        <div style="
            border: 2px dashed #374151;
            border-radius: 10px;
            padding: 2rem 2.25rem;
            background: rgba(255,255,255,0.015);
            color: #d1d5db;
            line-height: 1.75;
            font-size: 0.95rem;
            margin-bottom: 0.75rem;
        ">{safe}</div>
        """,
        unsafe_allow_html=True,
    )
    # Show cache date if available
    try:
        import json
        cached = json.loads(insights.CACHE_PATH.read_text())
        st.caption(f"Last analyzed: {cached.get('date', '—')}")
    except Exception:
        pass

if st.button("Refresh insights"):
    with st.spinner("Regenerating with Claude…"):
        try:
            insights.refresh_insights(summary, activities_raw)
            st.rerun()
        except Exception as e:
            st.error(f"Refresh failed: {e}")


# ---------------------------------------------------------------------------
# Direct-execution guard — ensures tables exist when running `python app.py`
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Initializing database…")
    database.init_db()
    print("Done. Run with: .venv/bin/streamlit run app.py")
