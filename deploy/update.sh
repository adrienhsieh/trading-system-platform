#!/bin/bash
# ── Trading System — 更新腳本 ─────────────────────────────────
# 使用方式：在 Oracle Cloud VM 上執行
#   bash /opt/trading-system/deploy/update.sh

set -e

APP_DIR="/opt/trading-system"
SERVICE_NAME="trading-system"

echo "📈 更新 Trading System..."

cd "$APP_DIR"
source .venv/bin/activate

# Pull latest
git pull

# Update dependencies
pip install --quiet -r requirements.txt

# Run tests
echo "🧪 執行測試..."
python -m unittest discover tests/ 2>&1 | tail -3

# Restart service
echo "🔄 重啟服務..."
sudo systemctl restart ${SERVICE_NAME}

echo "✅ 更新完成！"
sudo systemctl status ${SERVICE_NAME} --no-pager | head -5
