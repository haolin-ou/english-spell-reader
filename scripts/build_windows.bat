@echo off
setlocal

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
    echo [ERROR] Windows build script failed with exit code %EXIT_CODE%.
) else (
    echo [DONE] Windows build script completed successfully.
)

pause
endlocal & exit /b %EXIT_CODE%
