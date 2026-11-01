"""OpenAI-compatible API adapter. Credentials are never written to traces."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from importlib.metadata import PackageNotFoundError, version
from random import uniform
from time import monotonic, perf_counter, sleep
from typing import Any


def _retry_after_seconds(exc: Exception) -> float | None:
    """Read a safe delay from a provider 429 without logging response headers."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    value = headers.get("retry-after") if headers is not None else None
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        try:
            when = parsedate_to_datetime(str(value))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


class ModelAdapter:
    def __init__(self, *, model: str | None = None, max_attempts: int = 1,
                 timeout: float = 60, temperature: float | None = None,
                 request_interval_seconds: float = 0, client: Any = None):
        if not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts must be between 1 and 3")
        if request_interval_seconds < 0:
            raise ValueError("request_interval_seconds must be nonnegative")
        self.model = model or os.getenv("STATEGUARD_MODEL", "api-glm-5.3-flash")
        self.max_attempts = max_attempts
        self.timeout = timeout
        self.temperature = temperature
        self.request_interval_seconds = request_interval_seconds
        self._next_request_at = 0.0
        if client is None:
            from openai import OpenAI
            client = OpenAI(
                base_url=os.environ["OPENAI_BASE_URL"],
                api_key=os.environ["OPENAI_API_KEY"],
                timeout=timeout, max_retries=0,
            )
        self.client = client
        try:
            self.sdk_version = version("openai")
        except PackageNotFoundError:
            self.sdk_version = "not-installed-test-client"

    def generate_json(self, system_prompt: str, input_data: dict[str, Any]) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": system_prompt +
             "\nReturn only a JSON object, without Markdown."},
            {"role": "user", "content": json.dumps(input_data, ensure_ascii=False)},
        ]
        parameters = {"model": self.model, "messages": messages}
        if self.temperature is not None:
            parameters["temperature"] = self.temperature
        attempts = []
        started = perf_counter()
        for number in range(1, self.max_attempts + 1):
            call_started = perf_counter()
            record = {"attempt": number, "raw_response": None, "parsed": None,
                      "usage": None, "error": None, "status": "error"}
            wait_seconds = max(0.0, self._next_request_at - monotonic())
            if wait_seconds:
                sleep(wait_seconds)
            self._next_request_at = monotonic() + self.request_interval_seconds
            record["request_wait_seconds"] = wait_seconds
            try:
                response = self.client.chat.completions.create(**parameters)
                record["response_id"] = getattr(response, "id", None)
                record["response_model"] = getattr(response, "model", None)
                record["system_fingerprint"] = getattr(response, "system_fingerprint", None)
                record["usage"] = response.usage.model_dump() if response.usage else None
                choice = response.choices[0]
                record["finish_reason"] = choice.finish_reason
                record["raw_response"] = choice.message.content
                parsed = json.loads(choice.message.content)
                if not isinstance(parsed, dict):
                    raise ValueError("Expected a JSON object")
                if choice.finish_reason != "stop":
                    raise ValueError("Response did not finish normally")
                record.update(parsed=parsed, status="ok")
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                record["error"] = f"Output parse error: {type(exc).__name__}"
            except Exception as exc:
                name = type(exc).__name__
                record["status"] = "timeout" if "timeout" in name.lower() else "error"
                # Exception text/headers can contain credentials; keep only safe identifiers.
                record["error"] = f"API request failed: {name}"
                record["http_status"] = getattr(exc, "status_code", None)
                if record["http_status"] == 429:
                    record["retry_after_seconds"] = _retry_after_seconds(exc)
            record["latency_ms"] = (perf_counter() - call_started) * 1000
            attempts.append(record)
            status_code = record.get("http_status")
            if record["status"] == "ok" or status_code in (400, 401, 403, 404, 405, 422):
                break
            if number < self.max_attempts:
                if status_code == 429:
                    retry_after = record.get("retry_after_seconds")
                    if retry_after is not None and retry_after > 120:
                        record["retry_deferred"] = True
                        break
                    delay = (retry_after if retry_after is not None else
                             min(60.0, 15.0 * 2 ** (number - 1) + uniform(0, 1)))
                elif status_code is not None and status_code >= 500:
                    delay = min(10.0, 2 ** (number - 1) + uniform(0, 1))
                elif record["status"] == "timeout":
                    delay = min(10.0, 2 ** (number - 1) + uniform(0, 1))
                else:
                    delay = 0.0
                record["backoff_seconds"] = delay
                if delay:
                    sleep(delay)

        final = attempts[-1]
        # Aggregate costs over EVERY attempt, including malformed-output attempts.
        usage_records = [a["usage"] for a in attempts if a["usage"] is not None]
        usage = None
        if usage_records:
            usage = {}
            for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                values = [u.get(field) for u in usage_records]
                usage[field] = sum(v for v in values if type(v) is int) if any(type(v) is int for v in values) else None
            reasoning = [(u.get("completion_tokens_details") or {}).get("reasoning_tokens")
                         for u in usage_records]
            usage["completion_tokens_details"] = {
                "reasoning_tokens": sum(v for v in reasoning if type(v) is int)
                if any(type(v) is int for v in reasoning) else None,
            }
        return {
            "model": self.model,
            "prompt_version": "stateguard-llm-v2",
            "sdk_version": self.sdk_version,
            "parameters": {"timeout_seconds": self.timeout, "sdk_max_retries": 0,
                           "max_attempts": self.max_attempts, "temperature": self.temperature,
                           "request_interval_seconds": self.request_interval_seconds,
                           "provider_seed_sent": False},
            "messages": messages,
            "raw_response": final["raw_response"],
            "parsed": final["parsed"],
            "error": final["error"],
            "status": final["status"],
            "usage": usage,
            "attempts": attempts,
            "retry_count": len(attempts) - 1,
            "latency_ms": (perf_counter() - started) * 1000,
        }
