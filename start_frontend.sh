#!/bin/bash
# 启动独立前端（API 服务器 + 静态文件服务）
cd "$(dirname "$0")"
echo "🚀 启动 AI Resume System 前端..."
echo "   API:    http://localhost:8080/api"
echo "   UI:     http://localhost:8080"
echo "   Streamlit: http://localhost:8501 (原版)"
echo ""
python frontend/api_server.py
