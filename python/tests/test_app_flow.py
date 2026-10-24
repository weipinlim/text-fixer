"""End-to-end flows with real windows (needs a display: xvfb-run) and the real local API server."""
import pytest

from textfixer.app import App
from textfixer.hotkeys import parse_hotkey
from textfixer.llm import LLMClient
from textfixer.ui import CompareWindow, Context, PopupWindow, ResultWindow

from conftest import FakeClipboard, FakeHotkeys, pump, run_thread


@pytest.fixture
def app(cfg, ui):
    clip = FakeClipboard()
    return App(cfg, ui, clip=clip, hotkeys=FakeHotkeys())


def ctx_for(app):
    s = app.clip.copy_selection()
    return Context(s.text, s.saved, 0, parse_hotkey("^1"))


def test_tone_hotkey_replaces_text(app, ui):
    t = run_thread(app.on_hotkey, "preset2", parse_hotkey("^2"))
    assert pump(ui, lambda: app.clip.pasted)
    # the selection's trailing "  \n" is kept, with Windows line endings
    assert app.clip.pasted[0] == ("ECHO: sample text  \r\n", "SAVED")
    t.join(2)


def test_default_hotkey_uses_default_preset(app, ui):
    app.on_hotkey("default", parse_hotkey("^LButton"))
    assert pump(ui, lambda: app.clip.pasted)
    assert app.clip.pasted[0][0] == "ECHO: sample text  \r\n"


def test_incompatible_text_is_not_pasted(app, ui):
    app.clip.text = "GIBBERISH xx"
    app.on_hotkey("preset1", parse_hotkey("^1"))
    assert pump(ui, lambda: app.clip.restored)
    assert app.clip.pasted == [] and app.clip.restored == ["SAVED"]


def test_no_selection_passes_through(app, ui):
    app.clip.text = ""
    called = []
    app.passthrough = lambda combo: called.append(combo)
    app.on_hotkey("preset1", parse_hotkey("^1"))
    assert len(called) == 1 and app.clip.pasted == []


def test_popup_custom_instruction_and_tone_button(app, ui):
    ctx = ctx_for(app)
    app.show_popup(ctx)
    popup = next(iter(ui.windows))
    assert isinstance(popup, PopupWindow) and ui.windows
    popup.entry.insert(0, "translate to French")
    popup.send()
    assert pump(ui, lambda: app.clip.pasted)
    assert "Described change: translate to French" in app.clip.pasted[0][0]
    assert pump(ui, lambda: not ui.windows)

    app.clip.pasted.clear()
    ctx = ctx_for(app)
    app.show_popup(ctx)
    popup = next(iter(ui.windows))
    popup.pick(app.cfg.presets[1])
    assert pump(ui, lambda: app.clip.pasted)
    assert app.clip.pasted[0][0].startswith("ECHO: sample text")


def test_popup_escape_restores_clipboard(app, ui):
    ctx = ctx_for(app)
    app.show_popup(ctx)
    popup = next(iter(ui.windows))
    popup.close()
    assert app.clip.restored == ["SAVED"] and not ui.windows


def test_window_preset_with_followup(app, ui):
    app.run_preset(app.cfg.presets[5], ctx_for(app))  # Summary (MODE=window)
    assert pump(ui, lambda: any(isinstance(w, ResultWindow) for w in ui.root.winfo_children()))
    win = next(w for w in ui.root.winfo_children() if isinstance(w, ResultWindow))
    assert pump(ui, lambda: win.items)
    assert win.items[0][0] == "assistant" and win.items[0][1].startswith("ECHO: sample text")
    win.entry.insert(0, "and then?")
    win.send()
    assert pump(ui, lambda: len(win.items) == 3)
    assert win.items[1] == ("user", "and then?") and win.items[2][1] == "ECHO: and then?"
    assert [m["role"] for m in win.history] == ["user", "assistant", "user", "assistant"]
    assert "ECHO: and then?" in win.text.get("1.0", "end")
    win.destroy()


def test_blank_chat_window(app, ui):
    app.open_chat()
    win = next(w for w in ui.root.winfo_children() if isinstance(w, ResultWindow))
    win.entry.insert(0, "hello")
    win.send()
    assert pump(ui, lambda: len(win.items) == 2)
    assert win.items[1][1] == "ECHO: hello"
    win.destroy()


@pytest.mark.parametrize("mode", ["tabs", "list"])
def test_compare_windows(app, ui, mode):
    ctx = ctx_for(app)
    app.compare(ctx, mode)
    assert pump(ui, lambda: ui.windows and all(j.done for j in next(iter(ui.windows)).jobs))
    win = next(iter(ui.windows))
    assert isinstance(win, CompareWindow) and len(win.jobs) == 5
    assert all(j.text.startswith("ECHO: sample text") for j in win.jobs)
    win.use(2)
    assert pump(ui, lambda: app.clip.pasted)
    assert pump(ui, lambda: not ui.windows)


def test_compare_runs_one_at_a_time_with_ollama_and_shows_progress(app, ui, ollama):
    ollama.delay = 0.3
    app.compare(ctx_for(app), "tabs")
    assert pump(ui, lambda: ui.windows)
    win = next(iter(ui.windows))
    assert "Writing the first of 5" in win.progress.cget("text")
    assert pump(ui, lambda: "1 of 5 ready" in win.progress.cget("text"))
    # the first finished answer is shown and can be used while the others are still coming
    assert str(win.use_btn.cget("state")) == "normal" and win.jobs[win.selected].done
    assert pump(ui, lambda: win.progress.cget("text") == "All 5 ready", 10)
    chats = [r for r in ollama.requests if r["path"] == "/api/chat"]
    assert len(chats) == 5
    for before, after in zip(chats, chats[1:]):
        assert after["start"] >= before["end"] - 0.01  # never two at once
    win.close()


def test_closing_compare_stops_the_remaining_requests(app, ui, ollama):
    ollama.delay = 0.3
    app.clip.text = "closing test"
    app.compare(ctx_for(app), "list")
    assert pump(ui, lambda: ui.windows)
    win = next(iter(ui.windows))
    assert pump(ui, lambda: any(j.done for j in win.jobs))
    assert "Waiting for its turn" in win.rows[-1].cget("text")
    win.close()
    t = __import__("time").time()
    while __import__("time").time() - t < 1.0:
        ui.root.update()
    mine = [r for r in ollama.requests if r["path"] == "/api/chat"
            and r["body"]["messages"][-1]["content"] == "closing test"]
    assert len(mine) <= 2  # the one finished, maybe the one already started; not the other 3


def test_compare_marks_incompatible(app, ui):
    app.clip.text = "GIBBERISH"
    app.compare(ctx_for(app), "tabs")
    assert pump(ui, lambda: ui.windows and all(j.done for j in next(iter(ui.windows)).jobs))
    win = next(iter(ui.windows))
    assert all("isn't compatible" in j.error for j in win.jobs)
    win.close()
    assert app.clip.restored == ["SAVED"]


def test_explain_shows_tooltip(app, ui):
    ctx = ctx_for(app)
    run_thread(app.explain, ctx)
    assert pump(ui, lambda: ui._tip is not None and "ECHO" in ui._tip.winfo_children()[0].cget("text"))
    assert app.clip.restored[0] == "SAVED"
    ui.hide_tip()


def test_busy_hotkey_passes_through(app, ui):
    app.busy = True
    called = []
    app.passthrough = lambda combo: called.append(combo)
    app.on_hotkey("preset1", parse_hotkey("^1"))
    assert called and not app.clip.pasted


def test_startup_check_missing_model_and_unreachable(app, ui):
    app.cfg.update("Settings", {"MODEL": "mistral"})
    app.check_ollama()
    assert pump(ui, lambda: ui._tip is not None and "does not have the model 'mistral'" in ui._tip.winfo_children()[0].cget("text"))
    ui.hide_tip()
    app.cfg.update("Settings", {"MODEL": "llama3.2", "API_URL": "http://127.0.0.1:18999"})
    app.llm = LLMClient(app.cfg)
    app.check_ollama()
    assert pump(ui, lambda: ui._tip is not None and "Cannot reach Ollama" in ui._tip.winfo_children()[0].cget("text"))


def test_startup_check_is_silent_when_all_is_well(app, ui):
    app.check_ollama()
    ui.root.update()
    assert ui._tip is None


def test_request_failure_shows_error_and_restores_clipboard(app, ui, monkeypatch):
    shown = []
    monkeypatch.setattr(ui, "error", lambda message, title="TextFixer": shown.append(message))
    app.cfg.update("Settings", {"MODEL": "nope"})
    app.on_hotkey("preset1", parse_hotkey("^1"))
    assert pump(ui, lambda: shown)
    assert "ollama pull nope" in shown[0] and app.clip.pasted == [] and app.clip.restored == ["SAVED"]
    assert app.busy is False


def test_settings_window_models_download_and_save(app, ui, ollama, monkeypatch):
    from textfixer.ui import PullWindow, SettingsWindow

    saved = []
    win = SettingsWindow(ui, app, lambda: saved.append(True))
    assert pump(ui, lambda: win.model_box.cget("values"))
    assert list(win.model_box.cget("values")) == ["llama3.2:latest", "qwen2.5:3b"]
    assert "2 model(s)" in win.status.cget("text")

    win.model.set("phi3")
    win.download()
    pull = next(w for w in ui.root.winfo_children() if isinstance(w, PullWindow))
    assert pump(ui, lambda: pull.status.cget("text").startswith("Done"))
    assert "phi3:latest" in ollama.installed and pump(ui, lambda: "phi3:latest" in win.model_box.cget("values"))

    win.vars["TEMPERATURE"].set("0.7")
    win.provider.set("ollama")
    win.save()
    assert saved == [True] and app.cfg.setting("TEMPERATURE") == "0.7" and app.cfg.setting("MODEL") == "phi3"


def test_settings_cancel_changes_nothing(app, ui):
    from textfixer.ui import SettingsWindow

    win = SettingsWindow(ui, app, lambda: None)
    win.vars["API_URL"].set("http://127.0.0.1:18999")
    win.refresh_models()  # tries the typed (unsaved) address
    assert pump(ui, lambda: "Cannot reach Ollama" in win.status.cget("text"), 10)
    win.destroy()
    assert app.cfg.setting("API_URL") == "http://127.0.0.1:18766"


def test_hotkey_registration_and_errors(cfg, ui):
    cfg.update("Settings", {"POPUP_HOTKEY": "^+Nonsense"})
    app = App(cfg, ui, clip=FakeClipboard(), hotkeys=FakeHotkeys())
    app.register_hotkeys()
    assert any("POPUP_HOTKEY" in e for e in app.hotkey_errors)
    summary = app.hotkey_summary()
    assert "Ctrl+1 = Casual" in summary and "Ctrl+Alt+Space = open the chat window" in summary


def test_old_mouse_shortcuts_are_switched_off_once(cfg, ui, monkeypatch):
    from textfixer.config import Config

    cfg.update("Settings", {"DEFAULT_HOTKEY": "^LButton", "EXPLAIN_HOTKEY": "^MButton"})
    cfg.update("Preset3", {"HOTKEY": "^RButton"})
    shown = []
    monkeypatch.setattr(ui, "info", lambda message, title="TextFixer": shown.append(message))
    app = App(cfg, ui, clip=FakeClipboard(), hotkeys=FakeHotkeys())
    app.start()
    ui.root.update()
    assert shown and "^LButton (default tone)" in shown[0] and "Ctrl+Shift+Space" in shown[0]
    assert app.hotkey_errors == []
    again = Config(cfg.path)
    assert again.setting("DEFAULT_HOTKEY") == "" and again.setting("EXPLAIN_HOTKEY") == ""
    assert again.presets[2].hotkey == "" and again.setting("POPUP_HOTKEY") == "^+Space"
    shown.clear()
    App(again, ui, clip=FakeClipboard(), hotkeys=FakeHotkeys()).start()
    ui.root.update()
    assert shown == []  # the note only shows once


def test_popup_compare_and_explain_buttons(app, ui):
    ctx = ctx_for(app)
    app.show_popup(ctx)
    popup = next(iter(ui.windows))
    popup.compare("list")
    assert pump(ui, lambda: ui.windows and isinstance(next(iter(ui.windows)), CompareWindow))
    win = next(iter(ui.windows))
    assert win.mode == "list"
    win.close()
    app.show_popup(ctx_for(app))
    next(iter(ui.windows)).explain()
    assert pump(ui, lambda: ui._tip is not None and "ECHO" in ui._tip.winfo_children()[0].cget("text"))


def test_passthrough_goes_to_the_hotkey_manager(app):
    sent = []
    app.hk.suppresses = True
    app.hk.passthrough = lambda combo, send: sent.append(combo)
    app.passthrough(parse_hotkey("^1"))
    assert sent == [parse_hotkey("^1")]
