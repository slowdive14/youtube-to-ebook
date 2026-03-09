@echo off
chcp 65001 > nul
:: 이 파일이 있는 폴더로 이동 (작업 스케줄러 호환성 위함)
cd /d "%~dp0"

echo [YouTube to Ebook] 자동 실행을 시작합니다...
echo 현재 시간: %date% %time%

:: 화면 출력이 딜레이 없이 바로 나오게 설정
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8

:: NotebookLM 인증 상태 확인
echo.
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

:: 파이썬 스크립트 실행
py main.py

echo.
echo 실행이 완료되었습니다.
pause
