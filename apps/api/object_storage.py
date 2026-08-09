from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
import os
from pathlib import Path
from typing import Any

R2_URI_PREFIX = "r2://"


@dataclass(frozen=True)
class ObjectStorageSettings:
    backend: str
    bucket: str | None
    endpoint_url: str | None
    access_key_id: str | None
    secret_access_key: str | None
    region: str
    presign_ttl_seconds: int

    @classmethod
    def from_env(cls) -> "ObjectStorageSettings":
        backend = os.getenv("NEUROAD_OBJECT_STORAGE", "local").strip().lower()
        account_id = os.getenv("R2_ACCOUNT_ID", "").strip()
        endpoint_url = os.getenv("R2_ENDPOINT_URL", "").strip() or (f"https://{account_id}.r2.cloudflarestorage.com" if account_id else "")
        return cls(
            backend=backend,
            bucket=os.getenv("R2_BUCKET", "").strip() or None,
            endpoint_url=endpoint_url or None,
            access_key_id=os.getenv("R2_ACCESS_KEY_ID", "").strip() or None,
            secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY", "").strip() or None,
            region=os.getenv("R2_REGION", "auto").strip() or "auto",
            presign_ttl_seconds=max(60, int(os.getenv("R2_PRESIGN_TTL_SECONDS", "900"))),
        )

    @property
    def enabled(self) -> bool:
        return self.backend == "r2"

    @property
    def missing_fields(self) -> list[str]:
        return [name for name, value in {
            "R2_BUCKET": self.bucket,
            "R2_ENDPOINT_URL or R2_ACCOUNT_ID": self.endpoint_url,
            "R2_ACCESS_KEY_ID": self.access_key_id,
            "R2_SECRET_ACCESS_KEY": self.secret_access_key,
        }.items() if not value]


class ObjectStorage:
    def __init__(self, settings: ObjectStorageSettings | None = None):
        self.settings = settings or ObjectStorageSettings.from_env()

    @property
    def enabled(self) -> bool:
        return self.settings.enabled

    @property
    def ready(self) -> bool:
        return self.enabled and not self.settings.missing_fields

    @cached_property
    def client(self) -> Any:
        self.require_ready()
        import boto3
        return boto3.client("s3", endpoint_url=self.settings.endpoint_url, aws_access_key_id=self.settings.access_key_id, aws_secret_access_key=self.settings.secret_access_key, region_name=self.settings.region)

    def require_ready(self) -> None:
        if not self.enabled:
            raise RuntimeError("Object storage is disabled. Set NEUROAD_OBJECT_STORAGE=r2 to enable direct uploads.")
        if self.settings.missing_fields:
            raise RuntimeError(f"R2 object storage is missing: {', '.join(self.settings.missing_fields)}.")

    def uri(self, key: str) -> str:
        self.require_ready()
        return f"{R2_URI_PREFIX}{self.settings.bucket}/{normalize_key(key)}"

    def key_from_uri(self, value: str) -> str | None:
        if not value.startswith(R2_URI_PREFIX):
            return None
        try:
            bucket, key = value[len(R2_URI_PREFIX):].split("/", 1)
        except ValueError:
            return None
        return normalize_key(key) if bucket == self.settings.bucket else None

    def presign_put(self, key: str, content_type: str) -> str:
        return self.client.generate_presigned_url("put_object", Params={"Bucket": self.settings.bucket, "Key": normalize_key(key), "ContentType": content_type}, ExpiresIn=self.settings.presign_ttl_seconds, HttpMethod="PUT")

    def presign_get(self, key: str) -> str:
        return self.client.generate_presigned_url("get_object", Params={"Bucket": self.settings.bucket, "Key": normalize_key(key)}, ExpiresIn=self.settings.presign_ttl_seconds, HttpMethod="GET")

    def head(self, key: str) -> dict[str, Any]:
        return self.client.head_object(Bucket=self.settings.bucket, Key=normalize_key(key))

    def download_file(self, key: str, target: Path) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.settings.bucket, normalize_key(key), str(target))
        return target

    def upload_file(self, source: Path, key: str, content_type: str | None = None) -> None:
        self.client.upload_file(str(source), self.settings.bucket, normalize_key(key), ExtraArgs={"ContentType": content_type} if content_type else None)


def normalize_key(key: str) -> str:
    normalized = key.strip().lstrip("/")
    if not normalized or normalized.startswith("../") or "/../" in normalized or "\\" in normalized:
        raise ValueError("Invalid object storage key.")
    return normalized


def content_type_for_suffix(suffix: str) -> str:
    return {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".m4v": "video/x-m4v", ".jpg": "image/jpeg", ".json": "application/json", ".csv": "text/csv"}.get(suffix.lower(), "application/octet-stream")
