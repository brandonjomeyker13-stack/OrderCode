@echo off
REM ---------------------------------------------------------------------
REM  Envio diario del resumen de lotes atrasados.
REM
REM  Este archivo existe para que el Programador de tareas de Windows lo
REM  corra solo, una vez al dia. No hay que ejecutarlo a mano.
REM
REM  Es seguro que corra de mas: cada empresa recibe como mucho un resumen
REM  cada 20 horas, y a las que no tienen atrasos no se les manda nada.
REM
REM  Se apoya en el .env del proyecto, asi que trabaja sobre la base a la
REM  que apunte DATABASE_URL y necesita RESEND_API_KEY para poder enviar.
REM ---------------------------------------------------------------------

cd /d "%~dp0"

if not exist "logs" mkdir "logs"

set "LOG=logs\alertas.log"

echo. >> "%LOG%"
echo ===== %DATE% %TIME% ===== >> "%LOG%"

REM Se llama al python del entorno virtual directamente: el Programador de
REM tareas no hereda el entorno de tu terminal.
"%~dp0venv\Scripts\python.exe" -m scripts.enviar_alertas >> "%LOG%" 2>&1

if errorlevel 1 (
    echo *** EL ENVIO DE ALERTAS FALLO. Revisa el detalle arriba. *** >> "%LOG%"
    exit /b 1
)

exit /b 0
