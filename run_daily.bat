@echo off
chcp 65001 > nul
:: 이 파일이 있는 폴더로 이동 (작업 스케줄러 호환성 위함)
cd /d "%~dp0"

echo [YouTube to Ebook] 자동 실행을 시작합니다...
echo 현재 시간: %date% %time%

:: 파이썬 스크립트 실행 (python 대신 py 사용 권장)
py main.py

echo.
echo 실행이 완료되었습니다.
pause
