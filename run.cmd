@echo off
setlocal
rem PPTAgent launcher - opens a WSL shell with venv, config and office mode ready.
rem Run it from Windows: double-click, or `.\run.cmd` in cmd/PowerShell.
rem Different distro name? set PPTAGENT_WSL_DISTRO=Ubuntu-22.04

if "%PPTAGENT_WSL_DISTRO%"=="" (set "DISTRO=Ubuntu") else (set "DISTRO=%PPTAGENT_WSL_DISTRO%")

set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
for /f "usebackq delims=" %%i in (`wsl.exe -d %DISTRO% wslpath -a "%HERE%" 2^>nul`) do set "REPO=%%i"

if not defined REPO (
  echo.
  echo   [FAIL] WSL distro "%DISTRO%" is not reachable.
  echo          Check `wsl -l -q` and set PPTAGENT_WSL_DISTRO to the right name.
  echo.
  pause
  exit /b 1
)

wsl.exe -d %DISTRO% --cd "%REPO%" -- bash --init-file "%REPO%/scripts/devshell.sh"
