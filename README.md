# NEXUS AI — Multi-Agent Trading Signal System

> 6 AI agents · Real-time signals · Crypto, Stocks, Forex · Telegram + API

---

## 🏗 Architecture

```
Crawler → Technical → Sentiment → Pattern → Strategy → Risk → Signal
                                                              ↓
                                              Telegram Channel + REST API
                                              Position Tracker + Webhooks
```

**6 Agents:**
| Agent | Role |
|---|---|
| Crawler | OHLCV from yfinance + RSS news every 15m |
| Technical | RSI, MACD, EMA, BB, ATR, Pivots (20+ indicators) |
| Sentiment | TextBlob + Claude AI news scoring |
| Pattern | H&S, Flags, Triangles, Double Top/Bottom |
| Strategy | 6-strategy weighted ensemble with dynamic weights |
| Risk | ATR-based TP/SL, R:R ≥1.5 gate, position sizing |

---

## 🚀 Quick Start (Local)

```bash
git clone https://github.com/ozzyag9-cloud/NexusDeFai.git
cd NexusDeFai
pip install -r requirements.txt
cp .env.example .env
# Fill in .env — see setup section below
python main.py --once       # test one signal cycle
python main.py --backtest   # generate HTML backtest report
python main.py              # run live (scheduler + bot + API)
```

---

## ⚙️ Environment Setup

### Step 1 — Telegram Bot & Channel

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy token
2. Create a Telegram channel (public or private)
3. Add your bot as **Admin** with "Post Messages" permission
4. Send any message to the channel
5. Run the helper:
   ```bash
   python setup_telegram.py
   ```
   Copy the printed `CHANNEL_ID` and `ADMIN_ID` into `.env`

### Step 2 — Fill `.env`

```env
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHANNEL_ID=-100xxxxxxxxxx
TELEGRAM_ADMIN_ID=your_user_id
ADMIN_SECRET=choose-a-strong-secret
PAPER_TRADING=true          # keep true until 90 days proven
```

### Step 3 — Test

```bash
python main.py --once
```
Check your Telegram channel — signal should appear within 60 seconds.

---

## 🌐 Going Live — Website + Backend

### Website (Landing Page) → Vercel [FREE]

1. Go to [vercel.com](https://vercel.com) → Sign up with GitHub
2. Click **"New Project"** → Import `ozzyag9-cloud/NexusDeFai`
3. Framework: **Other** (static)
4. Root directory: leave as `/`
5. Click **Deploy**

Your landing page is live at `https://nexusdefi.vercel.app` in ~60 seconds.

**Custom domain** (optional):
- Vercel dashboard → Domains → Add `yourdomain.com`
- Add the CNAME record they give you to your DNS

### Backend API → Render.com [$7/mo]

1. Go to [render.com](https://render.com) → New → **Web Service**
2. Connect GitHub → select `NexusDeFai` repo
3. Render detects `render.yaml` automatically
4. In **Environment** tab, add your secret env vars:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHANNEL_ID`
   - `TELEGRAM_ADMIN_ID`
   - `ADMIN_SECRET`
   - `ANTHROPIC_API_KEY` (optional)
5. Click **Deploy**

API will be live at `https://nexus-ai-api.onrender.com`

**Update your landing page** — replace `YOUR_CHANNEL` with your real channel link.

### Full Server (Bot + Scheduler + API) → VPS [$6/mo]

Best option for running Telegram signals + API together:

```bash
# On Ubuntu 22.04 VPS (DigitalOcean, Hetzner, etc.)
git clone https://github.com/ozzyag9-cloud/NexusDeFai.git
cd NexusDeFai
chmod +x deploy.sh && ./deploy.sh
# Follow prompts — fills in .env, installs systemd service
systemctl start nexus_ai
systemctl status nexus_ai
```

Dashboard: `http://YOUR_VPS_IP:8000/dashboard?secret=YOUR_ADMIN_SECRET`

---

## 💳 Payment Setup (Stripe)

1. Create account at [stripe.com](https://stripe.com)
2. Dashboard → **Products** → Add Product:
   - "NEXUS AI Starter" — $29/mo recurring
   - "NEXUS AI Pro" — $79/mo recurring
   - "NEXUS AI Enterprise" — $299/mo recurring
3. For each: **Payment Links** → Create Link → Copy URL
4. Replace `YOUR_STARTER_LINK`, `YOUR_PRO_LINK` in `landing_page.html`
5. After payment, manually issue API key:
   ```bash
   curl -X POST https://nexus-ai-api.onrender.com/api/admin/subscribers \
     -H "X-Admin-Secret: YOUR_ADMIN_SECRET" \
     -H "Content-Type: application/json" \
     -d '{"name":"John Doe","email":"john@example.com","tier":"pro","expires_days":30}'
   ```
   Returns the API key to send to your subscriber.

---

## 📡 Telegram Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome + quick action buttons |
| `/signals` | Last 5 signals |
| `/stats` | Win rate & performance |
| `/status` | System health |
| `/positions` | Open paper trades with live P&L |
| `/performance` | Last 10 resolved signals |
| `/subscribe` | View pricing plans |
| `/alert BTC-USD 100000` | Set a price alert |
| `/run` | *(Admin only)* Trigger manual cycle |
| `/help` | Command list |

---

## 📊 API Endpoints

All data endpoints require `X-API-Key` header (subscriber key).

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Public health check |
| GET | `/dashboard` | Admin dashboard (needs `?secret=`) |
| GET | `/api/signals` | Latest signals (tier-filtered) |
| GET | `/api/stats` | Performance statistics |
| GET | `/api/me` | Subscriber plan info |
| POST | `/api/webhook/register` | Register webhook URL |
| POST | `/api/admin/subscribers` | Create subscriber (admin) |
| GET | `/api/admin/subscribers` | List subscribers (admin) |
| DELETE | `/api/admin/subscribers/{key}` | Revoke subscriber (admin) |

Docs: `https://your-api-url/docs`

---

## 🧪 Running Tests

```bash
pip install pytest pytest-asyncio
python -m pytest tests/ -v
```

45 tests covering all major components.

---

## 🐳 Docker

```bash
docker compose up -d            # start
docker compose logs -f nexus_ai # watch logs
docker compose down             # stop
```

---

## ⚠️ Risk Warning

Trading involves substantial risk of loss. This system is for educational and informational purposes only. Never invest money you cannot afford to lose. Always conduct your own research. Past backtest performance does not guarantee future results. The authors are not financial advisors.

Always run `PAPER_TRADING=true` for at least 90 days before considering live execution.
