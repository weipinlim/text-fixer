import json
import threading

import pytest

from textfixer.config import Config
from textfixer.llm import LLMClient, LLMError
from textfixer.markdown_tk import parse_inline, parse_markdown


def cfg(tmp_path, settings="", server=""):
    p = tmp_path / "config.ini"
    p.write_text(f"[Settings]\n{settings}\n[Server]\n{server}\n", encoding="utf-8")
    return Config(p)


def test_bodies(tmp_path):
    msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}, {"role": "user", "content": "x"}]
    c = LLMClient(cfg(tmp_path, "PROVIDER=gemini\nMODEL=g\nAPI_KEY=K"))
    b = c.body(msgs, "sys")
    assert b["system_instruction"]["parts"][0]["text"] == "sys"
    assert [x["role"] for x in b["contents"]] == ["user", "model", "user"]
    assert c.headers()["x-goog-api-key"] == "K" and "Authorization" not in c.headers()
    assert c.endpoint().endswith("/models/g:generateContent")
    c = LLMClient(cfg(tmp_path, "PROVIDER=ollama\nMODEL=o"))
    b = c.body(msgs, "sys")
    assert b["messages"][0] == {"role": "system", "content": "sys"} and b["stream"] is False
    assert c.endpoint() == "http://localhost:11434/api/chat"
    c = LLMClient(cfg(tmp_path, "PROVIDER=openai\nAPI_URL=http://x/v1/chat/completions\nAPI_KEY=K\nMODEL=m"))
    assert c.headers()["Authorization"] == "Bearer K"
    assert c.body([], "")["messages"] == []
    with pytest.raises(LLMError):
        LLMClient(cfg(tmp_path, "PROVIDER=openai")).endpoint()


def test_local_endpoint_and_key(tmp_path):
    c = LLMClient(cfg(tmp_path, "PROVIDER=local", "HOST=0.0.0.0\nPORT=8123\nAPI_KEY=srv"))
    assert c.endpoint() == "http://127.0.0.1:8123/v1/chat/completions"
    assert c.headers()["Authorization"] == "Bearer srv"


def test_extract():
    assert LLMClient.extract("openai", {"choices": [{"message": {"content": "<think>x</think> hi"}}]}) == "hi"
    assert LLMClient.extract("ollama", {"message": {"content": "o"}}) == "o"
    assert LLMClient.extract("gemini", {"candidates": [{"content": {"parts": [{"text": "g"}]}}]}) == "g"
    with pytest.raises(LLMError):
        LLMClient.extract("openai", {"oops": 1})


def test_round_trip_against_own_server(tmp_path):
    from textfixer.backend import EchoBackend
    from textfixer.server import ServerThread

    srv = ServerThread(EchoBackend("m"), "127.0.0.1", 18765)
    srv.start()
    try:
        c = LLMClient(cfg(tmp_path, "PROVIDER=local\nTIMEOUT=10", "PORT=18765"))
        assert c.complete([{"role": "user", "content": 'héllo "q"\nline2'}], "sys") == 'ECHO: héllo "q"\nline2'
        done = threading.Event()
        box = []
        c.complete_async([{"role": "user", "content": "async"}], "", lambda t, e: (box.append((t, e)), done.set()))
        assert done.wait(5) and box[0] == ("ECHO: async", None)
        bad = LLMClient(cfg(tmp_path, "PROVIDER=local\nTIMEOUT=2", "PORT=18999"))
        with pytest.raises(LLMError, match="Cannot reach"):
            bad.complete([{"role": "user", "content": "x"}])
    finally:
        srv.stop()


def test_inline_markdown():
    parts = parse_inline("a **b *c* d** `e` ~~f~~ [g](https://h.io)")
    assert ("b ", frozenset({"bold"})) in parts and ("c", frozenset({"bold", "italic"})) in parts
    assert ("e", frozenset({"code"})) in parts and ("f", frozenset({"strike"})) in parts
    assert ("g (https://h.io)", frozenset()) in parts
    assert "".join(t for t, _ in parse_inline("2*3*4 snake_case_name")) == "2*3*4 snake_case_name"


def test_blocks():
    md = "# T\n\ntext\nmore\n\n- a\n- b\n\n1. x\n2. y\n\n| A | B |\n|---|--:|\n| 1 | 2 |\n\n> q\n\n---\n\n```\ncode <x>\n```\n"
    kinds = [b[0] for b in parse_markdown(md)]
    assert kinds == ["h", "p", "li", "li", "li", "li", "table", "quote", "hr", "code"]
    blocks = parse_markdown(md)
    assert blocks[1] == ("p", "text\nmore")
    assert [b[1] for b in blocks if b[0] == "li"] == ["•", "•", "1.", "2."]
    assert blocks[6] == ("table", ["A", "B"], [["1", "2"]])
    assert blocks[9] == ("code", "code <x>")
