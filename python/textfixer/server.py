"""OpenAI-compatible API server (chat completions, streaming and not) for a Backend."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import uuid
from typing import Any

import uvicorn
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from .backend import Backend, GenParams, PromptTooLong

log = logging.getLogger("textfixer.server")


class Message(BaseModel):
    role: str
    content: Any = ""


class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[Message]
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    max_completion_tokens: int | None = None
    stream: bool = False
    stop: str | list[str] | None = None


def _text(content: Any) -> str:
    """Message content can be a string or a list of {"type": "text", "text": ...} parts."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return str(content)


def _error(status: int, message: str, kind: str = "invalid_request_error") -> JSONResponse:
    return JSONResponse({"error": {"message": message, "type": kind}}, status_code=status)


def create_app(backend: Backend, api_key: str = "", default_max_new_tokens: int = 1024) -> FastAPI:
    app = FastAPI(title="TextFixer local LLM server")

    def authorized(authorization: str | None) -> bool:
        return not api_key or authorization == f"Bearer {api_key}"

    @app.get("/health")
    def health():
        return {"status": "ok", "device": backend.device, "model": backend.model_name}

    @app.get("/v1/models")
    def models(authorization: str | None = Header(default=None)):
        if not authorized(authorization):
            return _error(401, "Invalid API key", "authentication_error")
        return {"object": "list", "data": [{"id": backend.model_name, "object": "model", "owned_by": "local"}]}

    @app.post("/v1/chat/completions")
    def chat(req: ChatRequest, authorization: str | None = Header(default=None)):
        if not authorized(authorization):
            return _error(401, "Invalid API key", "authentication_error")
        messages = []
        for m in req.messages:
            role = m.role if m.role in ("system", "user", "assistant") else ("system" if m.role == "developer" else "user")
            messages.append({"role": role, "content": _text(m.content)})
        if not messages:
            return _error(400, "messages must not be empty")

        stop = [req.stop] if isinstance(req.stop, str) else list(req.stop or [])
        params = GenParams(
            max_new_tokens=req.max_completion_tokens or req.max_tokens or default_max_new_tokens,
            temperature=req.temperature if req.temperature is not None else 0.0,
            top_p=req.top_p if req.top_p is not None else 1.0,
            stop=stop,
        )
        model = req.model or backend.model_name
        completion_id = "chatcmpl-" + uuid.uuid4().hex[:24]
        created = int(time.time())

        if backend.max_prompt_tokens:  # fail fast with a clear message instead of in the middle of a stream
            try:
                n = backend.count_tokens(messages)
            except Exception:
                n = 0
            if n > backend.max_prompt_tokens:
                return _error(400, f"Prompt too long for the NPU model ({n} tokens, limit {backend.max_prompt_tokens}). "
                                   "Raise MAX_PROMPT_LEN in [Server] or send less text.")

        if not req.stream:
            try:
                result = backend.generate(messages, params)
            except PromptTooLong as exc:
                return _error(400, str(exc))
            except Exception as exc:
                log.exception("generation failed")
                return _error(500, f"Generation failed: {exc}", "server_error")
            return {
                "id": completion_id, "object": "chat.completion", "created": created, "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": result.text},
                             "finish_reason": result.finish_reason}],
                "usage": {"prompt_tokens": result.prompt_tokens, "completion_tokens": result.completion_tokens,
                          "total_tokens": result.prompt_tokens + result.completion_tokens},
            }

        def chunk(delta: dict, finish: str | None = None) -> str:
            data = {"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": model,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            return f"data: {json.dumps(data)}\n\n"

        events: queue.Queue = queue.Queue()
        stop_flag = threading.Event()

        def worker():
            try:
                result = backend.generate(messages, params, lambda piece: (events.put(("tok", piece)), stop_flag.is_set())[1])
                events.put(("done", result))
            except Exception as exc:
                log.exception("generation failed")
                events.put(("err", exc))

        threading.Thread(target=worker, daemon=True).start()

        def stream():
            try:
                yield chunk({"role": "assistant", "content": ""})
                while True:
                    kind, value = events.get()
                    if kind == "tok":
                        yield chunk({"content": value})
                    elif kind == "done":
                        yield chunk({}, value.finish_reason)
                        break
                    else:
                        yield f"data: {json.dumps({'error': {'message': str(value), 'type': 'server_error'}})}\n\n"
                        break
                yield "data: [DONE]\n\n"
            finally:
                stop_flag.set()  # client went away: stop generating

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app


class ServerThread:
    """Runs the API server in a background thread (used by the desktop app)."""

    def __init__(self, backend: Backend, host: str, port: int, api_key: str = "", default_max_new_tokens: int = 1024):
        config = uvicorn.Config(create_app(backend, api_key, default_max_new_tokens), host=host, port=port,
                                log_level="warning")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True, name="api-server")

    def start(self, wait: float = 10.0) -> None:
        self.thread.start()
        deadline = time.time() + wait
        while not self.server.started and time.time() < deadline and self.thread.is_alive():
            time.sleep(0.05)

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


def serve(backend: Backend, host: str, port: int, api_key: str = "", default_max_new_tokens: int = 1024) -> None:
    uvicorn.run(create_app(backend, api_key, default_max_new_tokens), host=host, port=port, log_level="info")
