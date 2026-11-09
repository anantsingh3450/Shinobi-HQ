@echo off
REM Double-click wrapper for Restart-Hokage.ps1.
REM
REM 2026-11-09. The .ps1 exists because three commands pasted by hand is three
REM places to lose one, and the commander lost one twice. This exists because
REM one command pasted by hand is still one place to lose it: a wrong shell, a
REM wrong folder, an execution policy, a window that shuts before he reads the
REM proof. None of those are his mistakes; they are the cost of a text step.
REM
REM So: double-click it. It sets its own folder, bypasses the policy for this
REM one process only, and HOLDS THE WINDOW OPEN at the end - the output is the
REM entire point, because the script's job is to prove the restart happened
REM rather than to claim it.

cd /d "%~dp0"
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Restart-Hokage.ps1"
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" (
  echo ===============================================================
  echo  IT DID NOT RESTART. Exit code %RC%.
  echo  Read the red lines above - they say which step stopped, and
  echo  the stop is the step that usually fails. Nothing was forced.
  echo ===============================================================
)
echo.
echo Press any key to close this window.
pause >nul
exit /b %RC%
