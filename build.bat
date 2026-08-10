@echo off
chcp 65001 >nul
echo ============================================
echo  Gamepad MIDI Studio - 打包构建
echo ============================================
echo.
python -m pip install -r requirements.txt
python -m pip install pyinstaller

python -m PyInstaller --noconfirm --clean --onedir --noconsole ^
  --name GamepadMIDIStudio ^
  --icon "assets\icon.ico" ^
  --add-data "gms\ui;gms\ui" ^
  run.py

if errorlevel 1 (
    echo.
    echo [错误] 打包失败
    pause
    exit /b 1
)

echo.
echo 构建完成：dist\GamepadMIDIStudio\GamepadMIDIStudio.exe
pause
