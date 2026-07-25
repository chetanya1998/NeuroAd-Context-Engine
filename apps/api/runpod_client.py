from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx


class RunPodError(RuntimeError):
    """A safe-to-log error raised by the RunPod integration."""


def _int_from_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float_from_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class RunPodSettings:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float
    max_tokens: int
    max_retries: int

    @classmethod
    def from_env(cls) -> "RunPodSettings":
        endpoint_id = os.getenv("RUNPOD_ENDPOINT_ID", "").strip()
        base_url = os.getenv("RUNPOD_BASE_URL", "").strip()
        if not base_url and endpoint_id:
            base_url = f"https://api.runpod.ai/v2/{endpoint_id}/openai/v1"
        return cls(
            api_key=os.getenv("RUNPOD_API_KEY", "").strip(),
            base_url=base_url.rstrip("/"),
            model=os.getenv("RUNPOD_MODEL", "neuroad-reasoner").strip() or "neuroad-reasoner",
            timeout_seconds=max(10.0, _float_from_env("RUNPOD_TIMEOUT_SECONDS", 300.0)),
            max_tokens=max(128, _int_from_env("RUNPOD_MAX_TOKENS", 2500)),
            max_retries=max(0, min(5, _int_from_env("RUNPOD_MAX_RETRIES", 2))),
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    def public_status(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "base_url_configured": bool(self.base_url),
            "api_key_configured": bool(self.api_key),
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
            "max_tokens": self.max_tokens,
        }


class RunPodClient:
    def __init__(self, settings: RunPodSettings | None = None) -> None:
        self.settings = settings or RunPodSettings.from_env()

    def chat_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        if not self.settings.configured:
            raise RunPodError("RunPod is not configured.")

        request_payload = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False, separators=(",", ":")),
                },
            ],
            "temperature": temperature,
            "max_tokens": self.settings.max_tokens,
        }
        # vLLM/OpenAI-compatible RunPod endpoints support this. If an older worker rejects it,
        # the request below retries once without the parameter instead of failing the job.
        use_json_mode = os.getenv("RUNPOD_JSON_RESPONSE_FORMAT", "1").lower() not in {"0", "false", "no", "off"}
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.settings.base_url}/chat/completions"
        last_error: Exception | None = None

        attempt = 0
        while attempt <= self.settings.max_retries:
            try:
                payload_for_attempt = dict(request_payload)
                messages = list(request_payload["messages"])
                if attempt:
                    messages.insert(1, {"role": "system", "content": "Your last response was not valid JSON. Return one compact, syntactically valid JSON object only; do not use markdown, comments, or trailing text."})
                payload_for_attempt["messages"] = messages
                if use_json_mode:
                    payload_for_attempt["response_format"] = {"type": "json_object"}
                with httpx.Client(timeout=self.settings.timeout_seconds) as client:
                    response = client.post(url, headers=headers, json=payload_for_attempt)
                if response.status_code == 429 or response.status_code >= 500:
                    raise RunPodError(f"RunPod temporarily unavailable (HTTP {response.status_code}).")
                if response.status_code >= 400:
                    response_text = getattr(response, "text", "").lower()
                    if response.status_code == 400 and use_json_mode and "response_format" in response_text:
                        use_json_mode = False
                        # JSON mode is optional on older vLLM workers; this fallback does not
                        # consume one of the limited model-generation retries.
                        continue
                    raise RunPodError(f"RunPod request rejected (HTTP {response.status_code}).")
                payload = response.json()
                content = payload["choices"][0]["message"].get("content")
                if not isinstance(content, str) or not content.strip():
                    raise RunPodError("RunPod returned an empty completion.")
                return parse_json_completion(content)
            except json.JSONDecodeError as exc:
                last_error = RunPodError(f"RunPod returned malformed JSON ({exc.msg} at line {exc.lineno}, column {exc.colno}).")
                if attempt >= self.settings.max_retries:
                    break
                attempt += 1
                time.sleep(min(4.0, 2.0**attempt))
            except (httpx.HTTPError, KeyError, TypeError, ValueError, RunPodError) as exc:
                last_error = exc
                if attempt >= self.settings.max_retries:
                    break
                attempt += 1
                time.sleep(min(4.0, 2.0**attempt))

        if isinstance(last_error, RunPodError):
            raise last_error
        raise RunPodError("RunPod request failed before a valid response was returned.") from last_error


def parse_json_completion(content: str) -> dict[str, Any]:
    value = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", value, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        value = fenced.group(1)
    elif not value.startswith("{"):
        start = value.find("{")
        end = value.rfind("}")
        if start >= 0 and end > start:
            value = value[start : end + 1]
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise RunPodError("RunPod completion was not a JSON object.")
    return payload
