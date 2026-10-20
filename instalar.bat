@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Instalar Colloquia

echo.
echo   Colloquia · instalación
echo   ───────────────────────
echo.

set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo   No se ha encontrado Python.
    echo   Instálalo desde https://www.python.org/downloads/ marcando "Add python.exe to PATH"
    echo   y vuelve a ejecutar este instalador.
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo   [1/3] Creando el entorno de Python...
    %PY% -m venv .venv || goto :error
) else (
    echo   [1/3] Entorno de Python ya creado.
)

echo   [2/3] Instalando dependencias. Puede tardar unos minutos...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet --disable-pip-version-check
where nvidia-smi >nul 2>&1
if %errorlevel%==0 (
    echo         GPU NVIDIA detectada: se instala el soporte CUDA.
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check || goto :error
) else (
    echo         Sin GPU NVIDIA: Colloquia funcionará en CPU ^(la transcripción será más lenta^).
    findstr /v /i "nvidia" requirements.txt > "%TEMP%\colloquia-requirements.txt"
    ".venv\Scripts\python.exe" -m pip install -r "%TEMP%\colloquia-requirements.txt" --disable-pip-version-check || goto :error
    del "%TEMP%\colloquia-requirements.txt" >nul 2>&1
)

echo   [3/3] Creando accesos directos...
powershell -NoProfile -Command "$s = New-Object -ComObject WScript.Shell; foreach ($p in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))) { $l = $s.CreateShortcut((Join-Path $p 'Colloquia.lnk')); $l.TargetPath = (Resolve-Path '.venv\Scripts\pythonw.exe').Path; $l.Arguments = '\"' + (Resolve-Path 'colloquia.py').Path + '\"'; $l.WorkingDirectory = (Get-Location).Path; $l.Description = 'Grabación y transcripción local de sesiones'; $l.Save() }"

echo.
echo   La primera vez Colloquia descarga los modelos (~1,7 GB con el modelo Turbo).
echo   Después funciona sin conexión a internet.
echo.
start "" ".venv\Scripts\pythonw.exe" colloquia.py
echo   Listo. A partir de ahora abre Colloquia desde el menú Inicio o el escritorio.
echo.
pause
exit /b 0

:error
echo.
echo   Algo ha fallado durante la instalación. Revisa los mensajes de arriba.
echo.
pause
exit /b 1
