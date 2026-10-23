import threading

import pytest

from textfixer.config import Config
from textfixer.llm import LLMClient, LLMError
from textfixer.markdown_tk import parse_inline, parse_markdown


def cfg(tmp_path, settings=""):
    p = tmp_path / "config.ini"
    p.write_text(f"[Settings]\n{settings}\n", encoding="utf-8")
    return Config(p)


def test_bodies(tmp_path):
    msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}, {"role": "user", "content": "x"}]
    c = LLMClient(cfg(tmp_path, "PROVIDER=gemini\nMODEL=g\nAPI_KEY=K"))
    b = c.body(msgs, "sys")
    assert b["system_instruction"]["parts"][0]["text"] == "sys"
    assert [x["role"] for x in b["contents"]] == ["user", "model", "user"]
    assert c.headers()["x-goog-api-key"] == "K" and "Authorization" not in c.headers()
    assert c.endpoint().endswith("/models/g:generateContent")
    c = LLMClient(cfg(tmp_path, "PROVIDER=ollama\nMODEL=o"))  # the default provider
    b = c.body(msgs, "sys")
    assert b["messages"][0] == {"role": "system", "content": "sys"} and b["stream"] is False
    assert b["keep_alive"] == "30m" and b["model"] == "o"
    assert c.endpoint() == "http://localhost:11434/api/chat"
    c = LLMClient(cfg(tmp_path, "PROVIDER=openai\nAPI_URL=http://x/v1/chat/completions\nAPI_KEY=K\nMODEL=m"))
    assert c.headers()["Authorization"] == "Bearer K"
    assert c.body([], "")["messages"] == []
    with pytest.raises(LLMError):
        LLMClient(cfg(tmp_path, "PROVIDER=openai")).endpoint()


def test_ollama_address_forms(tmp_path):
    for url in ("http://pc:11434", "http://pc:11434/", "pc:11434", "http://pc:11434/api/chat"):
        c = LLMClient(cfg(tmp_path, f"PROVIDER=ollama\nAPI_URL={url}"))
        assert c.endpoint() == "http://pc:11434/api/chat", url
        assert c.ollama_base() == "http://pc:11434"
    assert LLMClient(cfg(tmp_path, "PROVIDER=ollama\nKEEP_ALIVE=")).body([], "")  .get("keep_alive") is None


def test_extract():
    assert LLMClient.extract("openai", {"choices": [{"message": {"content": "<think>x</think> hi"}}]}) == "hi"
    assert LLMClient.extract("ollama", {"message": {"content": "o"}}) == "o"
    assert LLMClient.extract("gemini", {"candidates": [{"content": {"parts": [{"text": "g"}]}}]}) == "g"
    with pytest.raises(LLMError):
        LLMClient.extract("openai", {"oops": 1})


def test_round_trip_against_ollama(cfg, ollama):
    c = LLMClient(cfg)
    assert c.complete([{"role": "user", "content": 'h\u00e9llo "q"\nline2'}], "sys") == 'ECHO: h\u00e9llo "q"\nline2'
    sent = ollama.requests[-1]["body"]
    assert sent["messages"][0] == {"role": "system", "content": "sys"} and sent["keep_alive"] == "30m"
    done = threading.Event()
    box = []
    c.complete_async([{"role": "user", "content": "async"}], "", lambda t, e: (box.append((t, e)), done.set()))
    assert done.wait(5) and box[0] == ("ECHO: async", None)


def test_friendly_errors(cfg, tmp_path):
    cfg.update("Settings", {"MODEL": "nope"})
    with pytest.raises(LLMError, match="ollama pull nope"):
        LLMClient(cfg).complete([{"role": "user", "content": "x"}])
    down = LLMClient(cfg_down(tmp_path))
    with pytest.raises(LLMError, match="Is Ollama running"):
        down.complete([{"role": "user", "content": "x"}])
    with pytest.raises(LLMError, match="Cannot reach"):
        down.list_models()


def cfg_down(tmp_path):
    return cfg(tmp_path, "PROVIDER=ollama\nAPI_URL=http://127.0.0.1:18999\nTIMEOUT=2")


def test_models_and_pull(cfg, ollama):
    c = LLMClient(cfg)
    assert c.list_models() == ["llama3.2:latest", "qwen2.5:3b"]
    assert c.has_model("llama3.2") and c.has_model("qwen2.5:3b") and not c.has_model("mistral")
    events = list(c.pull_model("mistral"))
    assert events[0] == ("pulling manifest", None) and ("pulling abc", 0.5) in events and events[-1][0] == "success"
    assert c.has_model("mistral")
    with pytest.raises(LLMError, match="does not exist"):
        list(c.pull_model("broken"))


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
