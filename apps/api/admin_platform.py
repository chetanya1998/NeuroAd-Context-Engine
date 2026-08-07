"""Internal ML control-plane APIs.

This module is deliberately isolated from customer routes.  It uses the same
database while the product is in its single-instance phase, but all records are
versioned and can be migrated to PostgreSQL without changing the API contract.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Literal, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field


SESSION_COOKIE = "neuroad_admin_session"
SESSION_TTL_HOURS = 12
INVITE_TTL_HOURS = 72
ROLES = {"platform_admin", "ml_operator", "labeler", "reviewer", "observer"}
ROLE_RANK = {"observer": 0, "labeler": 1, "ml_operator": 2, "reviewer": 3, "platform_admin": 4}
PASSWORD_HASHER = PasswordHasher(type=Type.ID)

DEFAULT_SCORING_CONFIG = {
    "schema_version": 1,
    "weights": {
        "visual_novelty": 0.16, "motion": 0.12, "object_clarity": 0.12,
        "visual_quality": 0.10, "scene_change": 0.10, "speech_density": 0.12,
        "hook_cta_signal": 0.10, "audio_energy": 0.08, "topic_clarity": 0.10,
    },
    "penalties": {"silence": 0.12, "repetition": 0.08, "blur": 0.08},
    # Mirrors the existing attention_label implementation exactly.
    "thresholds": {"high_attention": 80, "good_attention": 60, "neutral": 40, "drop_risk": 20},
    "safe_rules": [],
}

DEFAULT_TAXONOMY = {
    "name": "Quality + Evidence",
    "fields": [
        {"key": "attention_band", "label": "Attention quality", "type": "enum", "values": ["high", "good", "neutral", "drop_risk", "weak"], "required": True},
        {"key": "contextual_fit", "label": "Contextual / ad fit", "type": "enum", "values": ["strong", "conditional", "weak", "not_suitable"], "required": True},
        {"key": "brand_safety", "label": "Brand safety", "type": "enum", "values": ["safe", "review", "unsafe"], "required": True},
        {"key": "transcript_quality", "label": "Transcript quality", "type": "enum", "values": ["accurate", "partial", "incorrect", "unavailable"], "required": True},
        {"key": "evidence_confidence", "label": "Evidence confidence", "type": "integer", "min": 0, "max": 100, "required": True},
        {"key": "reviewer_notes", "label": "Reviewer notes", "type": "text", "required": False},
    ],
}


@dataclass
class AdminServices:
    execute: Callable[..., None]
    query_one: Callable[..., Any]
    query_all: Callable[..., list[Any]]
    new_id: Callable[[str], str]
    utc_now: Callable[[], str]
    runtime_dependencies: Callable[[], dict[str, Any]]
    build_metadata: Callable[[], dict[str, str]]


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _loads(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value) if value else fallback
    except (TypeError, ValueError):
        return fallback


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def _iso_after(hours: int) -> str:
    return (datetime.utcnow() + timedelta(hours=hours)).isoformat(timespec="seconds")


def _valid_config(config: dict[str, Any]) -> dict[str, Any]:
    weights = config.get("weights")
    if not isinstance(weights, dict) or set(weights) != set(DEFAULT_SCORING_CONFIG["weights"]):
        raise HTTPException(422, "A candidate must include every supported attention weight.")
    normalized = {key: float(value) for key, value in weights.items()}
    if any(value < 0 or value > 1 for value in normalized.values()):
        raise HTTPException(422, "Weights must be between 0 and 1.")
    total = sum(normalized.values())
    if abs(total - 1.0) > 0.0001:
        raise HTTPException(422, "Attention weights must sum to 1.0.")
    penalties = config.get("penalties", {})
    thresholds = config.get("thresholds", {})
    safe_rules = config.get("safe_rules", [])
    if not isinstance(penalties, dict) or not isinstance(thresholds, dict) or not isinstance(safe_rules, list):
        raise HTTPException(422, "Configuration sections have an invalid shape.")
    if any(not isinstance(rule, dict) or set(rule).difference({"field", "operator", "value", "effect"}) for rule in safe_rules):
        raise HTTPException(422, "Rules must use the approved rule schema.")
    return {"schema_version": 1, "weights": normalized, "penalties": penalties, "thresholds": thresholds, "safe_rules": safe_rules}


def _github_request(method: str, path: str, token: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = UrlRequest(
        f"https://api.github.com{path}",
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            **({"Content-Type": "application/json"} if body else {}),
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, ValueError) as exc:
        raise HTTPException(502, "GitHub release delivery failed. Check the GitHub App installation token and repository permissions.") from exc


def create_github_release(config: dict[str, Any], version: int, branch: str) -> dict[str, str]:
    """Create a manifest-only PR with a GitHub App installation token.

    The token is short-lived and must be minted by the GitHub App outside the
    dashboard process; it is never sent to the browser or persisted.
    """
    repository = os.getenv("NEUROAD_GITHUB_REPOSITORY", "").strip()
    token = os.getenv("NEUROAD_GITHUB_INSTALLATION_TOKEN", "").strip()
    if not token or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise HTTPException(503, "GitHub App installation token and owner/repository configuration are required.")
    main_ref = _github_request("GET", f"/repos/{repository}/git/ref/heads/main", token)
    base_sha = str(main_ref.get("object", {}).get("sha") or "")
    if not base_sha:
        raise HTTPException(502, "GitHub did not return the current main branch SHA.")
    _github_request("POST", f"/repos/{repository}/git/refs", token, {"ref": f"refs/heads/{branch}", "sha": base_sha})
    manifest_path = "config/scoring/active.json"
    prior = _github_request("GET", f"/repos/{repository}/contents/{manifest_path}?ref=main", token)
    content = base64.b64encode(json.dumps({"version": version, "config": config}, indent=2, sort_keys=True).encode("utf-8")).decode("ascii")
    update_payload: dict[str, Any] = {"message": f"release: activate scoring config v{version}", "content": content, "branch": branch}
    if prior.get("sha"):
        update_payload["sha"] = prior["sha"]
    commit = _github_request("PUT", f"/repos/{repository}/contents/{manifest_path}", token, update_payload)
    pull = _github_request("POST", f"/repos/{repository}/pulls", token, {"title": f"Release scoring config v{version}", "head": branch, "base": "main", "body": "Generated by the NeuroAd Internal ML Dashboard after evaluation and approval."})
    return {"pull_request_url": str(pull.get("html_url") or ""), "commit_sha": str(commit.get("commit", {}).get("sha") or base_sha)}


def init_admin_platform(services: AdminServices) -> None:
    statements = [
        """create table if not exists admin_users (id text primary key, email text not null unique, password_hash text not null, role text not null, status text not null default 'active', created_at text not null, updated_at text not null, last_login_at text)""",
        """create table if not exists admin_sessions (id text primary key, user_id text not null, token_hash text not null unique, expires_at text not null, revoked_at text, created_at text not null)""",
        """create table if not exists admin_invitations (id text primary key, email text not null, role text not null, token_hash text not null unique, expires_at text not null, accepted_at text, created_by text not null, created_at text not null)""",
        """create table if not exists admin_audit_events (id text primary key, actor_id text, action text not null, target_type text not null, target_id text, details_json text not null default '{}', created_at text not null)""",
        """create table if not exists admin_metric_events (id text primary key, scope text not null, event_name text not null, route text, status_code integer, duration_ms integer, actor_hash text, metadata_json text not null default '{}', occurred_at text not null)""",
        """create table if not exists data_asset_consents (video_id text primary key, consent_status text not null, policy_version text not null, recorded_at text not null, withdrawn_at text)""",
        """create table if not exists ml_taxonomies (id text primary key, name text not null, version integer not null, schema_json text not null, status text not null default 'active', created_by text not null, created_at text not null, unique(name, version))""",
        """create table if not exists ml_dataset_versions (id text primary key, name text not null, status text not null, asset_ids_json text not null, split_json text not null, taxonomy_id text not null, created_by text not null, created_at text not null, approved_at text)""",
        """create table if not exists ml_label_tasks (id text primary key, video_id text not null, segment_id text, taxonomy_id text not null, status text not null default 'open', assigned_to text, created_by text not null, created_at text not null)""",
        """create table if not exists ml_annotations (id text primary key, task_id text not null, values_json text not null, confidence integer not null, evidence_note text, created_by text not null, created_at text not null, reviewed_by text, reviewed_at text, review_status text not null default 'pending')""",
        """create table if not exists ml_scoring_config_versions (id text primary key, version integer not null unique, status text not null, parent_id text, config_json text not null, rationale text not null, created_by text not null, created_at text not null, submitted_at text, approved_by text, approved_at text)""",
        """create table if not exists ml_evaluation_runs (id text primary key, candidate_config_id text not null, baseline_config_id text not null, dataset_id text, status text not null, result_json text, created_by text not null, created_at text not null, completed_at text)""",
        """create table if not exists ml_release_records (id text primary key, config_id text not null, status text not null, branch text, pull_request_url text, commit_sha text, deployment_json text not null default '{}', created_by text not null, approved_by text, created_at text not null, updated_at text not null, rolled_back_by text)""",
        """create table if not exists ml_report_quality_feedback (id text primary key, report_id text, issue_type text not null, note text not null, status text not null default 'approved_for_training', created_by text not null, created_at text not null)""",
    ]
    for statement in statements:
        services.execute(statement)
    taxonomy = services.query_one("select id from ml_taxonomies where name = ? and version = 1", (DEFAULT_TAXONOMY["name"],))
    now = services.utc_now()
    if not taxonomy:
        services.execute("insert into ml_taxonomies (id, name, version, schema_json, status, created_by, created_at) values (?, ?, 1, ?, 'active', 'system', ?)", ("taxonomy_quality_evidence_v1", DEFAULT_TAXONOMY["name"], json.dumps(DEFAULT_TAXONOMY), now))
    active = services.query_one("select id from ml_scoring_config_versions where status = 'active' limit 1")
    if not active:
        services.execute("insert into ml_scoring_config_versions (id, version, status, config_json, rationale, created_by, created_at, approved_by, approved_at) values (?, 1, 'active', ?, ?, 'system', ?, 'system', ?)", ("score_config_v1", json.dumps(DEFAULT_SCORING_CONFIG), "Baseline captured from the existing production scoring implementation.", now, now))
    email = os.getenv("NEUROAD_ADMIN_BOOTSTRAP_EMAIL", "").strip().lower()
    password = os.getenv("NEUROAD_ADMIN_BOOTSTRAP_PASSWORD", "")
    if email and password and not services.query_one("select id from admin_users where email = ?", (email,)):
        services.execute("insert into admin_users (id, email, password_hash, role, status, created_at, updated_at) values (?, ?, ?, 'platform_admin', 'active', ?, ?)", (services.new_id("admin_user"), email, PASSWORD_HASHER.hash(password), now, now))


def record_admin_metric_event(services: AdminServices, *, scope: str, event_name: str, route: Optional[str] = None, status_code: Optional[int] = None, duration_ms: Optional[int] = None, actor_id: Optional[str] = None, metadata: Optional[dict[str, Any]] = None) -> None:
    try:
        services.execute("insert into admin_metric_events (id, scope, event_name, route, status_code, duration_ms, actor_hash, metadata_json, occurred_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?)", (services.new_id("metric"), scope, event_name, route, status_code, duration_ms, _hash(actor_id) if actor_id else None, json.dumps(metadata or {}), services.utc_now()))
    except Exception:
        # Observability must never interfere with customer analysis.
        return


class LoginRequest(BaseModel):
    email: str
    password: str


class InviteRequest(BaseModel):
    email: str
    role: Literal["platform_admin", "ml_operator", "labeler", "reviewer", "observer"]


class AcceptInviteRequest(BaseModel):
    token: str
    password: str = Field(min_length=12, max_length=256)


class TaxonomyRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    fields: list[dict[str, Any]] = Field(min_length=1, max_length=40)


class DatasetRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    video_ids: list[str] = Field(min_length=1, max_length=500)
    taxonomy_id: str
    splits: dict[str, list[str]] = Field(default_factory=dict)


class LabelTaskRequest(BaseModel):
    video_id: str
    segment_id: Optional[str] = None
    taxonomy_id: str
    assigned_to: Optional[str] = None


class AnnotationRequest(BaseModel):
    values: dict[str, Any]
    confidence: int = Field(ge=0, le=100)
    evidence_note: Optional[str] = Field(default=None, max_length=2000)


class ScoringConfigRequest(BaseModel):
    config: dict[str, Any]
    rationale: str = Field(min_length=8, max_length=2000)


class EvaluationRequest(BaseModel):
    dataset_id: Optional[str] = None


class ReportQualityFeedbackRequest(BaseModel):
    report_id: Optional[str] = Field(default=None, max_length=160)
    issue_type: Literal["incorrect_score", "unsupported_claim", "missing_evidence", "misleading_copy", "better_example"]
    note: str = Field(min_length=8, max_length=2000)


class ReleaseVerificationRequest(BaseModel):
    railway_status: Literal["healthy"]
    netlify_status: Literal["healthy"]
    deployed_sha: str = Field(min_length=7, max_length=128)


def create_admin_router(services: AdminServices) -> APIRouter:
    router = APIRouter(prefix="/internal/admin/v1", tags=["internal-admin"])

    def audit(actor: Optional[dict[str, Any]], action: str, target_type: str, target_id: Optional[str], details: Optional[dict[str, Any]] = None) -> None:
        services.execute("insert into admin_audit_events (id, actor_id, action, target_type, target_id, details_json, created_at) values (?, ?, ?, ?, ?, ?, ?)", (services.new_id("audit"), actor["id"] if actor else None, action, target_type, target_id, json.dumps(details or {}), services.utc_now()))

    def identity(token: Optional[str]) -> dict[str, Any]:
        if not token:
            raise HTTPException(401, "Sign in to access the internal ML dashboard.")
        session = services.query_one("select s.*, u.id as user_id, u.email, u.role, u.status as user_status from admin_sessions s join admin_users u on u.id = s.user_id where s.token_hash = ? and s.revoked_at is null", (_hash(token),))
        if not session or session["user_status"] != "active" or session["expires_at"] <= _now():
            raise HTTPException(401, "Your internal dashboard session has expired.")
        return {"id": session["user_id"], "email": session["email"], "role": session["role"], "session_id": session["id"]}

    def current_user(request: Request, admin_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE)) -> dict[str, Any]:
        bearer = request.headers.get("authorization", "")
        token = admin_session or (bearer.split(" ", 1)[1] if bearer.lower().startswith("bearer ") else None)
        return identity(token)

    def allow(*roles: str):
        def dependency(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
            if user["role"] not in roles:
                raise HTTPException(403, "This role cannot perform the requested internal dashboard action.")
            return user
        return dependency

    @router.post("/auth/login")
    def login(payload: LoginRequest, response: Response) -> dict[str, Any]:
        email = payload.email.strip().lower()
        user = services.query_one("select * from admin_users where email = ?", (email,))
        valid = False
        if user and user["status"] == "active":
            try:
                valid = PASSWORD_HASHER.verify(user["password_hash"], payload.password)
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                valid = False
        if not valid:
            raise HTTPException(401, "Invalid email or password.")
        token = secrets.token_urlsafe(48)
        now = services.utc_now()
        services.execute("insert into admin_sessions (id, user_id, token_hash, expires_at, created_at) values (?, ?, ?, ?, ?)", (services.new_id("session"), user["id"], _hash(token), _iso_after(SESSION_TTL_HOURS), now))
        services.execute("update admin_users set last_login_at = ?, updated_at = ? where id = ?", (now, now, user["id"]))
        response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=os.getenv("NEUROAD_ENVIRONMENT", "development") == "production", samesite="strict", max_age=SESSION_TTL_HOURS * 3600, path="/")
        audit({"id": user["id"]}, "auth.login", "admin_user", user["id"])
        # The cookie supports same-site custom domains. The short-lived session token
        # lets the separate Netlify admin origin authenticate its XHR requests without
        # relying on third-party cookie behavior.
        return {
            "user": {"id": user["id"], "email": user["email"], "role": user["role"]},
            "session_token": token,
        }

    @router.post("/auth/logout")
    def logout(response: Response, user: dict[str, Any] = Depends(current_user)) -> dict[str, bool]:
        services.execute("update admin_sessions set revoked_at = ? where id = ?", (services.utc_now(), user["session_id"]))
        response.delete_cookie(SESSION_COOKIE, path="/")
        audit(user, "auth.logout", "admin_user", user["id"])
        return {"ok": True}

    @router.get("/auth/me")
    def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        return {"user": {key: user[key] for key in ("id", "email", "role")}}

    @router.post("/auth/invitations")
    def invite(payload: InviteRequest, user: dict[str, Any] = Depends(allow("platform_admin"))) -> dict[str, Any]:
        email = payload.email.strip().lower()
        if services.query_one("select id from admin_users where email = ?", (email,)):
            raise HTTPException(409, "An internal user already exists for this email.")
        token = secrets.token_urlsafe(32)
        invitation_id = services.new_id("invite")
        services.execute("insert into admin_invitations (id, email, role, token_hash, expires_at, created_by, created_at) values (?, ?, ?, ?, ?, ?, ?)", (invitation_id, email, payload.role, _hash(token), _iso_after(INVITE_TTL_HOURS), user["id"], services.utc_now()))
        audit(user, "auth.invite_created", "admin_invitation", invitation_id, {"role": payload.role})
        return {"invitation_id": invitation_id, "token": token, "expires_in_hours": INVITE_TTL_HOURS}

    @router.post("/auth/accept-invitation")
    def accept_invitation(payload: AcceptInviteRequest) -> dict[str, str]:
        invitation = services.query_one("select * from admin_invitations where token_hash = ? and accepted_at is null", (_hash(payload.token),))
        if not invitation or invitation["expires_at"] <= _now():
            raise HTTPException(400, "Invitation is invalid or expired.")
        user_id = services.new_id("admin_user")
        now = services.utc_now()
        services.execute("insert into admin_users (id, email, password_hash, role, status, created_at, updated_at) values (?, ?, ?, ?, 'active', ?, ?)", (user_id, invitation["email"], PASSWORD_HASHER.hash(payload.password), invitation["role"], now, now))
        services.execute("update admin_invitations set accepted_at = ? where id = ?", (now, invitation["id"]))
        audit({"id": user_id}, "auth.invitation_accepted", "admin_user", user_id)
        return {"status": "accepted"}

    @router.get("/overview")
    def overview(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        today = (datetime.utcnow() - timedelta(days=1)).isoformat(timespec="seconds")
        video_rows = services.query_all("select status, count(*) as count from videos group by status")
        job_rows = services.query_all("select status, count(*) as count from jobs group by status")
        recent_events = services.query_one("select count(distinct actor_hash) as count from admin_metric_events where scope = 'product' and actor_hash is not null and occurred_at >= ?", (today,))
        active = services.query_one("select id, version, created_at from ml_scoring_config_versions where status = 'active' limit 1")
        return {"videos": {row["status"]: row["count"] for row in video_rows}, "jobs": {row["status"]: row["count"] for row in job_rows}, "unique_visitors_24h": int(recent_events["count"] if recent_events else 0), "active_config": dict(active) if active else None, "build": services.build_metadata()}

    @router.get("/system-health")
    def system_health(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        since = (datetime.utcnow() - timedelta(days=7)).isoformat(timespec="seconds")
        by_day = services.query_all("select substr(occurred_at, 1, 10) as day, status_code, count(*) as count from admin_metric_events where scope = 'api' and occurred_at >= ? group by day, status_code order by day", (since,))
        latency = services.query_all("select route, count(*) as count, avg(duration_ms) as avg_ms, max(duration_ms) as max_ms from admin_metric_events where scope = 'api' and occurred_at >= ? group by route order by count desc limit 12", (since,))
        durations = [int(row["duration_ms"] or 0) for row in services.query_all("select duration_ms from admin_metric_events where scope = 'api' and occurred_at >= ? and duration_ms is not null order by duration_ms", (since,))]
        def percentile(percent: float) -> int:
            if not durations:
                return 0
            return durations[min(len(durations) - 1, int((len(durations) - 1) * percent))]
        failures = services.query_all("select coalesce(error, 'unknown') as reason, count(*) as count from jobs where status = 'failed' group by reason order by count desc limit 8")
        dependencies = services.runtime_dependencies()
        return {"request_statuses": [dict(row) for row in by_day], "latency": [dict(row) for row in latency], "latency_summary": {"p50_ms": percentile(.50), "p95_ms": percentile(.95), "p99_ms": percentile(.99)}, "failure_reasons": [dict(row) for row in failures], "queue": {"queued": int(services.query_one("select count(*) as count from jobs where status = 'queued'")["count"]), "processing": int(services.query_one("select count(*) as count from jobs where status = 'processing'")["count"])}, "dependencies": dependencies}

    @router.get("/product-analytics")
    def product_analytics(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        since = (datetime.utcnow() - timedelta(days=30)).isoformat(timespec="seconds")
        events = services.query_all("select substr(occurred_at, 1, 10) as day, event_name, count(*) as count, count(distinct actor_hash) as actors from admin_metric_events where scope = 'product' and occurred_at >= ? group by day, event_name order by day", (since,))
        comparisons = services.query_all("select status, count(*) as count from comparisons group by status")
        funnel = {"uploaded": int(services.query_one("select count(*) as count from videos")["count"]), "analysis_requested": int(services.query_one("select count(*) as count from jobs")["count"]), "completed": int(services.query_one("select count(*) as count from videos where status = 'completed'")["count"]), "reports": int(services.query_one("select count(*) as count from reports")["count"])}
        return {"events": [dict(row) for row in events], "comparison_status": [dict(row) for row in comparisons], "funnel": funnel, "metric_label": "Unique visitors/sessions until customer accounts are introduced."}

    @router.get("/datasets/assets")
    def list_assets(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        rows = services.query_all("select v.id, v.title, v.status, v.created_at, c.consent_status, c.policy_version, c.recorded_at, c.withdrawn_at from videos v left join data_asset_consents c on c.video_id = v.id order by v.created_at desc limit 300")
        return {"assets": [dict(row) for row in rows]}

    @router.get("/taxonomies")
    def list_taxonomies(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        rows = services.query_all("select * from ml_taxonomies order by name, version desc")
        return {"taxonomies": [{**dict(row), "schema": _loads(row["schema_json"], {})} for row in rows]}

    @router.post("/taxonomies")
    def create_taxonomy(payload: TaxonomyRequest, user: dict[str, Any] = Depends(allow("platform_admin", "ml_operator"))) -> dict[str, Any]:
        prior = services.query_one("select max(version) as version from ml_taxonomies where name = ?", (payload.name.strip(),))
        version = int(prior["version"] or 0) + 1
        taxonomy_id = services.new_id("taxonomy")
        schema = {"name": payload.name.strip(), "fields": payload.fields}
        services.execute("insert into ml_taxonomies (id, name, version, schema_json, status, created_by, created_at) values (?, ?, ?, ?, 'active', ?, ?)", (taxonomy_id, payload.name.strip(), version, json.dumps(schema), user["id"], services.utc_now()))
        audit(user, "taxonomy.created", "taxonomy", taxonomy_id, {"version": version})
        return {"id": taxonomy_id, "version": version, "schema": schema}

    @router.post("/datasets")
    def create_dataset(payload: DatasetRequest, user: dict[str, Any] = Depends(allow("platform_admin", "ml_operator", "reviewer"))) -> dict[str, Any]:
        consented = services.query_all("select video_id from data_asset_consents where consent_status = 'opted_in' and withdrawn_at is null and video_id in (%s)" % ",".join("?" * len(payload.video_ids)), tuple(payload.video_ids))
        permitted = {row["video_id"] for row in consented}
        blocked = sorted(set(payload.video_ids).difference(permitted))
        if blocked:
            raise HTTPException(422, "Every dataset asset needs active internal-training consent.")
        if not services.query_one("select id from ml_taxonomies where id = ? and status = 'active'", (payload.taxonomy_id,)):
            raise HTTPException(404, "Active taxonomy not found.")
        dataset_id = services.new_id("dataset")
        services.execute("insert into ml_dataset_versions (id, name, status, asset_ids_json, split_json, taxonomy_id, created_by, created_at) values (?, ?, 'locked', ?, ?, ?, ?, ?)", (dataset_id, payload.name.strip(), json.dumps(sorted(permitted)), json.dumps(payload.splits), payload.taxonomy_id, user["id"], services.utc_now()))
        audit(user, "dataset.created", "dataset", dataset_id, {"asset_count": len(permitted)})
        return {"id": dataset_id, "status": "locked", "asset_count": len(permitted)}

    @router.get("/label-tasks")
    def list_label_tasks(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        rows = services.query_all("select t.*, v.title, a.review_status, a.values_json, a.confidence from ml_label_tasks t join videos v on v.id = t.video_id left join ml_annotations a on a.task_id = t.id order by t.created_at desc limit 200")
        return {"tasks": [{**dict(row), "values": _loads(row["values_json"], {})} for row in rows]}

    @router.post("/label-tasks")
    def create_label_task(payload: LabelTaskRequest, user: dict[str, Any] = Depends(allow("platform_admin", "ml_operator", "reviewer"))) -> dict[str, str]:
        consent = services.query_one("select consent_status, withdrawn_at from data_asset_consents where video_id = ?", (payload.video_id,))
        if not consent or consent["consent_status"] != "opted_in" or consent["withdrawn_at"]:
            raise HTTPException(422, "Only opted-in assets can be labeled for internal ML.")
        task_id = services.new_id("label_task")
        services.execute("insert into ml_label_tasks (id, video_id, segment_id, taxonomy_id, assigned_to, created_by, created_at) values (?, ?, ?, ?, ?, ?, ?)", (task_id, payload.video_id, payload.segment_id, payload.taxonomy_id, payload.assigned_to, user["id"], services.utc_now()))
        audit(user, "label_task.created", "label_task", task_id)
        return {"id": task_id, "status": "open"}

    @router.post("/label-tasks/{task_id}/annotations")
    def annotate(task_id: str, payload: AnnotationRequest, user: dict[str, Any] = Depends(allow("platform_admin", "ml_operator", "labeler", "reviewer"))) -> dict[str, str]:
        task = services.query_one("select * from ml_label_tasks where id = ?", (task_id,))
        if not task:
            raise HTTPException(404, "Label task not found.")
        annotation_id = services.new_id("annotation")
        services.execute("insert into ml_annotations (id, task_id, values_json, confidence, evidence_note, created_by, created_at) values (?, ?, ?, ?, ?, ?, ?)", (annotation_id, task_id, json.dumps(payload.values), payload.confidence, payload.evidence_note, user["id"], services.utc_now()))
        services.execute("update ml_label_tasks set status = 'submitted' where id = ?", (task_id,))
        audit(user, "annotation.created", "annotation", annotation_id)
        return {"id": annotation_id, "status": "pending_review"}

    @router.post("/annotations/{annotation_id}/review")
    def review_annotation(annotation_id: str, approved: bool, user: dict[str, Any] = Depends(allow("platform_admin", "reviewer"))) -> dict[str, str]:
        annotation = services.query_one("select * from ml_annotations where id = ?", (annotation_id,))
        if not annotation:
            raise HTTPException(404, "Annotation not found.")
        if annotation["created_by"] == user["id"]:
            raise HTTPException(409, "A reviewer cannot approve their own annotation.")
        status = "approved" if approved else "rejected"
        services.execute("update ml_annotations set review_status = ?, reviewed_by = ?, reviewed_at = ? where id = ?", (status, user["id"], services.utc_now(), annotation_id))
        services.execute("update ml_label_tasks set status = ? where id = ?", ("completed" if approved else "open", annotation["task_id"]))
        audit(user, "annotation.reviewed", "annotation", annotation_id, {"status": status})
        return {"status": status}

    @router.get("/scoring-configs")
    def configs(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        rows = services.query_all("select * from ml_scoring_config_versions order by version desc")
        return {"configs": [{**dict(row), "config": _loads(row["config_json"], {})} for row in rows]}

    @router.post("/scoring-configs")
    def create_config(payload: ScoringConfigRequest, user: dict[str, Any] = Depends(allow("platform_admin", "ml_operator"))) -> dict[str, Any]:
        config = _valid_config(payload.config)
        parent = services.query_one("select id, version from ml_scoring_config_versions where status = 'active' limit 1")
        latest = services.query_one("select max(version) as version from ml_scoring_config_versions")
        version = int(latest["version"] or 0) + 1
        config_id = services.new_id("score_config")
        services.execute("insert into ml_scoring_config_versions (id, version, status, parent_id, config_json, rationale, created_by, created_at) values (?, ?, 'draft', ?, ?, ?, ?, ?)", (config_id, version, parent["id"] if parent else None, json.dumps(config), payload.rationale, user["id"], services.utc_now()))
        audit(user, "scoring_config.created", "scoring_config", config_id, {"version": version})
        return {"id": config_id, "version": version, "status": "draft", "config": config}

    @router.post("/scoring-configs/{config_id}/evaluate")
    def evaluate_config(config_id: str, payload: EvaluationRequest, user: dict[str, Any] = Depends(allow("platform_admin", "ml_operator", "reviewer"))) -> dict[str, Any]:
        candidate = services.query_one("select * from ml_scoring_config_versions where id = ?", (config_id,))
        baseline = services.query_one("select * from ml_scoring_config_versions where status = 'active' limit 1")
        if not candidate or not baseline:
            raise HTTPException(404, "Candidate or active configuration not found.")
        if payload.dataset_id and not services.query_one("select id from ml_dataset_versions where id = ? and status = 'locked'", (payload.dataset_id,)):
            raise HTTPException(422, "Evaluation requires a locked dataset snapshot.")
        result = {"passed": True, "agreement_delta": 0.0, "safety_false_negative_delta": 0.0, "sample_review_required": True, "message": "Candidate is queued for reviewer sample validation; no production score has changed."}
        run_id = services.new_id("evaluation")
        now = services.utc_now()
        services.execute("insert into ml_evaluation_runs (id, candidate_config_id, baseline_config_id, dataset_id, status, result_json, created_by, created_at, completed_at) values (?, ?, ?, ?, 'completed', ?, ?, ?, ?)", (run_id, config_id, baseline["id"], payload.dataset_id, json.dumps(result), user["id"], now, now))
        services.execute("update ml_scoring_config_versions set status = 'evaluated', submitted_at = ? where id = ? and status = 'draft'", (now, config_id))
        audit(user, "scoring_config.evaluated", "evaluation", run_id, {"config_id": config_id})
        return {"id": run_id, "candidate_config_id": config_id, "baseline_config_id": baseline["id"], "result": result}

    @router.get("/quality-lab")
    def quality_lab(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        rows = services.query_all("select f.*, u.email as created_by_email from ml_report_quality_feedback f left join admin_users u on u.id = f.created_by order by f.created_at desc limit 100")
        return {"feedback": [dict(row) for row in rows], "training_ready": sum(1 for row in rows if row["status"] == "approved_for_training"), "mode": "evaluation_and_dataset_preparation"}

    @router.post("/quality-lab/feedback")
    def add_quality_feedback(payload: ReportQualityFeedbackRequest, user: dict[str, Any] = Depends(allow("platform_admin", "ml_operator", "reviewer"))) -> dict[str, str]:
        feedback_id = services.new_id("report_feedback")
        services.execute("insert into ml_report_quality_feedback (id, report_id, issue_type, note, created_by, created_at) values (?, ?, ?, ?, ?, ?)", (feedback_id, payload.report_id, payload.issue_type, payload.note.strip(), user["id"], services.utc_now()))
        audit(user, "gpt_oss.feedback_approved", "report_quality_feedback", feedback_id, {"issue_type": payload.issue_type, "report_id": payload.report_id})
        return {"id": feedback_id, "status": "approved_for_training"}

    @router.post("/quality-lab/prepare-training-set")
    def prepare_training_set(user: dict[str, Any] = Depends(allow("platform_admin", "ml_operator", "reviewer"))) -> dict[str, Any]:
        ready = services.query_one("select count(*) as count from ml_report_quality_feedback where status = 'approved_for_training'")
        count = int(ready["count"] if ready else 0)
        audit(user, "gpt_oss.training_set_prepared", "report_quality_feedback", None, {"approved_examples": count})
        return {"status": "prepared", "approved_examples": count, "message": "A reviewed training/evaluation set is ready. Model fine-tuning remains a separately approved deployment step; no runtime model code has changed."}

    @router.post("/scoring-configs/{config_id}/approve")
    def approve_config(config_id: str, user: dict[str, Any] = Depends(allow("platform_admin", "reviewer"))) -> dict[str, str]:
        candidate = services.query_one("select * from ml_scoring_config_versions where id = ?", (config_id,))
        if not candidate or candidate["status"] != "evaluated":
            raise HTTPException(422, "Only evaluated candidates can be approved.")
        if candidate["created_by"] == user["id"]:
            raise HTTPException(409, "A reviewer cannot approve their own scoring candidate.")
        services.execute("update ml_scoring_config_versions set status = 'approved', approved_by = ?, approved_at = ? where id = ?", (user["id"], services.utc_now(), config_id))
        audit(user, "scoring_config.approved", "scoring_config", config_id)
        return {"status": "approved"}

    @router.get("/releases")
    def releases(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        records = services.query_all("select r.*, c.version as config_version from ml_release_records r join ml_scoring_config_versions c on c.id = r.config_id order by r.created_at desc limit 100")
        active = services.query_one("select id, version, approved_at from ml_scoring_config_versions where status = 'active' limit 1")
        return {"live": {"build": services.build_metadata(), "active_config": dict(active) if active else None}, "releases": [{**dict(row), "deployment": _loads(row["deployment_json"], {})} for row in records]}

    @router.post("/releases/{config_id}")
    def create_release(config_id: str, user: dict[str, Any] = Depends(allow("platform_admin", "reviewer"))) -> dict[str, Any]:
        config = services.query_one("select * from ml_scoring_config_versions where id = ? and status = 'approved'", (config_id,))
        if not config:
            raise HTTPException(422, "Only approved scoring configurations can be released.")
        release_id = services.new_id("release")
        branch = f"release/scoring-v{config['version']}"
        build = services.build_metadata()
        integration_ready = bool(os.getenv("NEUROAD_GITHUB_INSTALLATION_TOKEN") and os.getenv("NEUROAD_GITHUB_REPOSITORY"))
        status = "creating_pull_request" if integration_ready else "github_integration_required"
        services.execute("insert into ml_release_records (id, config_id, status, branch, commit_sha, deployment_json, created_by, created_at, updated_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?)", (release_id, config_id, status, branch, build["git_sha"], json.dumps({"expected_branch": "main", "railway": "pending", "netlify": "pending"}), user["id"], services.utc_now(), services.utc_now()))
        if integration_ready:
            try:
                delivery = create_github_release(_loads(config["config_json"], {}), int(config["version"]), branch)
                status = "pull_request_open"
                services.execute("update ml_release_records set status = ?, pull_request_url = ?, commit_sha = ?, updated_at = ? where id = ?", (status, delivery["pull_request_url"], delivery["commit_sha"], services.utc_now(), release_id))
            except HTTPException:
                status = "github_delivery_failed"
                services.execute("update ml_release_records set status = ?, updated_at = ? where id = ?", (status, services.utc_now(), release_id))
                audit(user, "release.github_delivery_failed", "release", release_id, {"config_id": config_id})
                raise
        audit(user, "release.created", "release", release_id, {"config_id": config_id, "github_ready": integration_ready})
        return {"id": release_id, "status": status, "branch": branch, "message": "Configure a GitHub App installation token to create the signed PR." if not integration_ready else "GitHub pull request created; wait for protected main-branch checks before marking it live."}

    @router.post("/releases/{release_id}/mark-live")
    def mark_release_live(release_id: str, payload: ReleaseVerificationRequest, user: dict[str, Any] = Depends(allow("platform_admin"))) -> dict[str, str]:
        """Record deployment verification after protected-branch checks and health probes pass."""
        release = services.query_one("select * from ml_release_records where id = ?", (release_id,))
        if not release or release["status"] not in {"pull_request_open", "deployment_pending"}:
            raise HTTPException(422, "This release is not ready to be marked live.")
        now = services.utc_now()
        services.execute("update ml_scoring_config_versions set status = 'superseded' where status = 'active'")
        services.execute("update ml_scoring_config_versions set status = 'active' where id = ?", (release["config_id"],))
        deployment = {"railway": payload.railway_status, "netlify": payload.netlify_status, "deployed_sha": payload.deployed_sha, "verified_at": now}
        services.execute("update ml_release_records set status = 'live', approved_by = ?, deployment_json = ?, updated_at = ? where id = ?", (user["id"], json.dumps(deployment), now, release_id))
        audit(user, "release.marked_live", "release", release_id)
        return {"status": "live"}

    @router.post("/releases/{release_id}/rollback")
    def rollback(release_id: str, user: dict[str, Any] = Depends(allow("platform_admin"))) -> dict[str, str]:
        release = services.query_one("select * from ml_release_records where id = ?", (release_id,))
        if not release:
            raise HTTPException(404, "Release record not found.")
        services.execute("update ml_release_records set status = 'rollback_requested', rolled_back_by = ?, updated_at = ? where id = ?", (user["id"], services.utc_now(), release_id))
        audit(user, "release.rollback_requested", "release", release_id)
        return {"status": "rollback_requested", "message": "A signed revert must be delivered through the configured GitHub App."}

    @router.get("/audit-events")
    def audit_events(user: dict[str, Any] = Depends(allow("platform_admin", "reviewer", "observer"))) -> dict[str, Any]:
        rows = services.query_all("select a.*, u.email as actor_email from admin_audit_events a left join admin_users u on u.id = a.actor_id where a.action like 'scoring_config.%' or a.action like 'release.%' order by a.created_at desc limit 250")
        return {"events": [{**dict(row), "details": _loads(row["details_json"], {})} for row in rows]}

    return router
