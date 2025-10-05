@echo off
:: 将当前代码页设置为UTF-8，以正确显示中文字符。
chcp 65001 > nul

TITLE Chatterbox TTS 服务启动器

:: =======================================================
:: ==         Chatterbox TTS 服务启动器                 ==
:: =======================================================
echo.



:: 定义虚拟环境中Python解释器的路径
rem set HF_ENDPOINT=https://hf-mirror.com
rem set https_proxy=http://127.0.0.1:10808
set "VENV_PYTHON="%~dp0runtime\python.exe""

%VENV_PYTHON% app.py

echo.
echo(服务已停止。
echo.
pause