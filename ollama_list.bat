@echo off
setlocal enabledelayedexpansion

REM Use a temp directory for the model list file
set "TMPFILE=%TEMP%\ollama_models.txt"
ollama list > "%TMPFILE%"

REM Check if the file was created
if not exist "%TMPFILE%" (
    echo Failed to create model list file. Check permissions and ollama installation.
    pause
    exit /b
)

REM Build numbered menu and skip the first line (header)
set i=0
set skipHeader=1
for /f "usebackq tokens=1,2" %%a in ("%TMPFILE%") do (
    if !skipHeader! EQU 1 (
        set skipHeader=0
    ) else (
        if not "%%a"=="" (
            set /a i+=1
            set "model[!i!]=%%a"
            if !i! EQU 1 set "firstModel=%%a"
        )
    )
)
set /a count=%i%

REM Show only the top model
if defined firstModel echo Top model: %firstModel%

REM Show all array elements for debugging
echo --- Model array ---
for /l %%j in (1,1,%count%) do (
    echo %%j: !model[%%j]!
)
echo -------------------

REM Prompt user
set /p choice=Enter model number:

REM Validate input
if "%choice%"=="" goto :invalid
set /a num=%choice% 2>nul
if %num% lss 1 goto :invalid
if %num% gtr %count% goto :invalid

REM Get model name and run
set "modelname=!model[%num%]!"
echo Running: %modelname%
ollama run %modelname%
goto :eof

:invalid
echo Invalid choice
pause
