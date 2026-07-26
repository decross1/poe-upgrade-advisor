@echo off
rem ============================================================
rem  PoE Upgrade Advisor - MVP v0 launcher for Windows (TASK-208)
rem  Double-click run.bat. No dev tooling needed: uses the Python
rem  launcher (py), python3, or python on PATH, and bootstraps
rem  the server's one dependency into a private venv (.venv\).
rem ============================================================
setlocal
cd /d "%~dp0"

rem --- bind and smoke-test the bundled Windows x86-64 engine runtime.
if not defined POBCALC_RUNTIME set "POBCALC_RUNTIME=%CD%\engine\.runtime"
if not exist "%POBCALC_RUNTIME%\bin\luajit.exe" goto fail_engine
if not exist "%POBCALC_RUNTIME%\bin\lua51.dll" goto fail_engine
if not exist "%POBCALC_RUNTIME%\lib\lua\5.1\lua-utf8.dll" goto fail_engine
"%POBCALC_RUNTIME%\bin\luajit.exe" -e "package.cpath=[[%POBCALC_RUNTIME%\lib\lua\5.1\?.dll]]; require('lua-utf8')"
if errorlevel 1 goto fail_engine
if /I "%~1"=="--runtime-check-only" exit /b 0

rem --- find a Python: prefer the py launcher, then python3, then python on PATH.
set "PY="
where py >nul 2>nul && set "PY=py -3"
if defined PY goto python_found
where python3 >nul 2>nul && set "PY=python3"
if defined PY goto python_found
where python >nul 2>nul && set "PY=python"
if defined PY goto python_found
echo error: Python 3.10+ not found. Install it from https://www.python.org/downloads/ 1>&2
echo        (the python.org installer provides the "py" launcher this script prefers) 1>&2
exit /b 1

:python_found
rem --- fast path: pyyaml already importable - run straight off it.
%PY% -c "import yaml" >nul 2>nul
if not errorlevel 1 goto run_system

rem --- slow path (first run only): private venv + the server's one dep.
if exist .venv\Scripts\python.exe goto run_venv
echo first run: creating a private Python environment (.venv\)...
%PY% -m venv .venv
if errorlevel 1 goto fail_venv
.venv\Scripts\python.exe -m pip install --quiet --disable-pip-version-check "pyyaml>=6.0"
if errorlevel 1 goto fail_pip

:run_venv
.venv\Scripts\python.exe packaging\launch.py --open %*
exit /b %errorlevel%

:run_system
%PY% packaging\launch.py --open %*
exit /b %errorlevel%

:fail_venv
echo error: could not create the private Python environment (.venv). 1>&2
exit /b 1

:fail_pip
echo error: could not install pyyaml (needs an internet connection, once). 1>&2
exit /b 1

:fail_engine
echo error: the Windows calculation engine cannot start; the bundled runtime is missing or incompatible. 1>&2
echo        No verdict was produced. Re-download the app and report this in #poe if it continues. 1>&2
exit /b 1
