@echo off
:: 将当前代码页设置为UTF-8，以正确显示中文字符。
chcp 65001 > nul

TITLE 安装N卡GPU支持 



set "VENV_PYTHON="%~dp0runtime\python.exe""



call %VENV_PYTHON% -m pip uninstall  -y  torch torchaudio 
call %VENV_PYTHON% -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128

echo.
echo( 安装 cuda12.8 完毕，请重新执行启动脚本
echo.

pause