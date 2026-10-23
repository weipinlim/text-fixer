# PyInstaller spec for TextFixer (Python). Build on Windows with build_exe.bat, or:
#   pyinstaller --noconfirm textfixer.spec
# Result: dist/TextFixer/ with TextFixer.exe (no console window) and TextFixerCLI.exe (with console,
# for `check`, `serve` and seeing errors). Put config.example.ini and your models folder next to them.
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []
# OpenVINO loads its device plugins (CPU, GPU, NPU) as DLLs at run time, so collect everything
for package in ("openvino", "openvino_genai", "openvino_tokenizers"):
    try:
        d, b, h = collect_all(package)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # openvino_tokenizers is optional
        print(f"[spec] skipping {package}: {exc}")

# pynput and pystray pick their platform backend (win32 on Windows) with importlib at run time, so
# PyInstaller cannot see it: collect every submodule. uvicorn imports its parts the same way.
for package in ("uvicorn", "pynput", "pystray"):
    hiddenimports += collect_submodules(package)
hiddenimports += ["PIL._tkinter_finder"]
# Named explicitly as well, so the build does not depend on being able to import them (the X11
# ones need a display; they only matter for test builds on Linux)
hiddenimports += ["pynput.keyboard._win32", "pynput.mouse._win32", "pynput._util.win32", "pystray._win32",
                  "pynput.keyboard._xorg", "pynput.mouse._xorg", "pynput._util.xorg", "pystray._xorg"]

a = Analysis(
    ["run_textfixer.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["torch", "tensorflow", "matplotlib", "scipy", "pandas", "IPython", "pytest"],
)
pyz = PYZ(a.pure)

gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="TextFixer", console=False)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="TextFixerCLI", console=True)
coll = COLLECT(gui, cli, a.binaries, a.datas, name="TextFixer")
