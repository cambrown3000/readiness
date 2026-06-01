# insights.py — AI insights engine powered by the Anthropic Claude API.
# Queries the SQLite database for recent Garmin and nutrition data, constructs
# a structured prompt, and calls Claude to surface cross-variable patterns
# (e.g., sleep quality vs. protein intake, HRV vs. carb timing). Returns
# formatted insight text for display in the Streamlit dashboard.
