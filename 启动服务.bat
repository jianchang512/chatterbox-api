@echo off
:: 将当前代码页设置为UTF-8，以正确显示中文字符。
chcp 65001 > nul

TITLE Chatterbox TTS 服务启动器

:: =======================================================
:: ==         Chatterbox TTS 服务启动器                 ==
:: =======================================================
echo.



:: 定义虚拟环境中Python解释器的路径

set "VENV_PYTHON="%~dp0venv\scripts\python.exe""
set "UVEXE="%~dp0tools\uv.exe""


:: 检查虚拟环境是否存在
IF NOT EXIST "%VENV_PYTHON%" (
    echo([安装] 未检测到虚拟环境，开始执行首次设置...
    echo.

    :: 检查uv.exe是否存在
    IF NOT EXIST %UVEXE% (
        echo([错误] 未找到 uv.exe！
        pause
        exit /b 1
    )

    :: 检查requirements.txt是否存在
    IF NOT EXIST "requirements.txt" (
        echo([错误] 未找到 requirements.txt 文件，无法安装依赖。
        pause
        exit /b 1
    )

    echo(创建虚拟环境,若需重建环境，需手动删除 venv 文件夹
	echo.
    :: 在此明确指定虚拟环境文件夹名为 "venv"
    %UVEXE% venv venv -p 3.10 --seed --link-mode=copy
    
    :: 检查上一步是否成功
    IF ERRORLEVEL 1 (
        echo.
        echo([错误] 创建虚拟环境失败。
        pause
        exit /b 1
    )
    echo([安装] 虚拟环境创建成功。
    echo.

    echo([安装] 正在向新环境中安装依赖项...
	echo.
	
    %VENV_PYTHON% -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple
    
    :: 检查上一步是否成功
    IF ERRORLEVEL 1 (
        echo.
        echo([错误] 依赖安装失败。请检查错误。
        pause
        exit /b 1
    )
    echo([安装] 依赖项安装成功。
    echo.
    echo(==              首次设置完成！                       ==
    echo.
)

:: 启动应用程序
echo( 虚拟环境已准备就绪，若需重建，请删掉 venv 文件夹后重新运行该脚本。
echo.
echo( 正在启动应用服务,用时可能较久请耐心等待...
echo.

:: 使用 venv 目录下的 python 解释器
%VENV_PYTHON% app.py

echo.
echo(服务已停止。
echo.
pause