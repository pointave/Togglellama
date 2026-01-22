@echo off
call conda activate ***-YOUR-ENVIRONMENT-***
cd /d "%~dp0"
start /MIN pythonw main.py