@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (set PY=py -3) else (set PY=python)
if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -q -r requirements.lock
if errorlevel 1 goto failed
start "" http://127.0.0.1:8765
.venv\Scripts\python.exe app.py
if errorlevel 1 goto failed
goto end
:failed
echo.
echo Nao foi possivel iniciar. Verifique se Python 3.10 ou superior esta instalado.
pause
:end
endlocal
