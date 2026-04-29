from __future__ import annotations

import base64
from typing import Any

from openai import OpenAI


class OpenAICompatClient:
    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str | None,
        timeout: float = 180.0,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("缺少 API 密钥：请在 .env 中设置 VLM_API_KEY（见 .env.example）")
        kw: dict[str, Any] = {"api_key": api_key, "base_url": base_url, "timeout": timeout}
        if default_headers:
            kw["default_headers"] = default_headers
        self._client = OpenAI(**kw)

    def chat_vision(
        self,
        *,
        model: str,
        system: str,
        user_text: str,
        image_bytes: bytes,
        content_type: str = "image/png",
        temperature: float = 0.1,
        timeout: float = 300.0,
        response_format_json: bool = False,
    ) -> str:
        b64 = base64.standard_b64encode(image_bytes).decode("ascii")
        data_url = f"data:{content_type};base64,{b64}"
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ]
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "timeout": timeout,
        }
        if response_format_json:
            try:
                kwargs2 = {**kwargs, "response_format": {"type": "json_object"}}
                resp = self._client.chat.completions.create(**kwargs2)
            except (TypeError, Exception):
                resp = self._client.chat.completions.create(**kwargs)
        else:
            resp = self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0].message
        return (choice.content or "").strip()
