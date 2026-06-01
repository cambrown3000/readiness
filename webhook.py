# webhook.py — Flask webhook server for receiving Apple Health exports from Cronometer.
# Accepts POST requests containing nutrition data (calories, macros, micros),
# parses the payload, and writes records to the SQLite database via database.py.
