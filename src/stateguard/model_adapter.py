"""Shared adapter for the UCSD model API."""

import json
import os
from time import perf_counter

from openai import OpenAI


class ModelAdapter:
    def __init__(self):
        self.model = os.getenv(
            "STATEGUARD_MODEL", "api-glm-5.3-flash"
        )
        self.client = OpenAI(
            base_url=os.environ["OPENAI_BASE_URL"],
            api_key=os.environ["OPENAI_API_KEY"],
            timeout=60,
            max_retries=0,
        )

    def generate_json(self, system_prompt, input_data):
        messages = [
            {
                "role": "system",
                "content": system_prompt
                + "\nReturn only a JSON object, without Markdown.",
            },
            {
                "role": "user",
                "content": json.dumps(input_data),
            },
        ]

        started = perf_counter()
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
        )
        latency_ms = (perf_counter() - started) * 1000

        raw = response.choices[0].message.content
        parsed = None
        error = None

        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("Expected a JSON object")
        except (TypeError, ValueError) as exc:
            parsed = None
            error = str(exc)

        return {
            "model": self.model,
            "messages": messages,
            "raw_response": raw,
            "parsed": parsed,
            "error": error,
            "latency_ms": latency_ms,
            "usage": (
                response.usage.model_dump()
                if response.usage is not None
                else None
            ),
        }