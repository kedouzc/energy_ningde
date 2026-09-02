@echo off
chcp 65001 >nul
REM ============================================================
REM 价格真源同步器启动脚本
REM 用法：双击本文件，或命令行 node sync_prices.js
REM 前置：改了 电池价格口径统一与pack价格参考.md 后运行，全链路同步
REM ============================================================
pushd "%~dp0"
node "%~dp0sync_prices.js"
if errorlevel 1 (
  echo [错误] 同步失败，请检查 battery_prices.js 解析与 .md 自变量
  pause
  exit /b 1
)
echo.
echo [完成] 价格已同步：引擎 constants.js / 毛估估折扣链 / 总表 / 手册表格
pause
