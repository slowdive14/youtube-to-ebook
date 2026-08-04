@echo off
chcp 65001 > nul
:: 이 파일이 있는 폴더로 이동 (작업 스케줄러 호환성 위함)
cd /d "%~dp0"

echo [YouTube to Ebook] 자동 실행을 시작합니다...
echo 현재 시간: %date% %time%

:: 화면 출력이 딜레이 없이 바로 나오게 설정
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8

:: NotebookLM 인증 확인 — 오디오 생성이 꺼져 있으면 통째로 건너뜁니다.
:: nlm login 은 브라우저를 띄우고 사람 손을 기다리므로, 예약 실행이
:: 여기서 무한정 멈춰 버립니다. .env 의 ENABLE_PODCAST=true 일 때만 수행.
echo.
set ENABLE_PODCAST=false
for /f "tokens=2 delims==" %%a in ('findstr /b /i "ENABLE_PODCAST" .env 2^>nul') do set ENABLE_PODCAST=%%a
if /i "%ENABLE_PODCAST%"=="true" goto check_auth
echo [Auth] 오디오 생성 꺼짐 - NotebookLM 인증을 건너뜁니다.
goto run_main

:check_auth
echo [Auth] NotebookLM 인증 상태 확인 중...
py -c "from notebooklm_tools.core.auth import load_cached_tokens; from notebooklm_tools import NotebookLMClient; t=load_cached_tokens(); assert t and t.cookies; c=NotebookLMClient(cookies=t.cookies, csrf_token=t.csrf_token); c.list_notebooks()" >nul 2>&1
if errorlevel 1 (
    echo [!] NotebookLM 인증 만료. 재인증을 시작합니다...
    echo     브라우저에서 Google 로그인을 완료해주세요.
    echo.
    C:\Users\user\AppData\Local\Programs\Python\Python314\Scripts\nlm.exe login
    echo.
) else (
    echo [OK] NotebookLM 인증 유효
)

:run_main
:: 파이썬 스크립트 실행
py main.py

echo.
echo 실행이 완료되었습니다.
pause
