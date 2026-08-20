@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
set "LOG_DIR=%REPO_ROOT%\data\downloads\logs"
set "STATE_DIR=%REPO_ROOT%\data\downloads\state"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
if not exist "%STATE_DIR%" mkdir "%STATE_DIR%"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%bootstrap_teacher_environment.ps1" -RepoRoot "%REPO_ROOT%" >> "%LOG_DIR%\teacher_environment.log" 2>&1
set "MM26_EXIT_CODE=%ERRORLEVEL%"
> "%STATE_DIR%\teacher_environment_exit.json.tmp" echo {"schema_version":1,"status":"exited","exit_code":%MM26_EXIT_CODE%}
move /Y "%STATE_DIR%\teacher_environment_exit.json.tmp" "%STATE_DIR%\teacher_environment_exit.json" >NUL
exit /b %MM26_EXIT_CODE%
