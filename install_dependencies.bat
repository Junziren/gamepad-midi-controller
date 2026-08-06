@echo off
chcp 65001 >nul
echo ============================================
echo  Gamepad MIDI Studio - 依赖安装
echo ============================================
echo.

python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [错误] 依赖安装失败，请检查网络或 Python 环境
    pause
    exit /b 1
)

echo.
echo 依赖安装完成！
echo 运行方式：python -m gms
pause