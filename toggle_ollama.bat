@echo off
setlocal

:: Check if Ollama is running
tasklist /FI "IMAGENAME eq ollama app.exe" 2>NUL | find /I /N "ollama app.exe" >NUL

if "%ERRORLEVEL%"=="0" (
    echo Ollama is running. Shutting it down...
    taskkill /IM "ollama app.exe" /T /F
) else (
    echo Ollama is not running. Starting it...
    start "" "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
)

endlocal
