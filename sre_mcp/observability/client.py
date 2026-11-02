"""Small read-only HTTP client for the Monitoring and Logging REST APIs.

OBS_API_URL points at floci-gcp by default. GCP_PROJECT picks the project.
GCP_ACCESS_TOKEN is optional and only needed for real GCP.
"""

import os
from datetime import datetime, timedelta, timezone

import httpx

DEFAULT_URL = "http://localhost:4588"
DEFAULT_PROJECT = "demo-project"


class ApiError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def project() -> str:
    return os.getenv("GCP_PROJECT", DEFAULT_PROJECT)


def _base_url() -> str:
    return os.getenv("OBS_API_URL", DEFAULT_URL).rstrip("/")


def _headers() -> dict:
    token = os.getenv("GCP_ACCESS_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _request(method: str, path: str, timeout: float = 20, **kwargs) -> dict:
    try:
        resp = httpx.request(method, _base_url() + path, headers=_headers(), timeout=timeout, **kwargs)
    except httpx.HTTPError as exc:
        raise ApiError(f"Cannot reach {_base_url()}: {exc}. Is floci-gcp running?") from exc
    if resp.status_code >= 400:
        raise ApiError(f"API error {resp.status_code}: {resp.text[:200]}", resp.status_code)
    return resp.json() if resp.content else {}


def get(path: str, params: dict | None = None) -> dict:
    return _request("GET", path, params=params)


def post(path: str, body: dict, timeout: float = 20) -> dict:
    return _request("POST", path, timeout=timeout, json=body)


def patch(path: str, body: dict) -> dict:
    return _request("PATCH", path, json=body)


def is_local() -> bool:
    """True when the API is a local emulator. Writes are only allowed there for now."""
    return any(h in _base_url() for h in ("://localhost", "://127.0.0.1"))


def to_rfc3339(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def window(hours: int) -> tuple[str, str]:
    """Start and end of the last `hours` hours as RFC 3339 strings."""
    end = datetime.now(timezone.utc)
    return to_rfc3339(end - timedelta(hours=hours)), to_rfc3339(end)
