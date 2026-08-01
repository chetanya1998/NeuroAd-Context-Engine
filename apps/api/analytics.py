from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from typing import Any

try:
    from posthog import Posthog
except ImportError:  # Keep the API usable when analytics is intentionally not installed.
    Posthog = None  # type: ignore[assignment,misc]


LOGGER = logging.getLogger("neuroad.analytics")
SCHEMA_VERSION = 1
DISTINCT_ID_HEADER = "x-posthog-distinct-id"
SESSION_ID_HEADER = "x-posthog-session-id"
FORBIDDEN_PROPERTY_PARTS = {
    "authorization",
    "cookie",
    "description",
    "email",
    "file_name",
    "filename",
    "prompt",
    "raw_error",
    "report_content",
    "source_url",
    "thumbnail_url",
    "title",
    "token",
    "transcript",
    "url",
}


def _enabled_from_env() -> bool:
    value = os.getenv("POSTHOG_ENABLED", "").strip().lower()
    running_tests = "pytest" in sys.modules or os.getenv("PYTEST_CURRENT_TEST") is not None
    return not running_tests and value in {"1", "true", "yes", "on"} and bool(os.getenv("POSTHOG_PROJECT_TOKEN"))


def _safe_properties(properties: dict[str, Any] | None) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in (properties or {}).items():
        normalized = key.lower()
        if any(part in normalized for part in FORBIDDEN_PROPERTY_PARTS):
            continue
        if value is None or isinstance(value, (str, int, float, bool)):
            safe[key] = value
        elif isinstance(value, (list, tuple)):
            safe[key] = [item for item in value if item is None or isinstance(item, (str, int, float, bool))]
    return safe


def _new_client() -> Any | None:
    if not _enabled_from_env() or Posthog is None:
        return None
    try:
        client = Posthog(
            os.environ["POSTHOG_PROJECT_TOKEN"],
            host=os.getenv("POSTHOG_HOST", "https://us.i.posthog.com"),
            debug=os.getenv("POSTHOG_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"},
        )
        client.disabled = os.getenv("PYTEST_CURRENT_TEST") is not None
        return client
    except Exception:
        LOGGER.exception("PostHog client initialization failed.")
        return None


_client = _new_client()


@dataclass(frozen=True)
class AnalyticsContext:
    distinct_id: str | None = None
    session_id: str | None = None

    @classmethod
    def from_headers(cls, headers: Any) -> "AnalyticsContext":
        distinct_id = (headers.get(DISTINCT_ID_HEADER) or "").strip() or None
        session_id = (headers.get(SESSION_ID_HEADER) or "").strip() or None
        return cls(distinct_id=distinct_id, session_id=session_id)


def capture_event(
    event: str,
    context: AnalyticsContext,
    properties: dict[str, Any] | None = None,
    *,
    insert_id: str | None = None,
) -> bool:
    """Queue a privacy-filtered event without affecting the product workflow."""
    if _client is None or not context.distinct_id:
        return False

    event_properties = {
        "schema_version": SCHEMA_VERSION,
        "environment": os.getenv("NEUROAD_ENVIRONMENT", "production"),
        "$process_person_profile": False,
        **_safe_properties(properties),
    }
    if context.session_id:
        event_properties["$session_id"] = context.session_id
    if insert_id:
        event_properties["$insert_id"] = insert_id

    try:
        _client.capture(event, distinct_id=context.distinct_id, properties=event_properties)
        return True
    except Exception:
        LOGGER.exception("PostHog event capture failed: event=%s", event)
        return False


def shutdown_analytics() -> None:
    if _client is None:
        return
    try:
        _client.shutdown()
    except Exception:
        LOGGER.exception("PostHog shutdown failed.")
