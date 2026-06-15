@echo off
chcp 65001 >nul
echo 启动 jTessBoxEditor...
start "" java -jar "%~dp0jTessBoxEditor\jTessBoxEditor.jar"
echo.
echo 已启动 jTessBoxEditor，请稍候...
pause
