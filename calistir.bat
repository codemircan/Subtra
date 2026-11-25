@echo off
REM Subtra baslatici - cift tiklayarak calistirin
cd /d "%~dp0"

py -3.14 main.py
if errorlevel 1 (
    echo.
    echo Uygulama baslatilamadi. Hata mesaji yukarida.
    echo Gerekli paketler: py -m pip install -r requirements.txt
    pause
)
