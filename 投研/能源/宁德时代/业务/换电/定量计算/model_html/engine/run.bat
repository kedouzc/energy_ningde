@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo   宁德时代 超换一体站 财务模型引擎
echo   自动调参工具
echo ========================================
echo.
echo 正在启动...
echo.

REM 检查 Node.js 是否安装
where node >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [错误] 未检测到 Node.js，请先安装 Node.js！
    echo 下载地址: https://nodejs.org/
    echo.
    echo 如果你已经安装了 Node.js，请尝试：
    echo   1. 关闭此窗口，重新打开
    echo   2. 或在命令行中手动运行: node cli.js
    pause
    exit /b 1
)

REM 运行 CLI 脚本
node "%~dp0cli.js" %*

echo.
echo ========================================
echo   运行完成
echo ========================================
pause