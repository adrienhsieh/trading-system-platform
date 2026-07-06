#!/bin/bash
# ── Trading System — Oracle Cloud Free 一鍵部署 ──────────────
# 使用方式：在 Oracle Cloud VM 上執行
#   curl -sSL https://raw.githubusercontent.com/chadcoco1444/trading-system/main/deploy/setup.sh | bash
#
# 前置條件：Ubuntu 22.04/24.04（Oracle Cloud Free ARM 或 AMD）

set -e

APP_DIR="/opt/trading-system"
SERVICE_NAME="trading-system"

echo "═══════════════════════════════════════════════════"
echo "  📈 Trading System — Oracle Cloud 部署"
echo "═══════════════════════════════════════════════════"

# ── 1. 系統更新 + 安裝 Python 3.12 ──────────────────────────
echo "[1/6] 安裝系統套件..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip python3-venv git curl

# ── 2. Clone repo ─────────────────────────────────────────────
echo "[2/6] 下載程式碼..."
if [ -d "$APP_DIR" ]; then
    cd "$APP_DIR"
    git pull
else
    sudo git clone https://github.com/chadcoco1444/trading-system.git "$APP_DIR"
    sudo chown -R $USER:$USER "$APP_DIR"
    cd "$APP_DIR"
fi

# ── 3. 建立虛擬環境 + 安裝套件 ────────────────────────────────
echo "[3/6] 安裝 Python 套件..."
python3 -m venv .venv
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# ── 4. 建立 .env（如果不存在）────────────────────────────────
echo "[4/6] 設定環境變數..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "⚠️  請編輯 /opt/trading-system/.env 設定以下變數："
    echo "   TELEGRAM_BOT_TOKEN=your_token"
    echo "   TELEGRAM_ALLOWED_IDS=your_chat_id"
    echo "   GROQ_API_KEY=your_groq_key"
    echo ""
    echo "   編輯指令：nano /opt/trading-system/.env"
    echo ""
fi

# ── 5. 建立 systemd service ───────────────────────────────────
echo "[5/6] 建立系統服務..."
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null <<EOF
[Unit]
Description=Trading System
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
Environment=PATH=$APP_DIR/.venv/bin:/usr/bin
ExecStart=$APP_DIR/.venv/bin/python run.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}

# ── 6. 防火牆開放 8787 ────────────────────────────────────────
echo "[6/6] 設定防火牆..."
sudo iptables -I INPUT -p tcp --dport 8787 -j ACCEPT
# 持久化防火牆規則
if command -v netfilter-persistent &> /dev/null; then
    sudo netfilter-persistent save 2>/dev/null || true
else
    sudo apt-get install -y -qq iptables-persistent
    sudo netfilter-persistent save
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✅ 部署完成！"
echo ""
echo "  1. 編輯環境變數："
echo "     nano /opt/trading-system/.env"
echo ""
echo "  2. 啟動服務："
echo "     sudo systemctl start trading-system"
echo ""
echo "  3. 查看狀態："
echo "     sudo systemctl status trading-system"
echo ""
echo "  4. 查看 log："
echo "     journalctl -u trading-system -f"
echo ""
echo "  5. 瀏覽器開啟："
echo "     http://<你的公網IP>:8787"
echo "═══════════════════════════════════════════════════"
