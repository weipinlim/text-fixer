# TextFixer (Python)

The Python version of TextFixer. Select text in any app, press a hotkey, and the text is rewritten
by an LLM. It can **run the model itself on your Intel Core Ultra NPU** (through OpenVINO GenAI) and
serve it as an OpenAI-compatible API, or use any OpenAI-compatible server, Gemini or Ollama.

It does the same things as the [AutoHotkey version](../README.md) and uses the same `config.ini`
format, so you can move your tones and hotkeys between them:

- tone hotkeys (`Ctrl+1`..`Ctrl+5`) replace the selection; `Ctrl+Left click` runs the default tone
- `Ctrl+Shift+Space`: popup with a "describe your change" box and a button per tone
- `Ctrl+6/7/8`: Summary, Key Points, Table in a result window (Markdown, follow-up chat)
- `Ctrl+Shift+Left click` / `Ctrl+Shift+Right click`: every tone's answer in tabs / as a list (hover for full text)
- `Ctrl+Middle click`: explain the selected word in a tooltip
- `Ctrl+Alt+Space`: chat window
- tray icon: settings, pause hotkeys, start with Windows

## 1. Install (Windows 11, Intel Core Ultra)

1. Install **Python 3.10 or newer** from python.org (it includes tkinter).
2. Update the **Intel NPU driver** (Intel Core Ultra driver page, or Windows Update). Without a
   current driver OpenVINO cannot see the NPU.
3. In this folder:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
4. Check that the NPU is found:
   ```
   python -m textfixer check
   ```
   You should see a line like `NPU: Intel(R) AI Boost`.

## 2. Get a model

The NPU needs a model converted to OpenVINO format with **4-bit symmetric weights**. Two ways:

- **Download one that is already converted** (easiest): the `OpenVINO` organisation on Hugging Face has
  `-int4-ov` models, for example `OpenVINO/Qwen2.5-3B-Instruct-int4-ov`:
  ```
  pip install huggingface_hub
  huggingface-cli download OpenVINO/Qwen2.5-3B-Instruct-int4-ov --local-dir models/qwen2.5-3b
  ```
  (Check the exact model name on huggingface.co; availability changes.)
- **Convert one yourself:**
  ```
  pip install "optimum-intel[openvino]"
  python -m textfixer convert --model Qwen/Qwen2.5-3B-Instruct --out models/qwen2.5-3b
  ```
  This runs `optimum-cli export openvino ... --weight-format int4 --sym --ratio 1.0 --group-size -1`
  (channel-wise, which is what the NPU prefers; use `--group-size 128` for larger models if the
  NPU rejects the default).

Pick an **instruction/chat** model that fits your NPU. As a rule of thumb, 1.5B to 3B models are
comfortable on Core Ultra Series 1, and 7B to 8B models need a newer chip with more memory. See the
[OpenVINO GenAI NPU guide](https://docs.openvino.ai/) for the models it lists as supported.

## 3. Run

```
python -m textfixer
```

The first run creates `config.ini` from `config.example.ini` and opens the **Settings** window. Point
**Local model folder** at your model (for example `models\qwen2.5-3b`) and save; it restarts.

On the **first start the NPU compiles the model, which can take several minutes**. A tooltip says
"Model ready" when it is done, and the compiled model is cached in `.ov_cache`, so later starts are
fast. If the NPU cannot load the model, the app tries the GPU and then the CPU (`DEVICE=NPU,GPU,CPU`).

The app and the API server run in one process. The API is at `http://127.0.0.1:8000/v1`, so any
other tool (including the AutoHotkey version: `PROVIDER=openai`, `API_URL=http://127.0.0.1:8000/v1/chat/completions`)
can use the same model.

### Other ways to run it

| Command | What it does |
|---|---|
| `python -m textfixer` | the app and the local API server (default) |
| `python -m textfixer serve` | only the API server (no hotkeys, no windows) |
| `python -m textfixer app` | only the app, using the provider/URL in `config.ini` (no local model) |
| `python -m textfixer check` | list OpenVINO devices, check the model folder |
| `python -m textfixer --backend echo` | no model: answers with your own text. Handy to try the hotkeys and windows |

To run without a console window, use `pythonw -m textfixer`, or tray menu → **Start with Windows**.

## Using another provider

In Settings (or `config.ini`) set `PROVIDER`:

- `local`: the model on this PC (default; see `[Server]`)
- `openai`: any OpenAI-compatible server (vLLM, llama.cpp, LM Studio, ChatGPT...): set `API_URL` and `API_KEY`
- `gemini`: Google Gemini: `API_KEY`, `MODEL` (leave `API_URL` empty)
- `ollama`: a local Ollama (leave `API_URL` empty)

## Settings that matter for the NPU (`[Server]`)

- `DEVICE=NPU,GPU,CPU`: devices to try in order.
- `MAX_PROMPT_LEN=2048`: **the NPU model is compiled for a fixed prompt size.** Texts longer than this
  (in tokens) are refused with a clear message. Raise it for longer texts (it uses more memory and
  recompiles once).
- `MIN_RESPONSE_LEN=256`, `MAX_NEW_TOKENS=1024`: room for the answer.
- The NPU decodes **greedily**, so `TEMPERATURE` has no effect there (it does on GPU/CPU).
- Requests are handled **one at a time**. "Every tone at once" (`Ctrl+Shift+click`) sends one
  request per tone, so on the NPU they run one after another and the answers appear as they finish.
- `API_KEY`: if set, clients must send it. Keep `HOST=127.0.0.1` unless you want other PCs to use
  the model (then also set an `API_KEY`).

## Differences from the AutoHotkey version

- Hotkeys use the same syntax (`^+Space`, `^LButton`...). On Windows the matched key or click is
  swallowed and passed through to the app if nothing is selected, like the AutoHotkey version. This
  uses low-level hooks and is the part most worth testing on your PC.
- Only **text** on the clipboard is saved and restored (images or files on the clipboard are lost
  when a hotkey runs). The AutoHotkey version restores everything.
- The Settings window restarts the app when you save.
- Windows only for the hotkeys' pass-through and "Start with Windows". The API server also runs on
  Linux and macOS.

## Troubleshooting

- **`NPU: not available on this PC`** in the log: update the Intel NPU driver and check Device
  Manager > Neural processors. Use `DEVICE=GPU,CPU` meanwhile.
- **The model fails to load on the NPU**: try a smaller model or `--group-size 128` when converting,
  and make sure `openvino-genai` is recent (`pip install -U openvino-genai`).
- **"The text is too long for the NPU model"**: raise `MAX_PROMPT_LEN`.
- **Nothing happens on a hotkey**: another program may own it. Change it in Settings. The tray
  icon's **Show hotkeys** lists what is active.
- **A hotkey acts on the wrong app or pastes nothing**: some apps (Excel, VS Code) copy even with no
  selection; add them to `EXCLUDE_APPS`.

## Tests

```
pip install pytest httpx
python -m pytest tests
```
The window tests need a display (on Linux: `xvfb-run -a python -m pytest tests`). They use a dummy
model, so no NPU is needed.
