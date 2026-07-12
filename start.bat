@echo off
chcp 65001 >nul
cd /d "%~dp0"
set HTTP_PROXY=http://127.0.0.1:7897
set HTTPS_PROXY=http://127.0.0.1:7897
echo ==================================================
echo Starting Medicine OCR Tool...
echo ==================================================
echo.
python main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Proxy fail, retrying without proxy...
    set HTTP_PROXY=
    set HTTPS_PROXY=
    python main.py
)
pause
