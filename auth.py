"""
auth.py — Google OAuth 2.0 helper for the Readiness dashboard.
Uses google-auth-oauthlib directly; no third-party Streamlit auth wrapper.
"""

import json
import os
import traceback
from pathlib import Path

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

import streamlit as st
from dotenv import load_dotenv
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

load_dotenv()

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

# Survives the browser redirect that wipes st.session_state
_VERIFIER_FILE = Path(__file__).parent / "data" / ".pkce_verifier.json"


def _save_verifier(state: str, verifier: str) -> None:
    _VERIFIER_FILE.parent.mkdir(exist_ok=True)
    _VERIFIER_FILE.write_text(json.dumps({"state": state, "verifier": verifier}))


def _load_verifier(state: str) -> str | None:
    """Return the stored verifier if it matches state, then delete the file."""
    try:
        data = json.loads(_VERIFIER_FILE.read_text())
        if data.get("state") == state:
            _VERIFIER_FILE.unlink(missing_ok=True)
            return data["verifier"]
    except Exception:
        pass
    return None


def _get_flow(code_verifier: str | None = None) -> Flow:
    """Build a configured OAuth Flow from env vars."""
    redirect_uri = os.getenv("REDIRECT_URI", "http://localhost:8501/")
    return Flow.from_client_config(
        {
            "web": {
                "client_id":     os.getenv("GOOGLE_CLIENT_ID", ""),
                "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
                "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
                "token_uri":     "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        },
        scopes=SCOPES,
        redirect_uri=redirect_uri,
        # Disable auto-generation so we control the verifier explicitly
        code_verifier=code_verifier,
    )


def get_authorization_url() -> str:
    """
    Generate a Google OAuth authorization URL with PKCE (S256).
    Saves code_verifier to session_state AND a file — the file survives
    the browser redirect that creates a fresh Streamlit session.
    """
    redirect_uri = os.getenv("REDIRECT_URI", "http://localhost:8501/")
    print(f"[auth] get_authorization_url() redirect_uri={redirect_uri!r}")

    # Build a flow with auto-generation enabled just for this step
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id":     os.getenv("GOOGLE_CLIENT_ID", ""),
                "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
                "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
                "token_uri":     "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        },
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )

    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="select_account",
        code_challenge_method="S256",
    )

    verifier = flow.code_verifier
    print(f"[auth] code_verifier generated (first 10): {(verifier or '')[:10]!r}")

    # Persist via both mechanisms
    st.session_state["oauth_state"]   = state
    st.session_state["code_verifier"] = verifier
    _save_verifier(state, verifier)

    return auth_url


def exchange_code_for_user_info(code: str, state: str | None = None) -> dict | None:
    """
    Exchange the authorization code Google sends back for a user info dict.
    Returns {"email", "name", "google_id", "picture"} or None on any failure.
    """
    redirect_uri = os.getenv("REDIRECT_URI", "http://localhost:8501/")
    client_id    = os.getenv("GOOGLE_CLIENT_ID", "")
    print("[auth] exchange_code_for_user_info() called")
    print(f"[auth]   code[:20]:             {code[:20]!r}")
    print(f"[auth]   state:                 {(state or '')[:20]!r}")
    print(f"[auth]   REDIRECT_URI:          {redirect_uri!r}")
    print(f"[auth]   GOOGLE_CLIENT_ID[:20]: {client_id[:20]!r}")

    # Recover verifier — session_state if the session survived, file otherwise
    verifier = st.session_state.get("code_verifier") or _load_verifier(state or "")
    print(f"[auth]   code_verifier source:  {'session_state' if st.session_state.get('code_verifier') else 'file'}")
    print(f"[auth]   code_verifier[:10]:    {(verifier or '')[:10]!r}")

    try:
        flow = _get_flow(code_verifier=verifier)
        print("[auth]   flow created — calling fetch_token()")
        flow.fetch_token(code=code)
        print("[auth]   fetch_token() succeeded — fetching userinfo")
        service = build("oauth2", "v2", credentials=flow.credentials)
        info = service.userinfo().get().execute()
        print(f"[auth]   success — email={info.get('email')!r}")
        return {
            "email":     info.get("email"),
            "name":      info.get("name"),
            "google_id": info.get("id"),
            "picture":   info.get("picture"),
        }
    except Exception:
        print("[auth]   ERROR — full traceback:")
        traceback.print_exc()
        return None
