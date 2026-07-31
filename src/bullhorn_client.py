"""Bullhorn REST API client — read-only, used for exactly one thing: fetching
CV file bytes for the "Download CV" candidate-card feature.

Python port of Mind's OAuth2 3-step flow
(mind/apps/web/src/lib/clients/bullhorn-client.ts) — authorize -> token ->
login, session cached in-process and refreshed on 401/expiry. No write paths
implemented, mirroring this repo's other Bullhorn/Mothership access being
read-only by construction.

Known risk (per Mind's own CLAUDE.md): Bullhorn's OAuth authorize step fails
silently with "no code in redirect URL" if the calling IP isn't on Bullhorn's
allowlist. Mind's production IP (Railway) is allowlisted; a local dev machine
calling this may not be — if fetch_file raises that specific error, that's
almost certainly why, not a credentials problem.
"""
from __future__ import annotations

import base64
import os
import re
import threading
import time
from urllib.parse import unquote

import httpx
from dotenv import load_dotenv

load_dotenv()

_REST_LOGIN_URL = "https://rest.bullhornstaffing.com/rest-services/login"

_session: dict | None = None
_session_lock = threading.Lock()


def _auth_url() -> str:
    return os.environ.get("BULLHORN_AUTH_URL", "https://auth-emea.bullhornstaffing.com").rstrip("/")


def _get_auth_code() -> str:
    params = {
        "client_id": os.environ["BULLHORN_CLIENT_ID"],
        "response_type": "code",
        "username": os.environ["BULLHORN_API_USERNAME"],
        "password": os.environ["BULLHORN_API_PASSWORD"],
        "action": "Login",
    }
    resp = httpx.get(f"{_auth_url()}/oauth/authorize", params=params, follow_redirects=False, timeout=30)
    location = resp.headers.get("location")
    if not location:
        raise RuntimeError("Bullhorn OAuth: no redirect from authorize endpoint")
    match = re.search(r"code=([^&]+)", location)
    if not match:
        raise RuntimeError(
            f"Bullhorn OAuth: no code in redirect URL ({location}) — likely an IP-allowlist "
            "rejection (see module docstring), not a bad credential."
        )
    # The redirect's query string is already percent-encoded (the code often
    # contains a literal ":", encoded as %3A). Decode it here so the *next*
    # request's httpx params= (which re-encodes dict values) produces the
    # same single-encoded form Bullhorn issued, not a double-encoded one —
    # Mind's JS avoids this by building a raw URL string instead of an
    # encoded params object, which never re-encodes an already-encoded value.
    return unquote(match.group(1))


def _get_access_token(auth_code: str) -> str:
    params = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "client_id": os.environ["BULLHORN_CLIENT_ID"],
        "client_secret": os.environ["BULLHORN_CLIENT_SECRET"],
    }
    resp = httpx.post(f"{_auth_url()}/oauth/token", params=params, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"Bullhorn OAuth token failed: {resp.status_code}")
    return resp.json()["access_token"]


def _login(access_token: str) -> dict:
    params = {"version": "*", "access_token": access_token}
    resp = httpx.post(_REST_LOGIN_URL, params=params, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"Bullhorn REST login failed: {resp.status_code}")
    data = resp.json()
    return {
        "bh_rest_token": data["BhRestToken"],
        "rest_url": data["restUrl"],
        "expires_at": time.time() + 8 * 60,  # 8 min — buffer before Bullhorn's 10 min expiry
    }


def _authenticate() -> dict:
    auth_code = _get_auth_code()
    access_token = _get_access_token(auth_code)
    return _login(access_token)


def _get_session() -> dict:
    global _session
    with _session_lock:
        if _session and time.time() < _session["expires_at"]:
            return _session
        _session = _authenticate()
        return _session


def _invalidate_session() -> None:
    global _session
    with _session_lock:
        _session = None


def fetch_file(entity_type: str, entity_id: int, file_id: int) -> tuple[bytes, str]:
    """Fetch a binary file attachment from Bullhorn.

    Returns (content_bytes, content_type). Retries once with a fresh session
    on 401, matching Mind's bullhornFileFetch.

    Confirmed live (differs from Mind's own docstring assumption of a raw
    application/octet-stream body): this tenant's /file/ endpoint returns
    JSON — {"File": {"contentType": ..., "fileContent": "<base64>"}} — not
    raw bytes. Unwrapped here; falls back to treating the body as raw bytes
    if it isn't JSON, in case a different tenant/file type behaves as Mind's
    comment describes.
    """
    session = _get_session()
    url = f"{session['rest_url']}file/{entity_type}/{entity_id}/{file_id}"
    resp = httpx.get(url, params={"BhRestToken": session["bh_rest_token"]}, timeout=30)

    if resp.status_code == 401:
        _invalidate_session()
        session = _get_session()
        resp = httpx.get(url, params={"BhRestToken": session["bh_rest_token"]}, timeout=30)

    if resp.status_code >= 400:
        raise RuntimeError(
            f"Bullhorn file fetch error ({resp.status_code}) for "
            f"{entity_type}/{entity_id}/{file_id}: {resp.text[:200]}"
        )

    content_type = resp.headers.get("content-type", "application/octet-stream")
    if content_type.split(";")[0].strip() == "application/json":
        data = resp.json()
        file_obj = data.get("File", data)
        b64 = file_obj.get("fileContent")
        if b64 is None:
            raise RuntimeError(
                f"Bullhorn file fetch: JSON response had no fileContent field "
                f"(keys: {list(file_obj.keys())})"
            )
        return base64.b64decode(b64), file_obj.get("contentType", "application/octet-stream")

    return resp.content, content_type
