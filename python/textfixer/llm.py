"""LLM client: Ollama (default), OpenAI-compatible servers and Gemini."""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from typing import Callable, Iterator
from urllib.parse import urlsplit

from .config import Config

Messages = list[dict[str, str]]  # [{"role": "user" | "assistant", "content": text}]


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._send_think = True  # cleared if Ollama rejects the "think" option (older Ollama / model)

    @property
    def provider(self) -> str:
        return self.cfg.provider

    # -- addresses --------------------------------------------------------------
    def ollama_base(self) -> str:
        """http://host:port of the Ollama server (API_URL may also point to /api/chat)."""
        url = self.cfg.setting("API_URL") or "http://localhost:11434"
        parts = urlsplit(url if "//" in url else "http://" + url)
        return f"{parts.scheme}://{parts.netloc}"

    def endpoint(self) -> str:
        url = self.cfg.setting("API_URL")
        model = self.cfg.setting("MODEL")
        if self.provider == "gemini":
            return url or f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        if self.provider == "ollama":
            return self.ollama_base() + "/api/chat"
        if not url:
            raise LLMError("API_URL is not set in config.ini")
        return url

    def headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        key = self.cfg.setting("API_KEY")
        if key:
            if self.provider == "gemini":
                headers["x-goog-api-key"] = key
            else:
                headers["Authorization"] = f"Bearer {key}"
        return headers

    # -- request bodies -----------------------------------------------------------
    def body(self, messages: Messages, system: str = "") -> dict:
        temperature = self.cfg.number("TEMPERATURE", 0.2)
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
            body = {"model": model, "messages": chat, "stream": False, "options": {"temperature": temperature}}
            if self.cfg.setting("KEEP_ALIVE"):
                body["keep_alive"] = self.cfg.setting("KEEP_ALIVE")
            if self._send_think and self.cfg.setting("THINK").lower() in ("off", "false", "no", "0"):
                body["think"] = False  # thinking models answer straight away
            return body
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

    # -- calling ------------------------------------------------------------------
    def _open(self, request: urllib.request.Request, timeout: float):
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            if self.provider == "ollama" and exc.code == 404:
                model = self.cfg.setting("MODEL")
                raise LLMError(f"Ollama does not have the model '{model}'. Download it in Settings "
                               f"(Download model), or run:  ollama pull {model}") from exc
            raise LLMError(f"HTTP {exc.code}\n{detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            hint = "\nIs Ollama running? Start it from the Start menu, then try again." if self.provider == "ollama" else ""
            raise LLMError(f"Cannot reach the server at {request.full_url}: {exc}{hint}") from exc

    def complete(self, messages: Messages, system: str = "") -> str:
        """Blocking request; returns the answer text or raises LLMError."""
        try:
            return self._complete(messages, system)
        except LLMError as exc:
            text = str(exc).lower()
            if self.provider == "ollama" and self._send_think and text.startswith("http 400") and "think" in text:
                self._send_think = False  # this model/Ollama does not take the option: ask without it
                return self._complete(messages, system)
            raise

    def _complete(self, messages: Messages, system: str) -> str:
        request = urllib.request.Request(
            self.endpoint(), data=json.dumps(self.body(messages, system)).encode("utf-8"),
            headers=self.headers(), method="POST")
        with self._open(request, self.cfg.number("TIMEOUT", 120)) as response:
            try:
                data = json.loads(response.read().decode("utf-8"))
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

    # -- Ollama helpers -------------------------------------------------------------
    def list_models(self) -> list[str]:
        """Names of the models installed in Ollama (e.g. "llama3.2:latest")."""
        request = urllib.request.Request(self.ollama_base() + "/api/tags")
        with self._open(request, 5) as response:
            data = json.loads(response.read().decode("utf-8"))
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]

    def has_model(self, name: str) -> bool:
        installed = self.list_models()
        return name in installed or (":" not in name and f"{name}:latest" in installed)

    def pull_model(self, name: str) -> Iterator[tuple[str, float | None]]:
        """Download a model. Yields (status text, fraction 0..1 or None) as it goes."""
        request = urllib.request.Request(
            self.ollama_base() + "/api/pull", data=json.dumps({"model": name, "stream": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with self._open(request, 3600) as response:
            for raw in response:
                if not raw.strip():
                    continue
                event = json.loads(raw.decode("utf-8"))
                if event.get("error"):
                    raise LLMError(event["error"])
                total, done = event.get("total"), event.get("completed")
                yield event.get("status", ""), (done / total if total and done is not None else None)
