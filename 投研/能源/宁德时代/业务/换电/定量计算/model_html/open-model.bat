@echo off
chcp 65001 >nul
title 宁德时代换电财务模型 - 启动器

REM 切换到 model.html 的上级目录（换电/），使 ../定性分析/ 相对路径生效
cd /d "%~dp0.."

where python >nul 2>nul
if %errorlevel% neq 0 (
  echo [错误] 未找到 python，请先安装 Python 3 并加入系统 PATH。
  echo 下载地址：https://www.python.org/downloads/
  pause
  exit /b 1
)

REM 端口8123已占用则直接开浏览器（服务已在运行）
netstat -ano | findstr ":8123" | findstr "LISTENING" >nul
if %errorlevel%==0 (
  echo HTTP服务已在运行，直接打开浏览器...
  start "" "http://localhost:8123/财务模型/model.html"
  exit /b
)

echo 正在启动HTTP服务（端口8123，后台运行，关闭此窗口不影响）...
start "换电模型HTTP服务(请勿关闭)" /min cmd /c "python -m http.server 8123"

REM 等待服务就绪
timeout /t 2 /nobreak >nul

echo 正在打开模型页面...
start "" "http://localhost:8123/财务模型/model.html"
echo.
echo 启动完成。此窗口可关闭。模型页面已在新窗口打开。
echo 提示：更新 定性分析/ 下的MD后，浏览器刷新即可看到最新内容。
timeout /t 3 /nobreak >nul
exit
