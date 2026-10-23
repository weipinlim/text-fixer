@echo off
rem Builds dist\TextFixer\TextFixer.exe (run this on Windows, in this folder).
rem Needs Python 3.10+ (python.org). Takes a few minutes; the result is a few hundred MB
rem because it contains OpenVINO.
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    python -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat || goto :error
python -m pip install --upgrade pip || goto :error
pip install -r requirements.txt pyinstaller || goto :error

pyinstaller --noconfirm --clean textfixer.spec || goto :error

copy /y config.example.ini dist\TextFixer\ >nul
if not exist dist\TextFixer\models mkdir dist\TextFixer\models

echo.
echo Done: dist\TextFixer\TextFixer.exe
echo Next: copy your OpenVINO model folder into dist\TextFixer\models\ and run TextFixer.exe.
echo       Use TextFixerCLI.exe check to see whether the NPU is found.
exit /b 0

:error
echo.
echo Build failed. See the messages above.
exit /b 1
