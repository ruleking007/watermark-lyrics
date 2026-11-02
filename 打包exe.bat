@echo off
chcp 936 >nul
rem ============================================================
rem  重新打包免安装 exe（改了 app.py / editor.py 之后跑这个）
rem  需要联网装一次 PyInstaller，之后每次打包约 2-3 分钟
rem ============================================================
setlocal EnableExtensions
cd /d "%~dp0"

call "_env.bat"
if errorlevel 1 exit /b 1
set "PY=%PYEXE%"

"%PY%" -m pip show pyinstaller >nul 2>nul
if errorlevel 1 (
    echo 正在安装 PyInstaller ...
    "%PY%" -m pip install pyinstaller
    if errorlevel 1 (
        echo PyInstaller 安装失败，请检查网络。
        pause
        exit /b 1
    )
)

set "WORK=%TEMP%\wm_build"
set "DIST=%TEMP%\wm_dist"
set "SPEC=%TEMP%\wm_spec"

echo.
echo 正在打包 水印歌词.exe ...
"%PY%" -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  "--icon=%~dp0水印歌词.ico" ^
  --collect-all winrt ^
  --hidden-import winrt.windows.media.control ^
  --hidden-import winrt.windows.foundation ^
  --hidden-import winrt.windows.foundation.collections ^
  --workpath "%WORK%\app" --specpath "%SPEC%" --distpath "%DIST%" ^
  --name WatermarkLyric "%~dp0app.py"
if errorlevel 1 goto :failed

echo.
echo 正在打包 歌词编辑器.exe ...
"%PY%" -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  "--icon=%~dp0水印歌词.ico" ^
  --collect-all winrt ^
  --hidden-import winrt.windows.media.control ^
  --hidden-import winrt.windows.foundation ^
  --hidden-import winrt.windows.foundation.collections ^
  --workpath "%WORK%\editor" --specpath "%SPEC%" --distpath "%DIST%" ^
  --name LyricStudio "%~dp0editor.py"
if errorlevel 1 goto :failed

copy /y "%DIST%\WatermarkLyric.exe" "%~dp0水印歌词.exe" >nul
copy /y "%DIST%\LyricStudio.exe" "%~dp0歌词编辑器.exe" >nul
del "%DIST%\*.exe" >nul 2>nul
rmdir /s /q "%WORK%" >nul 2>nul
rmdir /s /q "%DIST%" >nul 2>nul
rmdir /s /q "%SPEC%" >nul 2>nul

echo.
echo   打包完成！两个 exe 已更新：
echo     %~dp0水印歌词.exe
echo     %~dp0歌词编辑器.exe
echo.
pause
exit /b 0

:failed
echo.
echo   [!] 打包失败，上面是 PyInstaller 的报错；原来的 exe 没有被改动。
echo.
pause
exit /b 1