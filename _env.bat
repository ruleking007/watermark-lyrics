@echo off
chcp 936 >nul
rem ============================================================
rem  find a Python that can run this app (needs PyQt5+requests+winrt)
rem  result: writes _python.txt, exports PYEXE and PYWEXE
rem  usage:   call "%~dp0_env.bat"
rem ============================================================
setlocal EnableExtensions EnableDelayedExpansion
set "ROOT=%~dp0"
set "CACHE=%ROOT%_python.txt"
set "LIST=%ROOT%_python_candidates.txt"
if defined LYRIC_PY_LIST set "LIST=%LYRIC_PY_LIST%"
set "PY="

if defined WATERMARK_PYTHON (
    call :check "%WATERMARK_PYTHON%"
    if defined PY goto :done
)

if exist "%CACHE%" (
    set "CACHED="
    set /p CACHED=<"%CACHE%"
    if defined CACHED call :check "!CACHED!"
    if defined PY goto :done
)

if exist "%LIST%" (
    for /f "usebackq tokens=* eol=#" %%L in ("%LIST%") do (
        if not defined PY (
            set "CAND=%%L"
            call set "CAND=%%CAND%%"
            if not "!CAND!"=="" call :check "!CAND!"
        )
    )
)
if not defined PY goto :fail

:done
set "PYW=%PY%"
for %%F in ("%PY%") do if exist "%%~dpFpythonw.exe" set "PYW=%%~dpFpythonw.exe"
>"%CACHE%" echo(%PY%
echo [env] 使用 Python: %PY%
if not "%PYW%"=="%PY%" echo [env] 静默启动: %PYW%
endlocal & set "PYEXE=%PY%" & set "PYWEXE=%PYW%" & exit /b 0

:fail
echo.
echo  ============================================================
echo   [!] 没找到可用的 Python 解释器
echo.
echo   本程序需要：Python 3.9 ~ 3.13 + PyQt5 + requests + winrt
echo   常见原因：这台电脑没装 Python；装的却是 3.14（PyQt5 还没有
echo   对应的预编译包）；或者库没装齐。
echo.
echo   办法一：直接运行「安装依赖.bat」，它会挑一个合适的 Python 装好；
echo   办法二：把已装好依赖的 python.exe 完整路径写到
echo           _python_candidates.txt 的第一行，再重新双击启动。
echo  ============================================================
echo.
if not "%NO_PAUSE%"=="1" (
    choice /c YN /n /m "现在就运行「安装依赖.bat」？[Y/N] "
    if not errorlevel 2 call "%ROOT%安装依赖.bat"
    echo.
    pause
)
endlocal
exit /b 1

:check
rem  首带引号的程序不能塞进 for /f，所以是完整路径时直接用它自己
set "CAND=%~1"
set "CAND=%CAND:"=%"
if "%CAND%"=="" exit /b 0
if exist "%CAND%" (
    set "REAL=%CAND%"
    goto :check_import
)
rem 像路径却不存在（比如 C:\Program Files\Python313\python.exe 没装），直接跳过
echo %CAND%|find /i ".exe" >nul && exit /b 0
echo %CAND%|find "\" >nul && exit /b 0
set "REAL="
for /f "usebackq delims=" %%E in (`%CAND% -c "import sys;sys.stdout.write(sys.executable)" 2^>nul`) do set "REAL=%%E"
if not defined REAL exit /b 0
if not exist "%REAL%" exit /b 0

:check_import
"%REAL%" -c "import PyQt5, requests, winrt.windows.media.control" >nul 2>nul
if errorlevel 1 exit /b 0
set "PY=%REAL%"
exit /b 0