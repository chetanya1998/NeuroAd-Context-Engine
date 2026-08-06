from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field


PUBLIC_BATCH_LIMIT = 10
PUBLIC_FREE_MONTHLY_VIDEO_LIMIT = 10
PUBLIC_FREE_RETENTION_SECONDS = 30 * 60
API_VERSION = "2026-08-01"


@dataclass
class DeveloperServices:
    execute: Callable[..., None]
    query_one: Callable[..., Any]
    query_all: Callable[..., list[Any]]
    new_id: Callable[[str], str]
    utc_now: Callable[[], str]
    store_uploaded_video: Callable[[UploadFile], Awaitable[dict[str, Any]]]
    create_video_analysis_job: Callable[..., dict[str, Any]]
    add_video_to_comparison: Callable[[str, str], None]
    process_comparison_job: Callable[[str, list[dict[str, Any]]], None]
    submit_comparison: Callable[..., Any]
    build_analysis_payload: Callable[[Any], dict[str, Any]]
    build_comparison_payload: Callable[[Any], dict[str, Any]]
    storage_dir: Path


class ImprovementPlanRequest(BaseModel):
    objective: Literal["balanced", "attention", "drop_risk", "ad_fit", "brand_safety", "short_form"] = "balanced"
    custom_instruction: Optional[str] = Field(default=None, max_length=1000)
    target_provider: Optional[str] = Field(default=None, max_length=80)


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def init_developer_platform(services: DeveloperServices) -> None:
    services.execute(
        """
        create table if not exists developer_projects (
          id text primary key,
          name text not null,
          product text not null default 'public',
          tier text not null default 'free',
          status text not null default 'active',
          monthly_video_limit integer not null default 10,
          retention_seconds integer not null default 1800,
          created_at text not null,
          updated_at text not null
        )
        """
    )
    services.execute(
        """
        create table if not exists developer_api_keys (
          id text primary key,
          project_id text not null,
          key_prefix text not null,
          secret_hash text not null unique,
          scopes text not null,
          status text not null default 'active',
          last_used_at text,
          created_at text not null
        )
        """
    )
    services.execute(
        """
        create table if not exists developer_batches (
          id text primary key,
          project_id text not null,
          mode text not null,
          title text not null,
          status text not null,
          comparison_id text,
          total_videos integer not null,
          completed_videos integer not null default 0,
          failed_videos integer not null default 0,
          idempotency_key text,
          created_at text not null,
          updated_at text not null,
          unique(project_id, idempotency_key)
        )
        """
    )
    services.execute(
        """
        create table if not exists developer_batch_videos (
          id text primary key,
          batch_id text not null,
          video_id text not null,
          display_order integer not null,
          unique(batch_id, video_id)
        )
        """
    )
    services.execute(
        """
        create table if not exists mcp_approvals (
          id text primary key,
          project_id text not null,
          action text not null,
          target_id text not null,
          plan_fingerprint text not null,
          status text not null default 'pending',
          expires_at text not null,
          consumed_at text,
          created_at text not null
        )
        """
    )
    services.execute(
        """
        create table if not exists developer_revision_requests (
          id text primary key,
          project_id text not null,
          parent_video_id text not null,
          revision_video_id text not null,
          idempotency_key text not null,
          created_at text not null,
          unique(project_id, idempotency_key)
        )
        """
    )

    bootstrap_key = os.getenv("NEUROAD_BOOTSTRAP_API_KEY", "").strip()
    if bootstrap_key and not services.query_one("select id from developer_api_keys where secret_hash = ?", (hash_secret(bootstrap_key),)):
        now = services.utc_now()
        project_id = "project_bootstrap"
        services.execute(
            """insert or ignore into developer_projects
               (id, name, product, tier, status, monthly_video_limit, retention_seconds, created_at, updated_at)
               values (?, 'Bootstrap project', 'internal', 'free', 'active', ?, ?, ?, ?)""",
            (project_id, PUBLIC_FREE_MONTHLY_VIDEO_LIMIT, PUBLIC_FREE_RETENTION_SECONDS, now, now),
        )
        services.execute(
            """insert into developer_api_keys
               (id, project_id, key_prefix, secret_hash, scopes, status, created_at)
               values (?, ?, ?, ?, ?, 'active', ?)""",
            (
                services.new_id("api_key"), project_id, bootstrap_key[:12], hash_secret(bootstrap_key),
                json.dumps(["analysis:read", "analysis:write", "comparisons:write", "data:delete"]), now,
            ),
        )


def create_api_key(services: DeveloperServices, project_id: str, raw_key: str, scopes: Optional[list[str]] = None) -> str:
    now = services.utc_now()
    services.execute(
        """insert into developer_api_keys
           (id, project_id, key_prefix, secret_hash, scopes, status, created_at)
           values (?, ?, ?, ?, ?, 'active', ?)""",
        (
            services.new_id("api_key"), project_id, raw_key[:12], hash_secret(raw_key),
            json.dumps(scopes or ["analysis:read", "analysis:write", "comparisons:write", "data:delete"]), now,
        ),
    )
    return raw_key


def authenticate_api_key(services: DeveloperServices, authorization: Optional[str], required_scope: str) -> dict[str, Any]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Provide a NeuroAd API key as a Bearer token.")
    raw_key = authorization.split(" ", 1)[1].strip()
    if not raw_key:
        raise HTTPException(status_code=401, detail="The API key is missing.")
    row = services.query_one(
        """select k.*, p.name as project_name, p.product, p.tier, p.monthly_video_limit, p.retention_seconds
           from developer_api_keys k join developer_projects p on p.id = k.project_id
           where k.secret_hash = ? and k.status = 'active' and p.status = 'active'""",
        (hash_secret(raw_key),),
    )
    if not row or not hmac.compare_digest(str(row["secret_hash"]), hash_secret(raw_key)):
        raise HTTPException(status_code=401, detail="The API key is invalid or revoked.")
    scopes = set(json.loads(row["scopes"] or "[]"))
    if required_scope not in scopes:
        raise HTTPException(status_code=403, detail=f"The API key lacks the {required_scope} scope.")
    services.execute("update developer_api_keys set last_used_at = ? where id = ?", (services.utc_now(), row["id"]))
    result = dict(row)
    result["scopes"] = sorted(scopes)
    return result


def _month_start() -> str:
    now = datetime.utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")


def enforce_monthly_quota(services: DeveloperServices, project: dict[str, Any], incoming: int) -> None:
    used_row = services.query_one(
        "select count(*) as count from videos where project_id = ? and created_at >= ?",
        (project["project_id"], _month_start()),
    )
    used = int(used_row["count"] if used_row else 0)
    limit = int(project["monthly_video_limit"] or PUBLIC_FREE_MONTHLY_VIDEO_LIMIT)
    if used + incoming > limit:
        raise HTTPException(
            status_code=429,
            detail=f"Monthly video quota exceeded. This project has used {used} of {limit} videos.",
        )


def _owned_video(services: DeveloperServices, project_id: str, video_id: str) -> Any:
    row = services.query_one("select * from videos where id = ? and project_id = ?", (video_id, project_id))
    if not row:
        raise HTTPException(status_code=404, detail="Video not found in this project.")
    return row


def _owned_batch(services: DeveloperServices, project_id: str, batch_id: str) -> Any:
    row = services.query_one("select * from developer_batches where id = ? and project_id = ?", (batch_id, project_id))
    if not row:
        raise HTTPException(status_code=404, detail="Batch not found in this project.")
    return row


def refresh_batch(services: DeveloperServices, batch: Any) -> dict[str, Any]:
    members = services.query_all(
        "select video_id, display_order from developer_batch_videos where batch_id = ? order by display_order",
        (batch["id"],),
    )
    videos: list[dict[str, Any]] = []
    completed = failed = 0
    for member in members:
        video = services.query_one("select status, retention_expires_at from videos where id = ?", (member["video_id"],))
        job = services.query_one("select * from jobs where video_id = ? order by created_at desc limit 1", (member["video_id"],))
        status = str(video["status"] if video else "failed")
        completed += int(status == "completed")
        failed += int(status == "failed")
        videos.append({
            "video_id": member["video_id"], "status": status,
            "job_id": job["id"] if job else None, "progress": int(job["progress"] if job else 0),
            "error": job["error"] if job else None,
        })
    terminal = completed + failed == len(members) and bool(members)
    status = "completed" if terminal and failed == 0 else "partial" if terminal and completed else "failed" if terminal else "processing"
    services.execute(
        "update developer_batches set status = ?, completed_videos = ?, failed_videos = ?, updated_at = ? where id = ?",
        (status, completed, failed, services.utc_now(), batch["id"]),
    )
    return {
        "batch_id": batch["id"], "mode": batch["mode"], "title": batch["title"], "status": status,
        "total_videos": len(members), "completed_videos": completed, "failed_videos": failed,
        "comparison_id": batch["comparison_id"], "videos": videos, "created_at": batch["created_at"],
    }


def build_improvement_plan(payload: dict[str, Any], objective: str = "balanced", custom_instruction: Optional[str] = None, target_provider: Optional[str] = None) -> dict[str, Any]:
    weights = {
        "balanced": (0.35, 0.25, 0.20, 0.20), "attention": (0.55, 0.20, 0.15, 0.10),
        "drop_risk": (0.25, 0.55, 0.10, 0.10), "ad_fit": (0.25, 0.15, 0.50, 0.10),
        "brand_safety": (0.20, 0.15, 0.10, 0.55), "short_form": (0.50, 0.30, 0.10, 0.10),
    }[objective]
    actions: list[dict[str, Any]] = []
    for segment in payload.get("segments", []):
        attention = float(segment.get("attention_score", 0))
        drop = float(segment.get("drop_risk_score", 0))
        ad_fit = float(segment.get("ad_fit_score", 0))
        safety = float(segment.get("brand_safety_score", 100))
        urgency = (100 - attention) * weights[0] + drop * weights[1] + (100 - ad_fit) * weights[2] + (100 - safety) * weights[3]
        if urgency < 38 and objective != "short_form":
            continue
        action = "tighten_or_replace" if drop >= 60 or attention < 40 else "strengthen_context"
        if safety < 70:
            action = "remove_or_rewrite_risky_claim"
        elif objective == "short_form" and attention >= 65:
            action = "feature_in_short_form_cut"
        actions.append({
            "action_id": f"action_{len(actions) + 1}", "segment_id": segment["id"],
            "start_seconds": segment["start"], "end_seconds": segment["end"], "operation": action,
            "priority": int(round(min(100, urgency))), "recommendation": segment.get("recommendation", ""),
            "evidence_refs": [segment["id"]], "requires_human_review": True,
        })
    actions.sort(key=lambda item: item["priority"], reverse=True)
    canonical = {
        "video_id": payload["video"]["id"], "analysis_version": "attention-proxy-v1",
        "objective": objective, "custom_instruction": custom_instruction, "target_provider": target_provider,
        "actions": actions[:12], "original_preserved": True,
    }
    fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode("utf-8")).hexdigest()
    edit_prompt = (
        f"Create a non-destructive revision of video {payload['video']['id']} optimized for {objective}. "
        "Apply only the timestamped operations in actions, preserve the original, and return an exported video for re-analysis."
    )
    if custom_instruction:
        edit_prompt += f" Additional direction: {custom_instruction.strip()}"
    return {
        "plan_id": f"plan_{fingerprint[:12]}", "plan_fingerprint": fingerprint, **canonical,
        "approval_required_for_execution": True,
        "destination_handoff": {
            "schema": "neuroad.edit-plan.v1",
            "provider": target_provider or "generic",
            "prompt": edit_prompt,
            "timeline_operations": actions[:12],
            "expected_output": {
                "type": "video",
                "preserve_original": True,
                "next_step": f"Upload the export to /v1/videos/{payload['video']['id']}/revisions for re-analysis.",
            },
        },
        "limitations": [
            "Recommendations are decision support and do not guarantee audience or campaign performance.",
            "The destination tool may not support every requested timeline operation.",
        ],
    }


def create_developer_router(services: DeveloperServices) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["Developer API v1"])

    @router.get("/meta")
    def metadata() -> dict[str, Any]:
        return {
            "api_version": API_VERSION, "product": "NeuroAd Developer API",
            "batch_limit": PUBLIC_BATCH_LIMIT, "input_mode": "upload_only",
            "modes": ["analyze", "compare"],
        }

    @router.post("/batches")
    async def create_batch(
        files: list[UploadFile] = File(...),
        mode: Literal["analyze", "compare"] = Form("analyze"),
        title: str = Form("Video batch"),
        authorization: Optional[str] = Header(default=None),
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        project = authenticate_api_key(services, authorization, "analysis:write")
        if mode == "compare" and "comparisons:write" not in project["scopes"]:
            raise HTTPException(status_code=403, detail="The API key lacks the comparisons:write scope.")
        if not idempotency_key or len(idempotency_key) > 160:
            raise HTTPException(status_code=400, detail="Provide an Idempotency-Key of at most 160 characters.")
        existing = services.query_one(
            "select * from developer_batches where project_id = ? and idempotency_key = ?",
            (project["project_id"], idempotency_key),
        )
        if existing:
            return refresh_batch(services, existing)
        if not files or len(files) > PUBLIC_BATCH_LIMIT:
            raise HTTPException(status_code=400, detail=f"Upload between 1 and {PUBLIC_BATCH_LIMIT} videos.")
        if mode == "compare" and len(files) < 2:
            raise HTTPException(status_code=400, detail="Comparison mode requires at least two videos.")
        enforce_monthly_quota(services, project, len(files))
        batch_id = services.new_id("batch")
        comparison_id = services.new_id("comparison") if mode == "compare" else None
        now = services.utc_now()
        services.execute(
            """insert into developer_batches
               (id, project_id, mode, title, status, comparison_id, total_videos, idempotency_key, created_at, updated_at)
               values (?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)""",
            (batch_id, project["project_id"], mode, title[:160] or "Video batch", comparison_id, len(files), idempotency_key, now, now),
        )
        if comparison_id:
            services.execute(
                """insert into comparisons
                   (id, title, status, comparison_mode, total_videos, completed_videos, failed_videos, project_id, created_at, updated_at)
                   values (?, ?, 'created', 'pending', 0, 0, 0, ?, ?, ?)""",
                (comparison_id, title[:160] or "Video comparison", project["project_id"], now, now),
            )
        members: list[dict[str, Any]] = []
        for index, file in enumerate(files):
            uploaded = await services.store_uploaded_video(file)
            retention = int(project["retention_seconds"] or PUBLIC_FREE_RETENTION_SECONDS)
            services.execute(
                "update videos set project_id = ?, retention_seconds = ? where id = ?",
                (project["project_id"], retention, uploaded["video_id"]),
            )
            services.execute(
                "insert into developer_batch_videos (id, batch_id, video_id, display_order) values (?, ?, ?, ?)",
                (services.new_id("batch_video"), batch_id, uploaded["video_id"], index + 1),
            )
            if comparison_id:
                services.add_video_to_comparison(comparison_id, uploaded["video_id"])
                member = services.query_one(
                    "select * from comparison_videos where comparison_id = ? and video_id = ?",
                    (comparison_id, uploaded["video_id"]),
                )
                members.append(dict(member))
            else:
                services.create_video_analysis_job(uploaded["video_id"])
        if comparison_id:
            services.submit_comparison(services.process_comparison_job, comparison_id, members)
        batch = services.query_one("select * from developer_batches where id = ?", (batch_id,))
        return refresh_batch(services, batch)

    @router.post("/videos/{video_id}/revisions")
    async def upload_revision(
        video_id: str,
        file: UploadFile = File(...),
        authorization: Optional[str] = Header(default=None),
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        """Upload an edited export as a traceable revision and start a fresh analysis."""
        project = authenticate_api_key(services, authorization, "analysis:write")
        parent = _owned_video(services, project["project_id"], video_id)
        if not idempotency_key or len(idempotency_key) > 160:
            raise HTTPException(status_code=400, detail="Provide an Idempotency-Key of at most 160 characters.")
        replay = services.query_one(
            """select v.*, r.parent_video_id as request_parent_video_id
               from videos v join developer_revision_requests r on r.revision_video_id = v.id
               where r.project_id = ? and r.idempotency_key = ?""",
            (project["project_id"], idempotency_key),
        )
        if replay:
            if replay["request_parent_video_id"] != parent["id"]:
                raise HTTPException(status_code=409, detail="The Idempotency-Key was already used for another revision request.")
            job = services.query_one("select * from jobs where video_id = ? order by created_at desc limit 1", (replay["id"],))
            return {
                "video_id": replay["id"], "parent_video_id": replay["parent_video_id"],
                "root_video_id": replay["root_video_id"], "revision_number": replay["revision_number"],
                "job_id": job["id"] if job else None, "status": replay["status"], "idempotent_replay": True,
            }
        enforce_monthly_quota(services, project, 1)
        uploaded = await services.store_uploaded_video(file)
        revision_id = uploaded["video_id"]
        root_video_id = parent["root_video_id"] or parent["id"]
        revision_row = services.query_one(
            "select max(revision_number) as revision_number from videos where project_id = ? and (id = ? or root_video_id = ?)",
            (project["project_id"], root_video_id, root_video_id),
        )
        revision_number = int(revision_row["revision_number"] or 0) + 1
        retention = int(project["retention_seconds"] or PUBLIC_FREE_RETENTION_SECONDS)
        now = services.utc_now()
        services.execute(
            """update videos set project_id = ?, retention_seconds = ?, parent_video_id = ?,
               root_video_id = ?, revision_number = ? where id = ?""",
            (project["project_id"], retention, parent["id"], root_video_id, revision_number, revision_id),
        )
        services.execute(
            """insert into developer_revision_requests
               (id, project_id, parent_video_id, revision_video_id, idempotency_key, created_at)
               values (?, ?, ?, ?, ?, ?)""",
            (services.new_id("revision_request"), project["project_id"], parent["id"], revision_id, idempotency_key, now),
        )
        result = services.create_video_analysis_job(revision_id)
        return {
            "video_id": revision_id, "parent_video_id": parent["id"], "root_video_id": root_video_id,
            "revision_number": revision_number, **result, "idempotent_replay": False,
        }

    @router.get("/batches/{batch_id}")
    def get_batch(batch_id: str, authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
        project = authenticate_api_key(services, authorization, "analysis:read")
        return refresh_batch(services, _owned_batch(services, project["project_id"], batch_id))

    @router.get("/batches/{batch_id}/results")
    def get_batch_results(batch_id: str, authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
        project = authenticate_api_key(services, authorization, "analysis:read")
        batch = _owned_batch(services, project["project_id"], batch_id)
        status = refresh_batch(services, batch)
        analyses = []
        for item in status["videos"]:
            if item["status"] == "completed":
                analyses.append(services.build_analysis_payload(_owned_video(services, project["project_id"], item["video_id"])))
        comparison = None
        if batch["comparison_id"] and len(analyses) >= 2:
            row = services.query_one("select * from comparisons where id = ? and project_id = ?", (batch["comparison_id"], project["project_id"]))
            comparison = services.build_comparison_payload(row) if row else None
        return {"batch": status, "analyses": analyses, "comparison": comparison}

    @router.get("/videos/{video_id}/analysis")
    def get_video_analysis(video_id: str, authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
        project = authenticate_api_key(services, authorization, "analysis:read")
        video = _owned_video(services, project["project_id"], video_id)
        if video["status"] != "completed":
            raise HTTPException(status_code=409, detail="Video analysis is not complete.")
        return services.build_analysis_payload(video)

    @router.post("/videos/{video_id}/improvement-plans")
    def create_plan(video_id: str, payload: ImprovementPlanRequest, authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
        project = authenticate_api_key(services, authorization, "analysis:read")
        video = _owned_video(services, project["project_id"], video_id)
        if video["status"] != "completed":
            raise HTTPException(status_code=409, detail="Complete the analysis before creating an improvement plan.")
        return build_improvement_plan(
            services.build_analysis_payload(video), payload.objective, payload.custom_instruction, payload.target_provider,
        )

    return router
