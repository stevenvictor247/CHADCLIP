@echo off
rem Starts Agent HQ so your other computers can open it over Tailscale. Needs HQ_PASSWORD in .env.
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
python -m hq update
python -m hq serve --host 0.0.0.0
pause
