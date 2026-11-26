@echo off
setlocal
cd /d "%~dp0"

if not exist "main.py" (
    echo main.py bulunamadi: %~dp0
    pause
    exit /b 1
)

rem Konsolsuz baslatma: pyw (pythonw) kullanilir. Boylece siyah cmd penceresi
rem acilmaz ve Qt'nin stderr uyarilari ekrana dusmez.
where pyw >nul 2>&1
if not errorlevel 1 (
    start "" pyw -3.14 "%~dp0main.py"
    exit /b 0
)

rem pyw yoksa konsollu calistir; hata mesajlari gorunur kalir.
py -3.14 "%~dp0main.py"
if errorlevel 1 (
    echo.
    echo Uygulama baslatilamadi. Hata mesaji yukarida.
    echo Gerekli paketler: py -m pip install -r requirements.txt
    pause
)
