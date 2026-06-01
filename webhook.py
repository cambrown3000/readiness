# webhook.py — Flask webhook server for receiving Apple Health exports from Cronometer.
# Accepts POST requests containing nutrition data (calories, macros, micros),
# parses the payload, and writes records to the SQLite database via database.py.

import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request

import database

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
if not WEBHOOK_SECRET:
    log.warning("WEBHOOK_SECRET is not set in .env — requests will not be authenticated")


# ---------------------------------------------------------------------------
# Parsing — Apple Shortcuts flat format
# ---------------------------------------------------------------------------

def _normalize_record(raw: dict) -> dict | None:
    """
    Validate and normalize a single nutrition dict from Apple Shortcuts.
    Expands time-only last_meal_time values ("HH:MM") to "YYYY-MM-DD HH:MM:SS".
    Returns None if the record lacks a usable date.
    """
    date = (raw.get("date") or "").strip()[:10]
    if len(date) != 10:
        return None

    last_meal = raw.get("last_meal_time")
    if last_meal and isinstance(last_meal, str) and " " not in last_meal:
        # Time-only string — expand to full datetime
        seconds = "" if last_meal.count(":") >= 2 else ":00"
        last_meal = f"{date} {last_meal}{seconds}"

    return {
        "date": date,
        "calories": raw.get("calories"),
        "protein_g": raw.get("protein_g"),
        "carbs_g": raw.get("carbs_g"),
        "fat_g": raw.get("fat_g"),
        "fiber_g": raw.get("fiber_g"),
        "water_ml": raw.get("water_ml"),
        "last_meal_time": last_meal,
    }


def _parse_payload(payload) -> list[dict]:
    """Accept either a single record dict or a list of record dicts."""
    items = payload if isinstance(payload, list) else [payload]
    records = []
    for item in items:
        if not isinstance(item, dict):
            continue
        record = _normalize_record(item)
        if record:
            records.append(record)
    return records


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/nutrition")
def nutrition_post():
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"status": "error", "message": "Invalid or missing JSON body"}), 400

    try:
        records = _parse_payload(payload)
        database.upsert_nutrition(records)
        log.info("Wrote %d nutrition record(s)", len(records))
        return jsonify({"status": "ok", "records_written": len(records)})
    except Exception as e:
        log.exception("Failed to process nutrition payload")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/nutrition")
def nutrition_get():
    """Return the last 7 days of nutrition records — useful for debugging from iPhone."""
    try:
        return jsonify(database.get_nutrition(days=7))
    except Exception as e:
        log.exception("Failed to query nutrition")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/health")
def health_check():
    return jsonify({"status": "running"})


# ---------------------------------------------------------------------------
# Entrypoint (production)
# ---------------------------------------------------------------------------

def run():
    """Start the Flask server. Called by a scheduler or directly."""
    app.run(host="0.0.0.0", port=5001, debug=False, use_reloader=False)


# ---------------------------------------------------------------------------
# Test block
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import threading
    import time

    import requests as http

    database.init_db()

    server_thread = threading.Thread(target=run, daemon=True)
    server_thread.start()
    time.sleep(1.5)

    BASE = "http://localhost:5001"

    # --- GET /health ---
    print("GET /health")
    r = http.get(f"{BASE}/health")
    print(f"  {r.status_code}  {r.json()}\n")

    # --- POST single record ---
    single = {
        "date": "2026-05-29",
        "calories": 1920.0,
        "protein_g": 148.0,
        "carbs_g": 175.0,
        "fat_g": 68.0,
        "fiber_g": 21.0,
        "water_ml": 2200.0,
        "last_meal_time": "20:15",
    }
    print("POST /nutrition  (single record)")
    r = http.post(f"{BASE}/nutrition", json=single)
    print(f"  {r.status_code}  {r.json()}\n")

    # --- POST array of two records ---
    two_days = [
        {
            "date": "2026-05-30",
            "calories": 2100.0,
            "protein_g": 162.0,
            "carbs_g": 198.0,
            "fat_g": 72.0,
            "fiber_g": 26.0,
            "water_ml": 2600.0,
            "last_meal_time": "19:45",
        },
        {
            "date": "2026-05-31",
            "calories": 1850.0,
            "protein_g": 142.0,
            "carbs_g": 180.0,
            "fat_g": 65.0,
            "fiber_g": 22.0,
            "water_ml": 2400.0,
            "last_meal_time": "19:30",
        },
    ]
    print("POST /nutrition  (array — 2 records)")
    r = http.post(f"{BASE}/nutrition", json=two_days)
    print(f"  {r.status_code}  {r.json()}\n")

    # --- GET /nutrition to confirm all three wrote ---
    print("GET /nutrition  (last 7 days from database)")
    r = http.get(f"{BASE}/nutrition")
    for row in r.json():
        print(
            f"  {row['date']} | {row['calories']} kcal | "
            f"protein {row['protein_g']}g | carbs {row['carbs_g']}g | "
            f"fat {row['fat_g']}g | fiber {row['fiber_g']}g | "
            f"water {row['water_ml']}ml | last meal {row['last_meal_time']}"
        )

    print()
    print("Webhook test complete.")
