from __future__ import annotations

import html
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from mcp.types import ToolAnnotations

from developer_platform import DeveloperServices, authenticate_api_key, build_improvement_plan, hash_secret


MCP_SCOPES = ["analysis:read", "analysis:write"]
ACCESS_TOKEN_SECONDS = 60 * 60
REFRESH_TOKEN_SECONDS = 30 * 24 * 60 * 60
AUTH_CODE_SECONDS = 5 * 60
APPROVAL_SECONDS = 15 * 60


@dataclass
class McpRuntime:
    mcp: FastMCP
    app: Any


class NeuroAdOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    def __init__(self, services: DeveloperServices, public_base_url: str):
        self.services = services
        self.public_base_url = public_base_url.rstrip("/")
        self._init_tables()

    def _init_tables(self) -> None:
        self.services.execute(
            """create table if not exists mcp_oauth_clients (
               client_id text primary key, client_json text not null, created_at text not null)"""
        )
        self.services.execute(
            """create table if not exists mcp_oauth_pending (
               id text primary key, client_id text not null, params_json text not null,
               expires_at integer not null, created_at text not null)"""
        )
        self.services.execute(
            """create table if not exists mcp_oauth_codes (
               code_hash text primary key, client_id text not null, project_id text not null,
               code_json text not null, used_at text, created_at text not null)"""
        )
        self.services.execute(
            """create table if not exists mcp_oauth_tokens (
               access_hash text primary key, refresh_hash text unique, client_id text not null,
               project_id text not null, scopes text not null, access_expires_at integer not null,
               refresh_expires_at integer not null, revoked_at text, created_at text not null)"""
        )

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        row = self.services.query_one("select client_json from mcp_oauth_clients where client_id = ?", (client_id,))
        return OAuthClientInformationFull.model_validate_json(row["client_json"]) if row else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        # NeuroAd accepts public PKCE clients. Secrets are deliberately not persisted.
        if client_info.client_secret or client_info.token_endpoint_auth_method not in {None, "none"}:
            raise RegistrationError(
                error="invalid_client_metadata",
                error_description="NeuroAd accepts public PKCE clients only.",
            )
        self.services.execute(
            "insert or replace into mcp_oauth_clients (client_id, client_json, created_at) values (?, ?, ?)",
            (str(client_info.client_id), client_info.model_dump_json(), self.services.utc_now()),
        )

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        request_id = secrets.token_urlsafe(32)
        self.services.execute(
            "insert into mcp_oauth_pending (id, client_id, params_json, expires_at, created_at) values (?, ?, ?, ?, ?)",
            (request_id, str(client.client_id), params.model_dump_json(), int(time.time()) + AUTH_CODE_SECONDS, self.services.utc_now()),
        )
        return f"{self.public_base_url}/mcp/consent?request_id={request_id}"

    async def complete_authorization(self, request_id: str, raw_api_key: str) -> str:
        pending = self.services.query_one("select * from mcp_oauth_pending where id = ?", (request_id,))
        if not pending or int(pending["expires_at"]) < int(time.time()):
            raise ValueError("The authorization request is missing or expired.")
        project = authenticate_api_key(self.services, f"Bearer {raw_api_key}", "analysis:read")
        params = AuthorizationParams.model_validate_json(pending["params_json"])
        code = secrets.token_urlsafe(32)
        scopes = [scope for scope in (params.scopes or MCP_SCOPES) if scope in set(project["scopes"])]
        authorization_code = AuthorizationCode(
            code=code, scopes=scopes, expires_at=time.time() + AUTH_CODE_SECONDS,
            client_id=pending["client_id"], code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri, redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource, subject=project["project_id"],
        )
        self.services.execute(
            "insert into mcp_oauth_codes (code_hash, client_id, project_id, code_json, created_at) values (?, ?, ?, ?, ?)",
            (hash_secret(code), pending["client_id"], project["project_id"], authorization_code.model_dump_json(), self.services.utc_now()),
        )
        self.services.execute("delete from mcp_oauth_pending where id = ?", (request_id,))
        query = urlencode({"code": code, **({"state": params.state} if params.state else {})})
        separator = "&" if "?" in str(params.redirect_uri) else "?"
        return f"{params.redirect_uri}{separator}{query}"

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str) -> AuthorizationCode | None:
        row = self.services.query_one(
            "select * from mcp_oauth_codes where code_hash = ? and client_id = ? and used_at is null",
            (hash_secret(authorization_code), str(client.client_id)),
        )
        if not row:
            return None
        code = AuthorizationCode.model_validate_json(row["code_json"])
        return code if code.expires_at >= time.time() else None

    def _issue_tokens(self, client_id: str, project_id: str, scopes: list[str]) -> OAuthToken:
        access_token = secrets.token_urlsafe(36)
        refresh_token = secrets.token_urlsafe(40)
        now = int(time.time())
        self.services.execute(
            """insert into mcp_oauth_tokens
               (access_hash, refresh_hash, client_id, project_id, scopes, access_expires_at, refresh_expires_at, created_at)
               values (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                hash_secret(access_token), hash_secret(refresh_token), client_id, project_id, json.dumps(scopes),
                now + ACCESS_TOKEN_SECONDS, now + REFRESH_TOKEN_SECONDS, self.services.utc_now(),
            ),
        )
        return OAuthToken(
            access_token=access_token, token_type="Bearer", expires_in=ACCESS_TOKEN_SECONDS,
            refresh_token=refresh_token, scope=" ".join(scopes),
        )

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode) -> OAuthToken:
        row = self.services.query_one(
            "select * from mcp_oauth_codes where code_hash = ? and client_id = ? and used_at is null",
            (hash_secret(authorization_code.code), str(client.client_id)),
        )
        if not row:
            raise ValueError("Authorization code is invalid or already used.")
        self.services.execute("update mcp_oauth_codes set used_at = ? where code_hash = ?", (self.services.utc_now(), hash_secret(authorization_code.code)))
        return self._issue_tokens(str(client.client_id), row["project_id"], authorization_code.scopes)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        row = self.services.query_one(
            "select * from mcp_oauth_tokens where refresh_hash = ? and client_id = ? and revoked_at is null",
            (hash_secret(refresh_token), str(client.client_id)),
        )
        if not row or int(row["refresh_expires_at"]) < int(time.time()):
            return None
        return RefreshToken(
            token=refresh_token, client_id=row["client_id"], scopes=json.loads(row["scopes"]),
            expires_at=int(row["refresh_expires_at"]), subject=row["project_id"],
        )

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        self.services.execute("update mcp_oauth_tokens set revoked_at = ? where refresh_hash = ?", (self.services.utc_now(), hash_secret(refresh_token.token)))
        requested = [scope for scope in scopes if scope in refresh_token.scopes] if scopes else refresh_token.scopes
        return self._issue_tokens(str(client.client_id), str(refresh_token.subject), requested)

    async def load_access_token(self, token: str) -> AccessToken | None:
        row = self.services.query_one(
            "select * from mcp_oauth_tokens where access_hash = ? and revoked_at is null", (hash_secret(token),),
        )
        if not row or int(row["access_expires_at"]) < int(time.time()):
            return None
        return AccessToken(
            token=token, client_id=row["client_id"], scopes=json.loads(row["scopes"]),
            expires_at=int(row["access_expires_at"]), resource=f"{self.public_base_url}/mcp", subject=row["project_id"],
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        token_hash = hash_secret(token.token)
        self.services.execute(
            "update mcp_oauth_tokens set revoked_at = ? where access_hash = ? or refresh_hash = ?",
            (self.services.utc_now(), token_hash, token_hash),
        )


def create_mcp_runtime(services: DeveloperServices, public_base_url: str) -> McpRuntime:
    base = public_base_url.rstrip("/")
    provider = NeuroAdOAuthProvider(services, base)
    mcp = FastMCP(
        "NeuroAd Context Engine",
        instructions=(
            "Use NeuroAd to inspect evidence-grounded video verdicts, create improvement plans, and compare revisions. "
            "Never claim a recommendation was applied unless the destination tool confirms it."
        ),
        website_url=base,
        auth_server_provider=provider,
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(base), resource_server_url=AnyHttpUrl(f"{base}/mcp"),
            required_scopes=["analysis:read"],
            client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=MCP_SCOPES, default_scopes=MCP_SCOPES),
            revocation_options=RevocationOptions(enabled=True),
        ),
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )

    def current_project_id(required_scope: str = "analysis:read") -> str:
        token = get_access_token()
        if not token or not token.subject:
            raise ValueError("Authenticated NeuroAd project context is unavailable.")
        if required_scope not in token.scopes:
            raise ValueError(f"The MCP grant lacks the {required_scope} scope.")
        return str(token.subject)

    def owned_video(video_id: str) -> Any:
        row = services.query_one("select * from videos where id = ? and project_id = ?", (video_id, current_project_id()))
        if not row:
            raise ValueError("Video not found in the authenticated project.")
        return row

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
    def list_videos(limit: int = 20) -> dict[str, Any]:
        """List the authenticated project's most recent videos and analysis states."""
        safe_limit = max(1, min(50, limit))
        rows = services.query_all(
            "select id, title, status, duration_seconds, created_at from videos where project_id = ? order by created_at desc limit ?",
            (current_project_id(), safe_limit),
        )
        return {"videos": [dict(row) for row in rows]}

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
    def get_video_verdict(video_id: str) -> dict[str, Any]:
        """Return a completed video's verdict, recommendations, and evidence-linked segment timeline."""
        video = owned_video(video_id)
        if video["status"] != "completed":
            return {"video_id": video_id, "status": video["status"], "message": "Analysis is not complete."}
        payload = services.build_analysis_payload(video)
        return {
            "video": payload["video"], "summary": payload["summary"],
            "recommendations": payload["recommendations"], "segments": payload["segments"],
            "limitations": ["Attention scores are decision-support proxies, not guaranteed viewer behavior."],
        }

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
    def create_improvement_plan(video_id: str, objective: str = "balanced", custom_instruction: str | None = None, target_provider: str | None = None) -> dict[str, Any]:
        """Create an evidence-grounded, non-destructive edit plan for another video tool."""
        allowed = {"balanced", "attention", "drop_risk", "ad_fit", "brand_safety", "short_form"}
        if objective not in allowed:
            raise ValueError(f"Objective must be one of: {', '.join(sorted(allowed))}.")
        video = owned_video(video_id)
        if video["status"] != "completed":
            raise ValueError("Complete analysis before creating an improvement plan.")
        return build_improvement_plan(services.build_analysis_payload(video), objective, custom_instruction, target_provider)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
    def get_comparison_verdict(comparison_id: str) -> dict[str, Any]:
        """Return a completed comparison owned by the authenticated project."""
        row = services.query_one("select * from comparisons where id = ? and project_id = ?", (comparison_id, current_project_id()))
        if not row:
            raise ValueError("Comparison not found in the authenticated project.")
        return services.build_comparison_payload(row)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
    def request_analysis_approval(video_id: str, plan_fingerprint: str) -> dict[str, Any]:
        """Create a short-lived NeuroAd approval link before starting a potentially billable analysis."""
        owned_video(video_id)
        approval_id = f"approval_{secrets.token_urlsafe(24)}"
        expires = int(time.time()) + APPROVAL_SECONDS
        services.execute(
            """insert into mcp_approvals
               (id, project_id, action, target_id, plan_fingerprint, status, expires_at, created_at)
               values (?, ?, 'start_analysis', ?, ?, 'pending', ?, ?)""",
            (approval_id, current_project_id(), video_id, plan_fingerprint, str(expires), services.utc_now()),
        )
        return {
            "approval_id": approval_id, "status": "pending", "expires_at": expires,
            "approval_url": f"{base}/mcp/approvals/{approval_id}",
            "message": "Open the approval URL and review the action before execution.",
        }

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
    def start_approved_analysis(video_id: str, approval_id: str, plan_fingerprint: str) -> dict[str, Any]:
        """Start analysis only after NeuroAd approval for this exact project, video, and plan."""
        current_project_id("analysis:write")
        owned_video(video_id)
        approval = services.query_one(
            """select * from mcp_approvals where id = ? and project_id = ? and target_id = ?
               and plan_fingerprint = ?""",
            (approval_id, current_project_id(), video_id, plan_fingerprint),
        )
        if not approval or approval["status"] not in {"approved", "consumed"} or int(approval["expires_at"]) < int(time.time()):
            raise ValueError("Approval is missing, expired, or does not match this plan.")
        if approval["status"] == "consumed":
            job = services.query_one("select * from jobs where video_id = ? order by created_at desc limit 1", (video_id,))
            return {"job_id": job["id"] if job else None, "status": job["status"] if job else "unknown", "idempotent_replay": True}
        result = services.create_video_analysis_job(video_id)
        services.execute(
            "update mcp_approvals set status = 'consumed', consumed_at = ? where id = ?",
            (services.utc_now(), approval_id),
        )
        return {**result, "approval_id": approval_id, "idempotent_replay": False}

    @mcp.resource("neuroad://videos/{video_id}/verdict")
    def verdict_resource(video_id: str) -> str:
        """Evidence-grounded verdict for a project video."""
        return json.dumps(get_video_verdict(video_id), indent=2)

    @mcp.prompt()
    def improve_before_publishing(video_id: str, objective: str = "balanced") -> str:
        """Guide Claude through an evidence-led improvement and re-analysis workflow."""
        return (
            f"Retrieve the NeuroAd verdict for video {video_id}, then create an improvement plan optimized for {objective}. "
            "Explain each recommendation with its timestamp and evidence. Use a separately connected video tool when available. "
            "Do not claim any edit was applied until that tool confirms it, preserve the original, and submit the resulting revision "
            "to NeuroAd for a before/after analysis before recommending publication."
        )

    @mcp.custom_route("/mcp/consent", methods=["GET", "POST"])
    async def consent(request: Request) -> Response:
        request_id = request.query_params.get("request_id", "")
        error = ""
        if request.method == "POST":
            form = await request.form()
            request_id = str(form.get("request_id", ""))
            try:
                redirect_url = await provider.complete_authorization(request_id, str(form.get("api_key", "")))
                return RedirectResponse(redirect_url, status_code=303)
            except Exception as exc:
                error = html.escape(str(exc))
        body = f"""<!doctype html><html><body style='font-family:system-ui;max-width:560px;margin:64px auto;padding:24px'>
        <h1>Connect Claude to NeuroAd</h1><p>Enter a project API key to grant Claude access to that project's video verdicts and analysis tools.</p>
        {f"<p style='color:#b91c1c'>{error}</p>" if error else ""}
        <form method='post'><input type='hidden' name='request_id' value='{html.escape(request_id)}'>
        <label>NeuroAd API key<br><input type='password' name='api_key' required autocomplete='off' style='width:100%;padding:10px;margin-top:8px'></label>
        <button type='submit' style='margin-top:18px;padding:10px 18px'>Authorize</button></form>
        <p style='color:#666;font-size:13px'>Claude receives scoped tokens, never the API key entered here.</p></body></html>"""
        return HTMLResponse(body, status_code=400 if error else 200)

    @mcp.custom_route("/mcp/approvals/{approval_id}", methods=["GET", "POST"])
    async def approval(request: Request) -> Response:
        approval_id = request.path_params["approval_id"]
        row = services.query_one("select * from mcp_approvals where id = ?", (approval_id,))
        if not row or int(row["expires_at"]) < int(time.time()):
            return HTMLResponse("<h1>Approval expired or unavailable</h1>", status_code=404)
        if request.method == "POST" and row["status"] == "pending":
            services.execute("update mcp_approvals set status = 'approved' where id = ?", (approval_id,))
            row = services.query_one("select * from mcp_approvals where id = ?", (approval_id,))
        body = f"""<!doctype html><html><body style='font-family:system-ui;max-width:560px;margin:64px auto;padding:24px'>
        <h1>NeuroAd action approval</h1><p><b>Action:</b> {html.escape(row['action'])}</p>
        <p><b>Video:</b> {html.escape(row['target_id'])}</p><p><b>Status:</b> {html.escape(row['status'])}</p>
        {"<form method='post'><button type='submit' style='padding:10px 18px'>Approve this action</button></form>" if row['status'] == 'pending' else "<p>You can return to Claude.</p>"}
        </body></html>"""
        return HTMLResponse(body)

    mcp_app = mcp.streamable_http_app()
    return McpRuntime(mcp=mcp, app=mcp_app)
