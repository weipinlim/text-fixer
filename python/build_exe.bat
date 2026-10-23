@echo off
rem Builds dist\TextFixer\TextFixer.exe (run this on Windows, in this folder).
rem Needs Python 3.10+ (python.org). Takes a minute or two.
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    python -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat || goto :error
python -m pip install --upgrade pip || goto :error
pip install -r requirements.txt pyinstaller || goto :error

pyinstaller --noconfirm --clean textfixer.spec || goto :error

copy /y config.example.ini dist\TextFixer\ >nul

echo.
echo Done: dist\TextFixer\TextFixer.exe
echo Next: install Ollama (https://ollama.com), then run TextFixer.exe. The first run opens Settings,
echo       where "Download model" fetches the model. TextFixerCLI.exe check tells you if Ollama is reachable.
exit /b 0

:error
echo.
echo Build failed. See the messages above.
exit /b 1
