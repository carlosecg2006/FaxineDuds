@echo off
rem Abre a interface do Faxineiro (desenvolvimento: so mexe na pasta_teste)
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m faxineiro gui
