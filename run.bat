@echo off
chcp 65001 >nul
echo ========================================
echo AI Resume System - 一键启动
echo ========================================

:: 检查 .env
if not exist .env (
    echo [警告] .env 文件不存在！
    echo 请创建 .env 文件并填入 DEEPSEEK_API_KEY
    echo.
    echo 示例:
    echo DEEPSEEK_API_KEY=your_key_here
    echo DEEPSEEK_BASE_URL=https://api.deepseek.com
    echo DEEPSEEK_MODEL=deepseek-chat
    echo.
    pause
    exit /b 1
)

echo [1/3] 安装依赖...
pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo 安装失败，请检查网络连接
    pause
    exit /b 1
)

echo [2/3] 运行数据分析...
python modules/data_analysis.py

echo [3/3] 启动系统...
echo.
echo 打开浏览器访问: http://localhost:8501
echo.
streamlit run app.py

pause
