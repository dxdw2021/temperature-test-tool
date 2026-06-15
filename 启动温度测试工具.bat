@echo off
title 温度测试工具
cd /d "%~dp0"

echo ========================================
echo   温度测试工具 - 正在启动...
echo ========================================
echo.

if not exist ".venv64\Scripts\python.exe" (
    echo [错误] 未找到虚拟环境，请先安装依赖
    pause
    exit /b 1
)

if not exist "temperature_test.py" (
    echo [错误] 未找到主程序文件
    pause
    exit /b 1
)

echo 启动中，请稍候...
.venv64\Scripts\python.exe temperature_test.py

if %errorlevel% neq 0 (
    echo.
    echo [错误] 程序异常退出，错误代码：%errorlevel%
    pause
)