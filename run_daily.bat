@echo off
chcp 65001 > nul
:: Keep this file ASCII-only. A batch file that switches itself to code
:: page 65001 gets its multibyte UTF-8 lines misread by cmd.exe: the tail
:: of a Korean comment ran as a command ("'...' is not recognized as an
:: internal or external command"). Korean printed by Python is fine; only
:: this file's own text must stay ASCII (test_run_daily_bat.py checks).

:: Run from this folder (Task Scheduler starts elsewhere)
cd /d "%~dp0"

echo [YouTube to Ebook] Daily run started
echo Time: %date% %time%

:: Print Python output immediately, as UTF-8
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8

:: NotebookLM auth check - skipped entirely while audio is off.
:: "nlm login" opens a browser and waits for a person, so a scheduled run
:: would hang here forever. Runs only when .env has ENABLE_PODCAST=true.
echo.
set ENABLE_PODCAST=false
for /f "tokens=2 delims==" %%a in ('findstr /b /i "ENABLE_PODCAST" .env 2^>nul') do set ENABLE_PODCAST=%%a
if /i "%ENABLE_PODCAST%"=="true" goto check_auth
echo [Auth] Audio is off - skipping NotebookLM auth.
goto run_main

:check_auth
echo [Auth] Checking NotebookLM auth...
py -c "from notebooklm_tools.core.auth import load_cached_tokens; from notebooklm_tools import NotebookLMClient; t=load_cached_tokens(); assert t and t.cookies; c=NotebookLMClient(cookies=t.cookies, csrf_token=t.csrf_token); c.list_notebooks()" >nul 2>&1
if errorlevel 1 (
    echo [!] NotebookLM auth expired. Starting re-auth...
    echo     Finish the Google sign-in in the browser.
    echo.
    C:\Users\user\AppData\Local\Programs\Python\Python314\Scripts\nlm.exe login
    echo.
) else (
    echo [OK] NotebookLM auth is valid
)

:run_main
:: Run the pipeline
py main.py

echo.
echo Done.
pause
