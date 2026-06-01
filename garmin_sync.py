# garmin_sync.py — Scheduled Garmin data sync using APScheduler.
# Authenticates with the Garmin Connect API, fetches daily activity, sleep,
# HRV, and readiness metrics, then upserts records into the SQLite database
# via database.py. Designed to run on a recurring schedule (e.g., every hour).

import os
from datetime import date, timedelta

from dotenv import load_dotenv
from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

load_dotenv()


def get_client() -> Garmin:
    """Initialize and return an authenticated Garmin client."""
    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")

    if not email or not password:
        raise ValueError("GARMIN_EMAIL and GARMIN_PASSWORD must be set in .env")

    try:
        client = Garmin(email, password)
        client.login()
        return client
    except GarminConnectAuthenticationError as e:
        raise RuntimeError(f"Garmin authentication failed — check credentials in .env: {e}") from e
    except GarminConnectConnectionError as e:
        raise RuntimeError(f"Could not reach Garmin Connect — check your internet connection: {e}") from e
    except GarminConnectTooManyRequestsError as e:
        raise RuntimeError(f"Garmin rate limit hit — wait a few minutes before retrying: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Unexpected error connecting to Garmin: {e}") from e


def _date_range(days: int) -> list[str]:
    today = date.today()
    return [(today - timedelta(days=i)).isoformat() for i in range(days)]


def fetch_activities(client: Garmin, days: int = 30) -> list[dict]:
    """Fetch recent activities. Returns one dict per activity."""
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=days)).isoformat()

    try:
        raw = client.get_activities_by_date(start, end) or []
    except Exception as e:
        print(f"  [activities] Failed to fetch activity list: {e}")
        return []

    records = []
    for a in raw:
        try:
            speed = a.get("averageSpeed")  # m/s — None for non-pace sports
            pace = round(1000 / (speed * 60), 2) if speed else None  # min/km

            records.append({
                "activity_id": a.get("activityId"),
                "name": a.get("activityName"),
                "type": (a.get("activityType") or {}).get("typeKey"),
                "start_time": a.get("startTimeLocal"),
                "distance_meters": a.get("distance"),
                "duration_seconds": a.get("duration"),
                "average_hr": a.get("averageHR"),
                "max_hr": a.get("maxHR"),
                "average_pace": pace,
                "calories": a.get("calories"),
            })
        except Exception as e:
            print(f"  [activities] Skipping activity {a.get('activityId')}: {e}")

    return records


def fetch_sleep(client: Garmin, days: int = 30) -> list[dict]:
    """Fetch nightly sleep data. Returns one dict per night."""
    records = []
    for cdate in _date_range(days):
        try:
            raw = client.get_sleep_data(cdate) or {}
            dto = raw.get("dailySleepDTO") or {}
            if not dto or dto.get("calendarDate") is None:
                continue

            # sleepScores can be a nested dict or a plain int depending on device/firmware
            scores = dto.get("sleepScores")
            if isinstance(scores, dict):
                sleep_score = (scores.get("overall") or {}).get("value")
            else:
                sleep_score = scores

            records.append({
                "date": dto.get("calendarDate"),
                "sleep_start": dto.get("sleepStartTimestampLocal"),
                "sleep_end": dto.get("sleepEndTimestampLocal"),
                "total_sleep_seconds": dto.get("sleepTimeSeconds"),
                "deep_sleep_seconds": dto.get("deepSleepSeconds"),
                "light_sleep_seconds": dto.get("lightSleepSeconds"),
                "rem_sleep_seconds": dto.get("remSleepSeconds"),
                "awake_seconds": dto.get("awakeSleepSeconds"),
                "sleep_score": sleep_score,
            })
        except Exception as e:
            print(f"  [sleep] Skipping {cdate}: {e}")

    return records


def fetch_hrv(client: Garmin, days: int = 30) -> list[dict]:
    """Fetch daily HRV status. Returns one dict per day."""
    records = []
    for cdate in _date_range(days):
        try:
            raw = client.get_hrv_data(cdate) or {}
            summary = raw.get("hrvSummary") or {}
            if not summary or summary.get("lastNight") is None:
                continue

            records.append({
                "date": cdate,
                "hrv_weekly_average": summary.get("weeklyAvg"),
                "hrv_last_night": summary.get("lastNight"),
                "hrv_status": summary.get("status"),
            })
        except Exception as e:
            print(f"  [hrv] Skipping {cdate}: {e}")

    return records


def fetch_daily_stats(client: Garmin, days: int = 30) -> list[dict]:
    """Fetch daily wellness summary. Returns one dict per day."""
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=days)).isoformat()

    # Body battery covers the full range in one call
    try:
        bb_list = client.get_body_battery(start, end) or []
        bb_by_date = {entry.get("calendarDate"): entry for entry in bb_list}
    except Exception as e:
        print(f"  [daily_stats] Body battery fetch failed (continuing without it): {e}")
        bb_by_date = {}

    records = []
    for cdate in _date_range(days):
        try:
            raw = client.get_stats(cdate) or {}
            if not raw:
                continue

            bb = bb_by_date.get(cdate) or {}

            records.append({
                "date": cdate,
                "resting_hr": raw.get("restingHeartRate"),
                "body_battery_high": bb.get("charged"),
                "body_battery_low": bb.get("drained"),
                "stress_avg": raw.get("averageStressLevel"),
                "steps": raw.get("totalSteps"),
                "active_calories": raw.get("activeKilocalories"),
            })
        except Exception as e:
            print(f"  [daily_stats] Skipping {cdate}: {e}")

    return records


def main():
    print("Connecting to Garmin Connect...")
    client = get_client()
    print("Authenticated successfully.\n")

    print("Fetching activities (last 30 days)...")
    activities = fetch_activities(client)
    print(f"  -> {len(activities)} activities")
    if activities:
        print(f"  Sample record: {activities[0]}")
    print()

    print("Fetching sleep data (last 30 days)...")
    sleep = fetch_sleep(client)
    print(f"  -> {len(sleep)} nights")
    if sleep:
        print(f"  Sample record: {sleep[0]}")
    print()

    print("Fetching HRV data (last 30 days)...")
    hrv = fetch_hrv(client)
    print(f"  -> {len(hrv)} days")
    if hrv:
        print(f"  Sample record: {hrv[0]}")
    print()

    print("Fetching daily stats (last 30 days)...")
    stats = fetch_daily_stats(client)
    print(f"  -> {len(stats)} days")
    if stats:
        print(f"  Sample record: {stats[0]}")
    print()


if __name__ == "__main__":
    main()
