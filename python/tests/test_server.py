import json

from fastapi.testclient import TestClient

from textfixer.backend import EchoBackend
from textfixer.server import create_app


def client(**kw):
    return TestClient(create_app(EchoBackend("m"), **kw))


def test_models_and_health():
    c = client()
    assert c.get("/v1/models").json()["data"][0]["id"] == "m"
    assert c.get("/health").json()["status"] == "ok"


def test_chat_non_stream():
    r = client().post("/v1/chat/completions", json={
        "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "hello world"}]})
    body = r.json()
    assert r.status_code == 200
    assert body["choices"][0]["message"]["content"] == "ECHO: hello world"
    assert body["usage"]["completion_tokens"] == 3
    assert body["choices"][0]["finish_reason"] == "stop"


def test_content_parts_and_max_tokens():
    r = client().post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": [{"type": "text", "text": "a b c d e"}]}], "max_tokens": 2})
    body = r.json()
    assert body["choices"][0]["message"]["content"] == "ECHO: a"
    assert body["choices"][0]["finish_reason"] == "length"


def test_stream():
    with client().stream("POST", "/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "one two"}], "stream": True}) as r:
        lines = [l for l in r.iter_lines() if l.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"
    chunks = [json.loads(l[6:]) for l in lines[:-1]]
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
    assert text == "ECHO: one two"
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


def test_api_key():
    c = client(api_key="secret")
    body = {"messages": [{"role": "user", "content": "x"}]}
    assert c.post("/v1/chat/completions", json=body).status_code == 401
    assert c.get("/v1/models").status_code == 401
    ok = c.post("/v1/chat/completions", json=body, headers={"Authorization": "Bearer secret"})
    assert ok.status_code == 200


def test_prompt_too_long_is_a_clear_400():
    backend = EchoBackend("m")
    backend.max_prompt_tokens = 3
    c = TestClient(create_app(backend))
    r = c.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "a b c d e f"}]})
    assert r.status_code == 400
    assert "too long" in r.json()["error"]["message"]


def test_empty_messages():
    assert client().post("/v1/chat/completions", json={"messages": []}).status_code == 400
