@echo off
REM Cambia SERVER=localhost por el nombre de tu servidor de SQL Server si es otro.
set DINAMEX_SQL_CONN=DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost;DATABASE=invDinamex;Trusted_Connection=yes;TrustServerCertificate=yes
cd /d "%~dp0"
python app.py
pause
