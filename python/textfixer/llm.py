"""LLM client: OpenAI-compatible servers (incl. this app's own local server), Gemini and Ollama."""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from typing import Callable

from .config import Config

Messages = list[dict[str, str]]  # [{"role": "user" | "assistant", "content": text}]


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    # -- request building ----------------------------------------------
    @property
    def provider(self) -> str:
        return self.cfg.provider

    def endpoint(self) -> str:
        url = self.cfg.setting("API_URL")
        if url:
            return url
        model = self.cfg.setting("MODEL")
        if self.provider == "gemini":
            return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        if self.provider == "ollama":
            return "http://localhost:11434/api/chat"
        if self.provider == "local":
            host = self.cfg.server("HOST")
            host = "127.0.0.1" if host in ("", "0.0.0.0") else host
            return f"http://{host}:{self.cfg.server('PORT')}/v1/chat/completions"
        raise LLMError("API_URL is not set in config.ini")

    def headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        key = self.cfg.setting("API_KEY")
        if self.provider == "local" and not key:
            key = self.cfg.server("API_KEY")
        if key:
            if self.provider == "gemini":
                headers["x-goog-api-key"] = key
            else:
                headers["Authorization"] = f"Bearer {key}"
        return headers

    def body(self, messages: Messages, system: str = "") -> dict:
        temperature = self.cfg.number("Settings", "TEMPERATURE", 0.2)
        model = self.cfg.setting("MODEL")
        if self.provider == "gemini":
            body: dict = {
                "contents": [{"role": "model" if m["role"] == "assistant" else "user",
                              "parts": [{"text": m["content"]}]} for m in messages],
                "generationConfig": {"temperature": temperature},
            }
            if system:
                body["system_instruction"] = {"parts": [{"text": system}]}
            return body
        chat = ([{"role": "system", "content": system}] if system else []) + [dict(m) for m in messages]
        if self.provider == "ollama":
            return {"model": model, "messages": chat, "stream": False, "options": {"temperature": temperature}}
        return {"model": model, "messages": chat, "temperature": temperature, "stream": False}

    @staticmethod
    def extract(provider: str, data: dict) -> str:
        try:
            if provider == "gemini":
                text = data["candidates"][0]["content"]["parts"][0]["text"]
            elif provider == "ollama":
                text = data["message"]["content"]
            else:
                text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected response: {json.dumps(data)[:500]}") from exc
        # Drop reasoning blocks some models emit before the answer
        return re.sub(r"(?s)^\s*<think>.*?</think>\s*", "", text or "")

    # -- calling --------------------------------------------------------
    def complete(self, messages: Messages, system: str = "") -> str:
        """Blocking request; returns the answer text or raises LLMError."""
        request = urllib.request.Request(
            self.endpoint(), data=json.dumps(self.body(messages, system)).encode("utf-8"),
            headers=self.headers(), method="POST")
        timeout = self.cfg.number("Settings", "TIMEOUT", 120)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise LLMError(f"HTTP {exc.code}\n{detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LLMError(f"Cannot reach the server at {request.full_url}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise LLMError("The server did not return JSON") from exc
        return self.extract(self.provider, data)

    def complete_async(self, messages: Messages, system: str, done: Callable[[str | None, Exception | None], None]
                       ) -> threading.Thread:
        """Run complete() in a thread; done(text, None) or done(None, error) is called from that thread."""
        def run():
            try:
                text = self.complete(messages, system)
            except Exception as exc:
                done(None, exc)
            else:
                done(text, None)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread
