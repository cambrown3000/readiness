# database.py — SQLite database layer for the Readiness app.
# Defines the schema (tables for garmin_metrics, nutrition, insights),
# handles connection management, and exposes read/write helper functions
# used by garmin_sync.py, webhook.py, and insights.py.

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "readiness.db"


@contextmanager
def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_db():
    """Create all tables if they do not already exist."""
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS activities (
                activity_id      TEXT PRIMARY KEY,
                name             TEXT,
                type             TEXT,
                start_time       TEXT,
                distance_meters  REAL,
                duration_seconds REAL,
                average_hr       REAL,
                max_hr           REAL,
                average_pace     REAL,
                calories         REAL
            );

            CREATE TABLE IF NOT EXISTS sleep (
                date                 TEXT PRIMARY KEY,
                sleep_start          TEXT,
                sleep_end            TEXT,
                total_sleep_seconds  INTEGER,
                deep_sleep_seconds   INTEGER,
                light_sleep_seconds  INTEGER,
                rem_sleep_seconds    INTEGER,
                awake_seconds        INTEGER,
                sleep_score          REAL
            );

            CREATE TABLE IF NOT EXISTS hrv (
                date                TEXT PRIMARY KEY,
                hrv_weekly_average  REAL,
                hrv_last_night      REAL,
                hrv_status          TEXT
            );

            CREATE TABLE IF NOT EXISTS daily_stats (
                date               TEXT PRIMARY KEY,
                resting_hr         REAL,
                body_battery_high  REAL,
                body_battery_low   REAL,
                stress_avg         REAL,
                steps              INTEGER,
                active_calories    REAL
            );

            CREATE TABLE IF NOT EXISTS nutrition (
                date            TEXT PRIMARY KEY,
                calories        REAL,
                protein_g       REAL,
                carbs_g         REAL,
                fat_g           REAL,
                fiber_g         REAL,
                water_ml        REAL,
                last_meal_time  TEXT
            );
        """)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ms_to_iso(value) -> str | None:
    """Convert epoch milliseconds → ISO datetime string. Passes strings and None through unchanged."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return datetime.fromtimestamp(int(value) / 1000).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Upserts
# ---------------------------------------------------------------------------

def upsert_activities(records: list[dict]):
    sql = """
        INSERT OR REPLACE INTO activities
            (activity_id, name, type, start_time, distance_meters, duration_seconds,
             average_hr, max_hr, average_pace, calories)
        VALUES
            (:activity_id, :name, :type, :start_time, :distance_meters, :duration_seconds,
             :average_hr, :max_hr, :average_pace, :calories)
    """
    rows = [
        {**r, "activity_id": str(r["activity_id"])}
        for r in records
        if r.get("activity_id") is not None
    ]
    with _conn() as con:
        con.executemany(sql, rows)


def upsert_sleep(records: list[dict]):
    sql = """
        INSERT OR REPLACE INTO sleep
            (date, sleep_start, sleep_end, total_sleep_seconds, deep_sleep_seconds,
             light_sleep_seconds, rem_sleep_seconds, awake_seconds, sleep_score)
        VALUES
            (:date, :sleep_start, :sleep_end, :total_sleep_seconds, :deep_sleep_seconds,
             :light_sleep_seconds, :rem_sleep_seconds, :awake_seconds, :sleep_score)
    """
    rows = [
        {**r,
         "sleep_start": _ms_to_iso(r.get("sleep_start")),
         "sleep_end":   _ms_to_iso(r.get("sleep_end"))}
        for r in records
        if r.get("date") is not None
    ]
    with _conn() as con:
        con.executemany(sql, rows)


def upsert_hrv(records: list[dict]):
    sql = """
        INSERT OR REPLACE INTO hrv
            (date, hrv_weekly_average, hrv_last_night, hrv_status)
        VALUES
            (:date, :hrv_weekly_average, :hrv_last_night, :hrv_status)
    """
    rows = [r for r in records if r.get("date") is not None]
    with _conn() as con:
        con.executemany(sql, rows)


def upsert_daily_stats(records: list[dict]):
    sql = """
        INSERT OR REPLACE INTO daily_stats
            (date, resting_hr, body_battery_high, body_battery_low,
             stress_avg, steps, active_calories)
        VALUES
            (:date, :resting_hr, :body_battery_high, :body_battery_low,
             :stress_avg, :steps, :active_calories)
    """
    rows = [r for r in records if r.get("date") is not None]
    with _conn() as con:
        con.executemany(sql, rows)


def upsert_nutrition(records: list[dict]):
    sql = """
        INSERT OR REPLACE INTO nutrition
            (date, calories, protein_g, carbs_g, fat_g, fiber_g, water_ml, last_meal_time)
        VALUES
            (:date, :calories, :protein_g, :carbs_g, :fat_g, :fiber_g, :water_ml, :last_meal_time)
    """
    rows = [r for r in records if r.get("date") is not None]
    with _conn() as con:
        con.executemany(sql, rows)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def get_daily_summary(days: int = 30) -> list[dict]:
    """Return the most recent N days joining all wellness tables, newest first."""
    sql = """
        SELECT
            ds.date,
            ds.resting_hr,
            ds.body_battery_high,
            ds.body_battery_low,
            ds.stress_avg,
            ds.steps,
            ds.active_calories,
            s.total_sleep_seconds,
            s.deep_sleep_seconds,
            s.light_sleep_seconds,
            s.rem_sleep_seconds,
            s.awake_seconds,
            s.sleep_score,
            s.sleep_start,
            s.sleep_end,
            h.hrv_weekly_average,
            h.hrv_last_night,
            h.hrv_status,
            n.calories        AS nutrition_calories,
            n.protein_g,
            n.carbs_g,
            n.fat_g,
            n.fiber_g,
            n.water_ml,
            n.last_meal_time
        FROM      daily_stats ds
        LEFT JOIN sleep       s ON s.date = ds.date
        LEFT JOIN hrv         h ON h.date = ds.date
        LEFT JOIN nutrition   n ON n.date = ds.date
        ORDER BY  ds.date DESC
        LIMIT     :days
    """
    with _conn() as con:
        rows = con.execute(sql, {"days": days}).fetchall()
    return [dict(r) for r in rows]


def get_activities(days: int = 30) -> list[dict]:
    """Return activities from the past N days, newest first."""
    sql = """
        SELECT *
        FROM   activities
        WHERE  date(start_time) >= date('now', :offset)
        ORDER  BY start_time DESC
    """
    with _conn() as con:
        rows = con.execute(sql, {"offset": f"-{days} days"}).fetchall()
    return [dict(r) for r in rows]


def get_latest_nutrition() -> dict | None:
    """Return the single most recent nutrition record, or None."""
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM nutrition ORDER BY date DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def get_nutrition(days: int = 7) -> list[dict]:
    """Return nutrition records for the past N days, newest first."""
    sql = """
        SELECT *
        FROM   nutrition
        WHERE  date >= date('now', :offset)
        ORDER  BY date DESC
    """
    with _conn() as con:
        rows = con.execute(sql, {"offset": f"-{days} days"}).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Test block
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import garmin_sync

    print("Initializing database...")
    init_db()
    print(f"  -> Tables created at {DB_PATH}\n")

    print("Connecting to Garmin Connect...")
    client = garmin_sync.get_client()
    print("Authenticated successfully.\n")

    print("Syncing activities...")
    activities = garmin_sync.fetch_activities(client)
    upsert_activities(activities)
    print(f"  -> {len(activities)} activities upserted")

    print("Syncing sleep...")
    sleep = garmin_sync.fetch_sleep(client)
    upsert_sleep(sleep)
    print(f"  -> {len(sleep)} sleep records upserted")

    print("Syncing HRV...")
    hrv = garmin_sync.fetch_hrv(client)
    upsert_hrv(hrv)
    print(f"  -> {len(hrv)} HRV records upserted")

    print("Syncing daily stats...")
    stats = garmin_sync.fetch_daily_stats(client)
    upsert_daily_stats(stats)
    print(f"  -> {len(stats)} daily stat records upserted\n")

    print("--- get_daily_summary() — first 3 records ---")
    for row in get_daily_summary()[:3]:
        print(row)

    print()
    print("--- get_activities() — first 2 records ---")
    for row in get_activities()[:2]:
        print(row)

    print()
    print("Database populated successfully.")
