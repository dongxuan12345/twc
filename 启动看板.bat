@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" "C:\Users\user\AppData\Local\Programs\Python\Python39\python.exe" -m venv .venv
if not exist ".venv\Scripts\python.exe" echo [ERROR] venv creation failed & pause & exit /b 1
".venv\Scripts\python.exe" -c "import streamlit, openai, dotenv, pandas" >nul 2>nul || ".venv\Scripts\python.exe" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
".venv\Scripts\python.exe" -m streamlit run app.py --server.port 8501
echo.
echo Service stopped.
pause
