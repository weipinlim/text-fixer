"""Local model backends. OpenVinoBackend runs a model on an Intel NPU/GPU/CPU through
OpenVINO GenAI; EchoBackend is a dummy for trying the app and for tests."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger("textfixer.backend")

Messages = list[dict[str, str]]


@dataclass
class GenParams:
    max_new_tokens: int = 512
    temperature: float = 0.0
    top_p: float = 1.0
    stop: list[str] = field(default_factory=list)


@dataclass
class GenResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str = "stop"  # "stop" or "length"


class PromptTooLong(ValueError):
    pass


class Backend:
    model_name = "local"
    device = "none"
    max_prompt_tokens: int | None = None

    def count_tokens(self, messages: Messages) -> int:
        raise NotImplementedError

    def generate(self, messages: Messages, params: GenParams,
                 on_text: Callable[[str], bool | None] | None = None) -> GenResult:
        """Generate an answer. on_text gets each new piece of text; returning True stops early."""
        raise NotImplementedError


class EchoBackend(Backend):
    """Answers with the last user message, word by word. No model needed."""

    def __init__(self, model_name: str = "echo", delay: float = 0.0):
        self.model_name = model_name
        self.device = "echo"
        self.delay = delay
        self._lock = threading.Lock()

    def count_tokens(self, messages: Messages) -> int:
        return sum(len(m["content"].split()) for m in messages)

    def generate(self, messages, params, on_text=None):
        last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        words = f"ECHO: {last}".split(" ")
        out: list[str] = []
        finish = "stop"
        with self._lock:
            for i, word in enumerate(words):
                if len(out) >= params.max_new_tokens:
                    finish = "length"
                    break
                piece = word if i == 0 else " " + word
                out.append(piece)
                if self.delay:
                    time.sleep(self.delay)
                if on_text and on_text(piece):
                    break
        text = "".join(out)
        for stop in params.stop:
            cut = text.find(stop)
            if cut >= 0:
                text = text[:cut]
                break
        return GenResult(text, self.count_tokens(messages), len(out), finish)


class OpenVinoBackend(Backend):
    def __init__(self, model_dir: str, devices: str = "NPU,GPU,CPU", model_name: str = "local",
                 max_prompt_len: int = 2048, min_response_len: int = 256, cache_dir: str = ".ov_cache"):
        try:
            import openvino_genai as ov_genai
        except ImportError as exc:  # pragma: no cover - depends on the install
            raise RuntimeError("openvino-genai is not installed: pip install openvino-genai") from exc
        self._genai = ov_genai
        self.model_name = model_name
        self._lock = threading.Lock()

        available = _available_devices()
        log.info("OpenVINO devices found: %s", ", ".join(available) or "(none)")
        errors = []
        self.pipe = None
        for device in [d.strip() for d in devices.split(",") if d.strip()]:
            if available and device.split(".")[0] not in {a.split(".")[0] for a in available}:
                errors.append(f"{device}: not available on this PC")
                continue
            props: dict[str, object] = {"CACHE_DIR": cache_dir}
            if device.upper().startswith("NPU"):
                props.update({"MAX_PROMPT_LEN": int(max_prompt_len), "MIN_RESPONSE_LEN": int(min_response_len)})
            try:
                log.info("Loading %s on %s%s...", model_dir, device,
                         " (the first NPU start can take a few minutes)" if device.upper().startswith("NPU") else "")
                self.pipe = ov_genai.LLMPipeline(str(model_dir), device, props)
                self.device = device
                break
            except Exception as exc:  # try the next device
                errors.append(f"{device}: {exc}")
                log.warning("Could not load the model on %s: %s", device, exc)
        if self.pipe is None:
            raise RuntimeError("Could not load the model on any device:\n  " + "\n  ".join(errors))

        self.tokenizer = self.pipe.get_tokenizer()
        self.max_prompt_tokens = int(max_prompt_len) if self.device.upper().startswith("NPU") else None
        log.info("Model ready on %s", self.device)

    # -- helpers --------------------------------------------------------
    def _prompt(self, messages: Messages) -> str:
        prompt = self.tokenizer.apply_chat_template(messages, add_generation_prompt=True)
        # The tokenizer adds the BOS token again when encoding; don't send it twice
        bos = ""
        try:
            bos = self.tokenizer.get_bos_token()
        except Exception:
            pass
        if bos and prompt.startswith(bos):
            prompt = prompt[len(bos):]
        return prompt

    def count_tokens(self, messages: Messages) -> int:
        prompt = self._prompt(messages)
        try:
            return int(self.tokenizer.encode([prompt]).input_ids.shape[1])
        except Exception:
            return max(1, len(prompt) // 4)  # rough estimate if the tokenizer API differs

    def generate(self, messages, params, on_text=None):
        prompt = self._prompt(messages)
        prompt_tokens = self.count_tokens(messages)
        if self.max_prompt_tokens and prompt_tokens > self.max_prompt_tokens:
            raise PromptTooLong(
                f"The text is too long for the NPU model ({prompt_tokens} tokens, limit "
                f"{self.max_prompt_tokens}). Raise MAX_PROMPT_LEN in [Server] or use a shorter text.")

        gc = self.pipe.get_generation_config()
        gc.max_new_tokens = params.max_new_tokens
        gc.apply_chat_template = False  # the template is already applied above
        npu = self.device.upper().startswith("NPU")
        if params.temperature > 0 and not npu:  # the NPU pipeline decodes greedily
            gc.do_sample = True
            gc.temperature = params.temperature
            gc.top_p = params.top_p
        else:
            gc.do_sample = False
        if params.stop:
            gc.stop_strings = set(params.stop)

        cancelled = False
        chunks: list[str] = []
        running = getattr(self._genai.StreamingStatus, "RUNNING", False)
        cancel = getattr(self._genai.StreamingStatus, "CANCEL", True)

        def streamer(piece: str):
            nonlocal cancelled
            chunks.append(piece)
            if on_text and on_text(piece):
                cancelled = True
                return cancel
            return running

        with self._lock:
            result = self.pipe.generate(prompt, gc, streamer)
        text = "".join(chunks) or str(result)
        completion = _generated_tokens(result) or max(1, len(text) // 4)
        finish = "length" if (not cancelled and completion >= params.max_new_tokens) else "stop"
        return GenResult(text, prompt_tokens, completion, finish)


def _available_devices() -> list[str]:
    try:
        import openvino as ov

        return list(ov.Core().available_devices)
    except Exception:
        return []


def _generated_tokens(result) -> int:
    try:
        return int(result.perf_metrics.get_num_generated_tokens())
    except Exception:
        return 0


def create_backend(cfg, kind: str = "auto") -> Backend:
    """kind: "openvino", "echo" or "auto" (openvino)."""
    if kind == "echo":
        return EchoBackend(cfg.server("MODEL_NAME") or "echo")
    return OpenVinoBackend(
        model_dir=cfg.resolve_path(cfg.server("MODEL_DIR")),
        devices=cfg.server("DEVICE"),
        model_name=cfg.server("MODEL_NAME") or "local",
        max_prompt_len=int(cfg.number("Server", "MAX_PROMPT_LEN", 2048)),
        min_response_len=int(cfg.number("Server", "MIN_RESPONSE_LEN", 256)),
        cache_dir=cfg.resolve_path(cfg.server("CACHE_DIR")),
    )
