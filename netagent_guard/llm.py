"""Minimal OpenAI-compatible chat client configured only through environment variables.

LLM_BASE_URL (e.g. https://openrouter.ai/api/v1), LLM_API_KEY, LLM_MODEL.
Any transport or HTTP error raises LLMUnavailable: callers must not silently fall back.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request


class LLMUnavailable(RuntimeError):
    pass


def config() -> dict:
    cfg = {k: os.getenv(k, "").strip() for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")}
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        raise LLMUnavailable(f"LLM endpoint not configured: set {', '.join(missing)}")
    return cfg


class Client:
    def __init__(self, transport=None, retries: int = 3):
        self.cfg = None if transport else config()
        self.transport = transport or self._http
        self.retries = retries
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}

    @property
    def model(self):
        return self.cfg["LLM_MODEL"] if self.cfg else "mock"

    def _http(self, body: dict) -> dict:
        req = urllib.request.Request(
            self.cfg["LLM_BASE_URL"].rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.cfg['LLM_API_KEY']}", "Content-Type": "application/json"})
        last = None
        for i in range(self.retries):
            try:
                with urllib.request.urlopen(req, timeout=90) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}: {e.read()[:300].decode(errors='replace')}"
                if e.code not in (429, 500, 502, 503, 504):
                    break
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = str(e)
            time.sleep(2 ** i)
        raise LLMUnavailable(f"LLM call failed: {last}")

    def chat(self, messages: list, schema: dict | None = None, temperature: float = 0.0, max_tokens: int = 500) -> str:
        body = {"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "out", "strict": True, "schema": schema}}
        out = self.transport(body)
        if "error" in out:
            raise LLMUnavailable(f"LLM error: {str(out['error'])[:300]}")
        u = out.get("usage") or {}
        self.usage["prompt_tokens"] += int(u.get("prompt_tokens", 0))
        self.usage["completion_tokens"] += int(u.get("completion_tokens", 0))
        self.usage["calls"] += 1
        try:
            return out["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise LLMUnavailable(f"malformed LLM response: {e}")


def parse_json(text: str):
    """Parse the first JSON object in text; None if there is none."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    i, j = (text or "").find("{"), (text or "").rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        return json.loads(text[i:j + 1])
    except json.JSONDecodeError:
        return None
