@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo    ShortsEditor - build (run once)
echo ============================================
echo.

set "PYCMD="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PYCMD=py -3"
if defined PYCMD goto HAVEPY
python --version >nul 2>&1
if not errorlevel 1 set "PYCMD=python"
if defined PYCMD goto HAVEPY
goto NOPY

:HAVEPY
echo Using Python: %PYCMD%
%PYCMD% --version
echo.
echo [1/3] Installing build tools (pip, pyinstaller, pillow)...
%PYCMD% -m pip install --upgrade pip
%PYCMD% -m pip install pyinstaller pillow
echo.
echo [2/3] Building portable exe (with OTA)... 3-6 minutes (ffmpeg bundled)
%PYCMD% -m PyInstaller --onefile --noconfirm --noconsole --name ShortsEditor --add-binary "_bin_win\ffmpeg.exe;." --add-binary "_bin_win\yt-dlp.exe;." --add-data "font.ttf;." --add-data "app.py;." bootstrap.py
if errorlevel 1 goto FAILBUILD

echo.
echo [3/3] Cleaning up...
copy /Y "dist\ShortsEditor.exe" "ShortsEditor.exe" >nul
rmdir /S /Q build >nul 2>&1
rmdir /S /Q dist >nul 2>&1
del /Q "ShortsEditor.spec" >nul 2>&1

echo.
echo ============================================
echo    DONE!  "ShortsEditor.exe" was created here.
echo    From now on, just double-click ShortsEditor.exe
echo ============================================
pause
exit /b

:NOPY
echo [!] Real Python is NOT installed (only a Microsoft Store shortcut).
echo.
echo  Please install Python first:
echo    1) Open  https://www.python.org/downloads/
echo    2) Click the big yellow "Download Python" button
echo    3) Run the installer
echo    4) VERY IMPORTANT: check the box
echo         [v] Add python.exe to PATH   (at the bottom)
echo    5) Click "Install Now", wait until done
echo    6) Then double-click this bat again
echo.
pause
exit /b

:FAILBUILD
echo [!] Build failed. Please screenshot this window and send it.
pause
exit /b
