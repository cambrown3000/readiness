# Readiness

A personal health dashboard that combines Garmin fitness data with nutrition data from Cronometer (synced via Apple Health) to surface cross-variable patterns and AI-generated insights.

## Tech Stack

| Layer | Tool |
|---|---|
| Frontend | Streamlit |
| AI insights | Anthropic Claude API |
| Garmin data | `garminconnect` Python library + APScheduler |
| Nutrition data | Apple Health export → Cronometer → Flask webhook |
| Database | SQLite |
| Auth | Google OAuth |
| Deployment | Streamlit Community Cloud |

## Project Structure

```
readiness/
├── app.py           # Streamlit dashboard + Google OAuth
├── webhook.py       # Flask server for Apple Health / Cronometer data
├── garmin_sync.py   # Scheduled Garmin Connect sync
├── database.py      # SQLite schema and data access layer
├── insights.py      # Claude-powered pattern analysis
├── requirements.txt
├── .env.example     # Template for required credentials
└── data/            # Local SQLite database (git-ignored)
```

## Credentials

All secrets (Garmin login, Anthropic API key, Google OAuth credentials) are stored in a `.env` file that is listed in `.gitignore` and **never committed to GitHub**. Copy `.env.example` to `.env` and fill in your values before running locally.

```bash
cp .env.example .env
```

## Running Locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```
