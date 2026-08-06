from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from developer_platform import (
    DeveloperServices,
    authenticate_api_key,
    build_improvement_plan,
    create_api_key,
    create_developer_router,
    init_developer_platform,
)


def make_services(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "developer.db")
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(main, "FRAME_DIR", tmp_path / "frames")
    monkeypatch.setattr(main, "AUDIO_DIR", tmp_path / "audio")
    monkeypatch.setattr(main, "REPORT_DIR", tmp_path / "reports")
    main.init_db()
    upload_count = {"value": 0}

    async def fake_store(file):
        upload_count["value"] += 1
        video_id = f"video_{upload_count['value']}"
        main.execute(
            """insert into videos
               (id, source_type, title, duration_seconds, status, file_path, created_at)
               values (?, 'upload', ?, 5, 'uploaded', ?, ?)""",
            (video_id, file.filename or video_id, str(tmp_path / f"{video_id}.mp4"), main.utc_now()),
        )
        return {"video_id": video_id, "status": "uploaded", "duration_seconds": 5}

    def fake_job(video_id, **kwargs):
        job_id = f"job_{video_id}"
        now = main.utc_now()
        main.execute(
            """insert into jobs (id, video_id, status, progress, current_step, created_at, updated_at)
               values (?, ?, 'completed', 100, 'report', ?, ?)""",
            (job_id, video_id, now, now),
        )
        main.execute("update videos set status = 'completed' where id = ?", (video_id,))
        return {"job_id": job_id, "status": "completed"}

    def fake_analysis(video):
        return {
            "video": {"id": video["id"], "title": video["title"], "status": video["status"]},
            "summary": {"overall_attention_score": 60},
            "recommendations": [],
            "segments": [],
        }

    services = DeveloperServices(
        execute=main.execute, query_one=main.query_one, query_all=main.query_all,
        new_id=main.new_id, utc_now=main.utc_now, store_uploaded_video=fake_store,
        create_video_analysis_job=fake_job, add_video_to_comparison=lambda *_: None,
        process_comparison_job=lambda *_: None, submit_comparison=lambda *_: None,
        build_analysis_payload=fake_analysis, build_comparison_payload=lambda row: {"comparison_id": row["id"]},
        storage_dir=tmp_path,
    )
    init_developer_platform(services)
    now = main.utc_now()
    main.execute(
        """insert into developer_projects
           (id, name, product, tier, status, monthly_video_limit, retention_seconds, created_at, updated_at)
           values ('project_test', 'Test', 'public', 'free', 'active', 10, 1800, ?, ?)""",
        (now, now),
    )
    create_api_key(services, "project_test", "nad_test_secret")
    return services, upload_count


def test_api_key_authentication_enforces_scopes(monkeypatch, tmp_path):
    services, _ = make_services(monkeypatch, tmp_path)
    project = authenticate_api_key(services, "Bearer nad_test_secret", "analysis:read")
    assert project["project_id"] == "project_test"

    with pytest.raises(HTTPException) as error:
        authenticate_api_key(services, "Bearer wrong", "analysis:read")
    assert error.value.status_code == 401


def test_improvement_plan_is_timestamped_and_fingerprinted():
    payload = {
        "video": {"id": "video_1"},
        "segments": [
            {"id": "seg_1", "start": 0, "end": 4, "attention_score": 25, "drop_risk_score": 78,
             "ad_fit_score": 30, "brand_safety_score": 95, "recommendation": "Tighten the opening."},
            {"id": "seg_2", "start": 4, "end": 8, "attention_score": 82, "drop_risk_score": 12,
             "ad_fit_score": 75, "brand_safety_score": 98, "recommendation": "Keep this moment."},
        ],
    }
    plan = build_improvement_plan(payload, "attention", "Make the first benefit clear", "canva")
    assert plan["video_id"] == "video_1"
    assert plan["actions"][0]["segment_id"] == "seg_1"
    assert plan["actions"][0]["evidence_refs"] == ["seg_1"]
    assert len(plan["plan_fingerprint"]) == 64
    assert plan["approval_required_for_execution"] is True
    assert plan["destination_handoff"]["schema"] == "neuroad.edit-plan.v1"
    assert plan["destination_handoff"]["provider"] == "canva"


def test_upload_batch_is_idempotent_and_project_scoped(monkeypatch, tmp_path):
    services, upload_count = make_services(monkeypatch, tmp_path)
    test_app = FastAPI()
    test_app.include_router(create_developer_router(services))
    client = TestClient(test_app)
    headers = {"Authorization": "Bearer nad_test_secret", "Idempotency-Key": "batch-once"}
    files = [
        ("files", ("one.mp4", b"one", "video/mp4")),
        ("files", ("two.mp4", b"two", "video/mp4")),
    ]
    first = client.post("/v1/batches", headers=headers, data={"mode": "analyze", "title": "Test"}, files=files)
    assert first.status_code == 200
    assert first.json()["total_videos"] == 2
    assert first.json()["status"] == "completed"

    repeated = client.post("/v1/batches", headers=headers, data={"mode": "analyze", "title": "Ignored"}, files=files)
    assert repeated.status_code == 200
    assert repeated.json()["batch_id"] == first.json()["batch_id"]
    assert upload_count["value"] == 2

    unauthorized = client.get(f"/v1/batches/{first.json()['batch_id']}")
    assert unauthorized.status_code == 401


def test_revision_upload_preserves_lineage_and_is_idempotent(monkeypatch, tmp_path):
    services, _ = make_services(monkeypatch, tmp_path)
    now = main.utc_now()
    main.execute(
        """insert into videos
           (id, source_type, title, duration_seconds, status, file_path, project_id, revision_number, created_at)
           values ('video_original', 'upload', 'Original', 5, 'completed', ?, 'project_test', 0, ?)""",
        (str(tmp_path / "original.mp4"), now),
    )
    test_app = FastAPI()
    test_app.include_router(create_developer_router(services))
    client = TestClient(test_app)
    headers = {"Authorization": "Bearer nad_test_secret", "Idempotency-Key": "revision-once"}
    file = {"file": ("edited.mp4", b"edited", "video/mp4")}

    first = client.post("/v1/videos/video_original/revisions", headers=headers, files=file)
    assert first.status_code == 200
    payload = first.json()
    assert payload["parent_video_id"] == "video_original"
    assert payload["root_video_id"] == "video_original"
    assert payload["revision_number"] == 1
    assert payload["idempotent_replay"] is False

    repeated = client.post("/v1/videos/video_original/revisions", headers=headers, files=file)
    assert repeated.status_code == 200
    assert repeated.json()["video_id"] == payload["video_id"]
    assert repeated.json()["idempotent_replay"] is True


def test_expired_project_media_is_purged_but_record_is_retained(monkeypatch, tmp_path):
    make_services(monkeypatch, tmp_path)
    source = tmp_path / "expired.mp4"
    source.write_bytes(b"video")
    expired_at = (datetime.utcnow() - timedelta(minutes=1)).isoformat(timespec="seconds")
    main.execute(
        """insert into videos
           (id, source_type, title, status, file_path, project_id, retention_seconds,
            retention_expires_at, created_at)
           values ('video_expired', 'upload', 'Expired', 'completed', ?, 'project_test', 1800, ?, ?)""",
        (str(source), expired_at, main.utc_now()),
    )

    assert main.purge_expired_project_media() == 1
    video = main.query_one("select * from videos where id = 'video_expired'")
    assert video is not None
    assert video["file_path"] is None
    assert video["media_deleted_at"] is not None
    assert not source.exists()
