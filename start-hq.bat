@echo off
rem Starts Agent HQ so your other computers can open it over Tailscale. Needs HQ_PASSWORD (Settings page). Setup-Mac-Access.bat runs this at sign-in.
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
rem HQ exits with code 3 when you press "Update and restart" or save Settings, and this starts it again.
set HQ_SUPERVISED=1
:start
python -m hq update
python -m hq serve --host 0.0.0.0
if errorlevel 3 if not errorlevel 4 goto start
pause
