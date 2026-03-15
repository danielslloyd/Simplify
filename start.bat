@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo.
echo === Simplify -- startup ===
echo.

:: ── 1. git pull ──────────────────────────────────────────────────────────────
echo ^> Pulling latest changes...
git pull --ff-only >nul 2>&1
if errorlevel 1 (
    echo [!] git pull failed. Check your connection or resolve conflicts manually.
) else (
    echo [OK] Repository up to date.
)

:: ── 2. Python 3.11+ ──────────────────────────────────────────────────────────
echo ^> Checking Python...
set PYTHON=
for %%c in (python3.13 python3.12 python3.11 python3 python) do (
    if "!PYTHON!"=="" (
        where %%c >nul 2>&1
        if not errorlevel 1 (
            %%c -c "import sys; sys.exit(0 if sys.version_info>=(3,11) else 1)" >nul 2>&1
            if not errorlevel 1 (
                set PYTHON=%%c
            )
        )
    )
)
if "!PYTHON!"=="" (
    echo [ERROR] Python 3.11+ is required but was not found.
    echo         Install it from https://python.org
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('!PYTHON! --version 2^>^&1') do echo [OK] Python %%v found.

:: ── 3. uv ────────────────────────────────────────────────────────────────────
echo ^> Checking uv...
where uv >nul 2>&1
if errorlevel 1 (
    echo [!] uv not found -- installing via PowerShell...
    powershell -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    :: refresh PATH from user environment
    for /f "tokens=2*" %%a in ('reg query HKCU\Environment /v PATH 2^>nul') do set "USERPATH=%%b"
    set "PATH=!USERPATH!;%PATH%"
    where uv >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] uv install failed. Try manually: https://docs.astral.sh/uv/
        pause
        exit /b 1
    )
)
for /f "tokens=2" %%v in ('uv --version 2^>^&1') do echo [OK] uv %%v found.

:: ── 4. Ollama ────────────────────────────────────────────────────────────────
echo ^> Checking Ollama...
where ollama >nul 2>&1
if errorlevel 1 (
    echo [!] Ollama not found. Install it from https://ollama.ai and run 'ollama serve'.
    echo     LLM calls will fail until Ollama is running.
) else (
    for /f "tokens=*" %%v in ('ollama --version 2^>^&1') do echo [OK] %%v found.
    curl -sf http://localhost:11434/api/tags >nul 2>&1
    if errorlevel 1 (
        echo [!] Ollama is installed but not running. Start it with: ollama serve
        echo     LLM calls will fail until the server is up.
    ) else (
        echo [OK] Ollama server is reachable.
    )
)

:: ── 5. Python dependencies via uv ────────────────────────────────────────────
echo ^> Syncing Python dependencies...
uv sync --no-install-project --quiet
if errorlevel 1 (
    echo [ERROR] Dependency sync failed.
    pause
    exit /b 1
)
echo [OK] Dependencies ready.

:: ── 6. Launch ────────────────────────────────────────────────────────────────
echo.
echo === Starting Simplify ===
echo.

uv run python main.py %*
if errorlevel 1 (
    echo.
    echo [ERROR] Application exited with an error ^(see above^).
    pause
)
