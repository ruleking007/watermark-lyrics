@echo off
chcp 936 >nul
rem ============================================================
rem  install PyQt5 / requests / winrt into a suitable Python
rem  usage:  安装依赖.bat            -> 安装
rem          安装依赖.bat check      -> 只检查，不安装
rem ============================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "CHECKONLY="
if /i "%~1"=="check" set "CHECKONLY=1"
set "PKGS=PyQt5 requests winrt-Windows.Media.Control winrt-Windows.Foundation winrt-Windows.Foundation.Collections"
set "TARGET="
set "TARGETPATH="

if defined WATERMARK_PYTHON (
    if exist "%WATERMARK_PYTHON%" set "TARGETPATH=%WATERMARK_PYTHON%"
)
if not defined TARGETPATH (
    for %%V in (3.13 3.12 3.11 3.10 3.9) do (
        if not defined TARGETPATH (
            py -%%V -c "import sys" >nul 2>nul
            if not errorlevel 1 set "TARGETPATH=py -%%V"
        )
    )
)
if not defined TARGETPATH (
    python -c "import sys" >nul 2>nul
    if not errorlevel 1 set "TARGETPATH=python"
)
if not defined TARGETPATH (
    echo.
    echo  [!] 这台电脑没找到 Python。
    echo      请先到 python.org 安装 Python 3.11 / 3.12 / 3.13，
    echo      安装时勾选 "Add python.exe to PATH"，然后重新运行本脚本。
    echo.
    if not "%NO_PAUSE%"=="1" pause
    exit /b 1
)

set "ISFILE="
if exist "%TARGETPATH%" set "ISFILE=%TARGETPATH%"
if defined ISFILE (set "TARGET="%TARGETPATH%"") else (set "TARGET=%TARGETPATH%")

set "REALPY="
if defined ISFILE (
    set "REALPY=%TARGETPATH%"
) else (
    for /f "usebackq delims=" %%P in (`%TARGET% -c "import sys;sys.stdout.write(sys.executable)"`) do set "REALPY=%%P"
)

echo.
<nul set /p="   解释器 : "
if defined REALPY (echo %REALPY%) else (echo %TARGETPATH%)
<nul set /p="   版本   : "
%TARGET% -c "import sys;sys.stdout.write('.'.join(map(str,sys.version_info[:3])))"
echo.
<nul set /p="   缺少   : "
%TARGET% -c "import PyQt5" >nul 2>nul
if errorlevel 1 (set "MISSING=PyQt5 ") else (set "MISSING=")
%TARGET% -c "import requests" >nul 2>nul
if errorlevel 1 set "MISSING=!MISSING!requests "
%TARGET% -c "import winrt.windows.media.control" >nul 2>nul
if errorlevel 1 set "MISSING=!MISSING!winrt"
if defined MISSING (echo !MISSING!) else (echo 无，依赖已齐全)

%TARGET% -c "import sys;raise SystemExit(0 if sys.version_info[:2] <= (3,13) else 1)" >nul 2>nul
if errorlevel 1 (
    echo.
    echo   [!] 这个 Python 是 3.14 或更新，PyQt5 目前没有对应的预编译包，装不上。
    echo       请改装 Python 3.11 / 3.12 / 3.13 后再运行本脚本。
    echo.
    if not "%NO_PAUSE%"=="1" pause
    exit /b 1
)

echo.
if defined CHECKONLY (
    echo   [检查模式] 正式安装时会执行：
    echo     %TARGET% -m pip install --upgrade pip
    echo     %TARGET% -m pip install %PKGS%
    echo.
    if not "%NO_PAUSE%"=="1" pause
    exit /b 0
)

echo   开始安装依赖（需要联网，约 60-100 MB，第一次可能要几分钟）...
echo.
%TARGET% -m pip install --upgrade pip
%TARGET% -m pip install %PKGS%
echo.
%TARGET% -c "import PyQt5, requests, winrt.windows.media.control;print('   依赖自检通过')"
if errorlevel 1 (
    echo.
    echo   [!] 依赖仍不完整，请把上面的报错信息留一下。
    if not "%NO_PAUSE%"=="1" pause
    exit /b 1
)
if defined REALPY >"%CD%\_python.txt" echo(%REALPY%
echo.
echo   完成！现在可以双击「启动水印歌词.bat」或「启动歌词编辑器.bat」了。
echo.
if not "%NO_PAUSE%"=="1" pause
exit /b 0