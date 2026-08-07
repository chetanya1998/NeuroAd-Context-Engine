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


def test_dataset_creation_rejects_media_without_training_consent(tmp_path, monkeypatch):
    client, execute = make_client(tmp_path, monkeypatch)
    execute("insert into videos (id, title, status, created_at) values ('video_1', 'Example', 'completed', '2026-08-06T00:00:00')")
    login(client)
    payload = {"name": "No consent", "video_ids": ["video_1"], "taxonomy_id": "taxonomy_quality_evidence_v1"}
    response = client.post("/internal/admin/v1/datasets", json=payload)
    assert response.status_code == 422
