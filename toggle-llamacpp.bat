@echo off
setlocal

set "LLAMA_EXE=llama-server.exe"
set "LLAMA_DIR=--YOUR_FILEPATH--...\llama.cpp\build\bin\Release"                 ###EDIT ME
set "MODELS_DIR=--YOUR_GGUF_MODEL_FOLDER--"                                      ###EDIT ME TOO

:: Check if llama-server is running
tasklist /FI "IMAGENAME eq %LLAMA_EXE%" 2>NUL | find /I "%LLAMA_EXE%" >NUL

if "%ERRORLEVEL%"=="0" (
    echo llama-server is running. Shutting it down...
    taskkill /IM "%LLAMA_EXE%" /T /F >NUL 2>&1
) else (
    echo llama-server is not running. Starting it...
    pushd "%LLAMA_DIR%"
    start "llama.cpp server" "%LLAMA_EXE%" --models-dir "%MODELS_DIR%" -c 16000     ##### add flags here
    popd
)

:: Wait 1 second, then close automatically
timeout /t 1 /nobreak >NUL
endlocal
exit
