"""End-to-end flows with real windows (needs a display: xvfb-run) and the real local API server."""
import pytest

from textfixer.app import App
from textfixer.hotkeys import parse_hotkey
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


def test_local_model_not_ready_message(app, ui):
    app.server_status = "loading"
    app.on_hotkey("preset1", parse_hotkey("^1"))
    assert pump(ui, lambda: ui._tip is not None and "loading" in ui._tip.winfo_children()[0].cget("text"))
    assert app.clip.pasted == [] and app.clip.restored == ["SAVED"]


def test_hotkey_registration_and_errors(cfg, ui):
    from textfixer.hotkeys import HotkeyManager

    cfg.update("Settings", {"POPUP_HOTKEY": "^+Nonsense"})
    app = App(cfg, ui, clip=FakeClipboard(), hotkeys=HotkeyManager(lambda a, c: None))
    app.register_hotkeys()
    assert any("POPUP_HOTKEY" in e for e in app.hotkey_errors)
    summary = app.hotkey_summary()
    assert "Ctrl+Left click = default tone" in summary and "Ctrl+1 = Casual" in summary
