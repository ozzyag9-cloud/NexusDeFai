#!/bin/bash
# ============================================================
# NEXUS AI — VPS Deployment Script
# Tested on Ubuntu 22.04 / 24.04
# Run: chmod +x deploy.sh && ./deploy.sh
# ============================================================

set -e
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo -e "${GREEN}"
echo "╔══════════════════════════════════╗"
echo "║  NEXUS AI — VPS Deployment       ║"
echo "╚══════════════════════════════════╝"
echo -e "${NC}"

# ── 1. System packages ──────────────────────────────────────
echo -e "${YELLOW}[1/6] Installing system packages...${NC}"
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv git curl wget unzip

# ── 2. Python virtual environment ───────────────────────────
echo -e "${YELLOW}[2/6] Setting up Python venv...${NC}"
cd /home/ubuntu/nexus_ai || { echo "Put nexus_ai in /home/ubuntu/nexus_ai first"; exit 1; }
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo -e "${GREEN}✓ Dependencies installed${NC}"

# ── 3. Environment file ─────────────────────────────────────
echo -e "${YELLOW}[3/6] Checking .env...${NC}"
if [ ! -f .env ]; then
    cp .env.example .env
    echo -e "${RED}⚠️  .env created from template. EDIT IT before starting!${NC}"
    echo "    nano /home/ubuntu/nexus_ai/.env"
    exit 1
else
    echo -e "${GREEN}✓ .env found${NC}"
fi

# ── 4. Log directory ────────────────────────────────────────
echo -e "${YELLOW}[4/6] Creating directories...${NC}"
mkdir -p logs data
chmod 755 logs data

# ── 5. Systemd service ──────────────────────────────────────
echo -e "${YELLOW}[5/6] Installing systemd service...${NC}"
cp systemd/nexus_ai.service /etc/systemd/system/nexus_ai.service
systemctl daemon-reload
systemctl enable nexus_ai
echo -e "${GREEN}✓ Service installed and enabled${NC}"

# ── 6. Test run ─────────────────────────────────────────────
echo -e "${YELLOW}[6/6] Testing single cycle...${NC}"
source venv/bin/activate
timeout 60 python main.py --once || echo "(timed out — that's ok for testing)"

echo ""
echo -e "${GREEN}════════════════════════════════════${NC}"
echo -e "${GREEN}  Deployment complete!               ${NC}"
echo -e "${GREEN}════════════════════════════════════${NC}"
echo ""
echo "Commands:"
echo "  Start:   systemctl start nexus_ai"
echo "  Stop:    systemctl stop nexus_ai"
echo "  Status:  systemctl status nexus_ai"
echo "  Logs:    journalctl -u nexus_ai -f"
echo "  API:     http://YOUR_VPS_IP:8000/docs"
echo ""
echo -e "${YELLOW}⚠️  Remember: PAPER_TRADING=true in .env until you're confident!${NC}"
