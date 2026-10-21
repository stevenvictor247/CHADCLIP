@echo off
rem Double-click once to put an "Agent HQ" icon on your Desktop.
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python -m hq install-shortcut
pause
