@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Abre o aplicativo de janela propria. O .exe e "windowed": nao deixa
rem console aberto, por isso este .bat encerra logo em seguida.

if exist ".venv\Scripts\lauda-app.exe" (
    start "" ".venv\Scripts\lauda-app.exe"
    exit /b 0
)

echo.
echo  [ERRO] O ambiente do aplicativo nao esta instalado.
echo.
echo  Abra o PowerShell nesta pasta e rode, uma unica vez:
echo.
echo     py -3.12 -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt; pip install -e .
echo.
pause
exit /b 1
