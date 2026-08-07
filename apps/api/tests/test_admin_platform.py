import json
import sqlite3
import sys
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from admin_platform import (  # noqa: E402
    DEFAULT_SCORING_CONFIG,
    AdminServices,
    create_admin_router,
    init_admin_platform,
)


def make_client(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.db"

    def connect():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def execute(sql, params=()):
        with connect() as conn:
            conn.execute(sql, params)
            conn.commit()

    def query_one(sql, params=()):
        with connect() as conn:
            return conn.execute(sql, params).fetchone()

    def query_all(sql, params=()):
        with connect() as conn:
            return conn.execute(sql, params).fetchall()

    for statement in (
        "create table videos (id text primary key, title text, status text, created_at text)",
        "create table jobs (id text primary key, status text, error text)",
        "create table reports (id text primary key)",
        "create table comparisons (id text primary key, status text)",
    ):
        execute(statement)
    monkeypatch.setenv("NEUROAD_ADMIN_BOOTSTRAP_EMAIL", "admin@neuroad.test")
    monkeypatch.setenv("NEUROAD_ADMIN_BOOTSTRAP_PASSWORD", "internal-password-123")
    services = AdminServices(
        execute=execute,
        query_one=query_one,
        query_all=query_all,
        new_id=lambda prefix: f"{prefix}_{uuid.uuid4().hex}",
        utc_now=lambda: "2026-08-06T00:00:00",
        runtime_dependencies=lambda: {},
        build_metadata=lambda: {"git_sha": "abc123", "git_branch": "main", "build_time": "now", "release_id": "release", "scoring_manifest_version": "v1"},
    )
    init_admin_platform(services)
    app = FastAPI()
    app.include_router(create_admin_router(services))
    return TestClient(app), execute


def login(client):
    response = client.post("/internal/admin/v1/auth/login", json={"email": "admin@neuroad.test", "password": "internal-password-123"})
    assert response.status_code == 200
    assert response.json()["session_token"]
    return response.json()["session_token"]


def test_admin_routes_require_an_internal_session(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    assert client.get("/internal/admin/v1/overview").status_code == 401
    login(client)
    response = client.get("/internal/admin/v1/overview")
    assert response.status_code == 200
    assert response.json()["build"]["git_sha"] == "abc123"


def test_admin_bearer_session_supports_separate_admin_origins(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    token = login(client)
    client.cookies.clear()
    response = client.get("/internal/admin/v1/overview", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


def test_scoring_candidates_are_validated_and_versioned(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    login(client)
    bad = {**DEFAULT_SCORING_CONFIG, "weights": {**DEFAULT_SCORING_CONFIG["weights"], "motion": 0.4}}
    assert client.post("/internal/admin/v1/scoring-configs", json={"config": bad, "rationale": "A valid explanation for an invalid total."}).status_code == 422
    response = client.post("/internal/admin/v1/scoring-configs", json={"config": DEFAULT_SCORING_CONFIG, "rationale": "Test candidate with the production baseline values."})
    assert response.status_code == 200
    assert response.json()["version"] == 2


def test_scoring_candidate_can_run_a_safe_simulation(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    login(client)
    candidate = client.post(
        "/internal/admin/v1/scoring-configs",
        json={"config": DEFAULT_SCORING_CONFIG, "rationale": "Validate the candidate against the locked baseline before release."},
    )
    assert candidate.status_code == 200
    simulation = client.post(f"/internal/admin/v1/scoring-configs/{candidate.json()['id']}/evaluate", json={})
    assert simulation.status_code == 200
    assert simulation.json()["result"]["passed"] is True


def test_monitoring_endpoints_support_presets_and_custom_datetime_ranges(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    login(client)
    preset = client.get("/internal/admin/v1/system-health?range_minutes=15")
    assert preset.status_code == 200
    assert preset.json()["metric_range"] == {"kind": "preset", "minutes": 15, "label": "Last 15 minutes"}
    custom = client.get("/internal/admin/v1/product-analytics?start=2026-08-05T00:00:00Z&end=2026-08-06T00:00:00Z")
    assert custom.status_code == 200
    assert custom.json()["metric_range"]["kind"] == "custom"
    assert client.get("/internal/admin/v1/overview?range_minutes=2").status_code == 422


def test_product_analytics_reports_privacy_filtered_key_action_users(tmp_path, monkeypatch):
    client, execute = make_client(tmp_path, monkeypatch)
    execute("insert into admin_metric_events (id, scope, event_name, actor_hash, metadata_json, occurred_at) values ('old_a', 'product', 'page_view', 'visitor_a', '{}', '2026-08-05T12:00:00')")
    execute("insert into admin_metric_events (id, scope, event_name, actor_hash, metadata_json, occurred_at) values ('recent_a', 'product', 'comparison_created', 'visitor_a', '{}', '2026-08-06T12:00:00')")
    execute("insert into admin_metric_events (id, scope, event_name, actor_hash, metadata_json, occurred_at) values ('recent_b', 'product', 'insight_report_requested', 'visitor_b', '{}', '2026-08-06T12:10:00')")
    execute("insert into admin_metric_events (id, scope, event_name, actor_hash, metadata_json, occurred_at) values ('recent_c', 'product', 'brand_fit_requested', 'visitor_c', '{}', '2026-08-06T12:20:00')")
    login(client)
    response = client.get("/internal/admin/v1/product-analytics?start=2026-08-06T00:00:00Z&end=2026-08-07T00:00:00Z")
    assert response.status_code == 200
    assert response.json()["user_activity"] == {"returning_visitors": 1, "multi_video_users": 1, "report_generation_users": 1, "brand_fit_users": 1}


def test_dataset_creation_rejects_media_without_training_consent(tmp_path, monkeypatch):
    client, execute = make_client(tmp_path, monkeypatch)
    execute("insert into videos (id, title, status, created_at) values ('video_1', 'Example', 'completed', '2026-08-06T00:00:00')")
    login(client)
    payload = {"name": "No consent", "video_ids": ["video_1"], "taxonomy_id": "taxonomy_quality_evidence_v1"}
    response = client.post("/internal/admin/v1/datasets", json=payload)
    assert response.status_code == 422


def test_quality_feedback_is_prepared_without_expanding_release_audit(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    login(client)
    feedback = client.post(
        "/internal/admin/v1/quality-lab/feedback",
        json={"issue_type": "incorrect_score", "note": "The report should cite the sampled scene evidence before assigning a score."},
    )
    assert feedback.status_code == 200
    quality = client.get("/internal/admin/v1/quality-lab")
    assert quality.status_code == 200
    assert quality.json()["training_ready"] == 1
    prepared = client.post("/internal/admin/v1/quality-lab/prepare-training-set")
    assert prepared.status_code == 200
    assert prepared.json()["approved_examples"] == 1
    audit = client.get("/internal/admin/v1/audit-events")
    assert audit.status_code == 200
    assert all(event["action"].startswith(("scoring_config.", "release.")) for event in audit.json()["events"])
