# database.py — SQLite database layer for the Readiness app.
# Defines the schema (tables for garmin_metrics, nutrition, insights),
# handles connection management, and exposes read/write helper functions
# used by garmin_sync.py, webhook.py, and insights.py.
