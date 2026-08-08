@echo off
REM ---------------------------------------------------------------------
REM  Respaldo automatico de OrdersCode.
REM
REM  Este archivo existe para que el Programador de tareas de Windows pueda
REM  correr el respaldo solo. No hay que ejecutarlo a mano: si quieres un
REM  respaldo en el momento, usa  python -m scripts.respaldar
REM
REM  Se apoya en el .env del proyecto, asi que respalda la base a la que
REM  apunte DATABASE_URL (hoy: produccion en Supabase).
REM ---------------------------------------------------------------------

REM Se para en la carpeta del proyecto sin importar desde donde lo llamen.
cd /d "%~dp0"

if not exist "respaldos" mkdir "respaldos"

set "LOG=respaldos\respaldo.log"

echo. >> "%LOG%"
echo ===== %DATE% %TIME% ===== >> "%LOG%"

REM Se llama al python del entorno virtual directamente, sin activar nada:
REM el Programador de tareas no hereda el entorno de tu terminal.
"%~dp0venv\Scripts\python.exe" -m scripts.respaldar >> "%LOG%" 2>&1

if errorlevel 1 (
    echo *** EL RESPALDO FALLO. Revisa el detalle arriba. *** >> "%LOG%"
    exit /b 1
)

echo Respaldo OK >> "%LOG%"
exit /b 0
