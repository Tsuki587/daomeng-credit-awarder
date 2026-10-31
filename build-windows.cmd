@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo 找不到 .venv，请先运行 install-windows.cmd
    exit /b 1
)

.venv\Scripts\python.exe -m pip install -r requirements-gui.txt || exit /b 1

rem 仓库里放了 platform-tools 就一起打进去，省得目标电脑再装 adb
set "ADB_ARG="
if exist "vendor\platform-tools\adb.exe" set "ADB_ARG=--add-binary vendor\platform-tools\adb.exe;vendor/platform-tools"

.venv\Scripts\pyinstaller.exe --noconfirm --clean --windowed --onedir --name daomeng-gui --paths . %ADB_ARG% DM-gui.py || exit /b 1

echo.
echo 打包完成: dist\daomeng-gui\daomeng-gui.exe
echo 把整个 dist\daomeng-gui 目录拷给要发分的电脑即可。
