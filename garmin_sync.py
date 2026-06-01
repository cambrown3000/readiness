# garmin_sync.py — Scheduled Garmin data sync using APScheduler.
# Authenticates with the Garmin Connect API, fetches daily activity, sleep,
# HRV, and readiness metrics, then upserts records into the SQLite database
# via database.py. Designed to run on a recurring schedule (e.g., every hour).
