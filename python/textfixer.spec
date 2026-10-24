# PyInstaller spec for TextFixer (Python). Build on Windows with build_exe.bat, or:
#   pyinstaller --noconfirm textfixer.spec
# Result: dist/TextFixer/ with TextFixer.exe (no console window) and TextFixerCLI.exe (with console,
# for `check` and seeing errors). Put config.example.ini next to them.
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

WINDOWS = sys.platform == "win32"
datas, binaries, hiddenimports = [], [], []

# pystray picks its platform backend with importlib at run time, so PyInstaller cannot see it
hiddenimports += collect_submodules("pystray") + ["pystray._win32" if WINDOWS else "pystray._xorg"]
hiddenimports += ["PIL._tkinter_finder", "darkdetect"]
datas += collect_data_files("customtkinter")  # its colour themes and fonts
excludes = ["torch", "tensorflow", "matplotlib", "scipy", "pandas", "IPython", "pytest", "numpy"]
if WINDOWS:
    # On Windows keys are sent with SendInput (textfixer/keys.py): no keyboard library in the build
    excludes.append("pynput")
else:  # Linux test builds use pynput, which also picks its backend at run time
    hiddenimports += collect_submodules("pynput") + ["pynput.keyboard._xorg", "pynput._util.xorg"]

a = Analysis(
    ["run_textfixer.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
)
pyz = PYZ(a.pure)

# File properties (Details tab): an .exe without them looks more suspicious to antivirus scanners
version = "installer/version_info.txt" if WINDOWS else None
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="TextFixer", console=False, upx=False, version=version)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="TextFixerCLI", console=True, upx=False, version=version)
coll = COLLECT(gui, cli, a.binaries, a.datas, name="TextFixer", upx=False)
