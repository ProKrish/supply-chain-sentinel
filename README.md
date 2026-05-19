# 🛰️ Supply Chain Sentinel

> **Predict. Detect. Reroute.** A real-time AI-powered supply chain disruption detection and rerouting platform.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Vercel-black?style=for-the-badge&logo=vercel)](https://supply-chain-sentinel-rho.vercel.app)
[![Backend](https://img.shields.io/badge/Backend-Render-purple?style=for-the-badge&logo=render)](https://supply-chain-sentinel.onrender.com/docs)
[![GitHub](https://img.shields.io/badge/GitHub-ProKrish-181717?style=for-the-badge&logo=github)](https://github.com/ProKrish/supply-chain-sentinel)
[![Made with Gemini](https://img.shields.io/badge/AI-Gemini%202.5%20Pro-blue?style=for-the-badge&logo=google)](https://ai.google.dev/)

> 🏆 **Google Solution Challenge 2026** · Built with Google Gemini 2.5 Pro · Deployed on Vercel + Render · Made by **Krish Gupta**

---

## ⚡ For Judges — 3-Minute Walkthrough

> [!WARNING]
> **First load takes 30–50 seconds.** Render free tier spins down after inactivity.
> If the screen is blank — wait 40 seconds and refresh once. The backend is waking up.

1. **Open the live app** → [supply-chain-sentinel-rho.vercel.app](https://supply-chain-sentinel-rho.vercel.app)
2. **Login as Logistics Manager** — `manager@sentinel.com` / `Manager123!`
3. **Click any red or critical shipment** on the map → see the 5-factor SHAP-style risk breakdown
4. **Click "Analyse with AI"** → watch Gemini 2.5 Pro stream a live rerouting decision in real time
5. **Click "Inject Disruption"** → set Singapore, severity 0.8, Typhoon → watch BFS cascade re-score all downstream shipments automatically
6. **Visit the Analytics tab** → see the 24h risk trend, carrier reliability chart, and trade lane heat table

> **Read-Only Analyst view** — `analyst@sentinel.com` / `Analyst123!` (no AI agent or disruption injection access)

---

## 🔑 Test Credentials

| Role | Email | Password | Access |
| --- | --- | --- | --- |
| **Logistics Manager** | manager@sentinel.com | Manager123! | Full — map, AI agent, disruption injection, analytics |
| **Read-Only Analyst** | analyst@sentinel.com | Analyst123! | View only — map + analytics |

---

## 🌐 UN SDG Alignment

Built for **Google Solution Challenge 2026** — directly aligned with:

| Goal | How Supply Chain Sentinel contributes |
|------|---------------------------------------|
| **SDG 8** — Decent Work & Economic Growth | Prevents billions in annual supply chain losses; protects livelihoods and jobs in developing economies that depend on reliable global logistics networks |
| **SDG 9** — Industry, Innovation & Infrastructure | Builds resilient trade infrastructure with real-time AI-powered risk detection and automated rerouting across 20 global trade nodes and 15 carriers |
| **SDG 17** — Partnerships for the Goals | Enables transparent, cross-border trade coordination, reducing disruption friction in global supply chains that emerging economies critically depend on for export-led growth |

> Global supply chains connect over 800 million workers across developing nations. A single undetected disruption cascading through a major port like Singapore or Rotterdam can delay hundreds of shipments simultaneously — Supply Chain Sentinel detects and reroutes these cascades in real time before they become economic crises.

---

## 🌍 Live Links

|  | URL |
| --- | --- |
| **Frontend (Live App)** | https://supply-chain-sentinel-rho.vercel.app |
| **Backend API** | https://supply-chain-sentinel.onrender.com |
| **API Docs (Swagger)** | https://supply-chain-sentinel.onrender.com/docs |

---

## 🧠 What Is This?

Global supply chains lose billions annually to undetected disruptions — port congestion, geopolitical events, carrier failures, and extreme weather. Logistics managers receive no predictive warning, only reactive alerts after shipments are already delayed.

**Supply Chain Sentinel** solves this by:

- **Predicting** — Computing a live 5-factor risk score for every shipment across 20 global trade nodes
- **Detecting** — Propagating disruption cascades via BFS across the entire NetworkX trade graph
- **Rerouting** — Streaming AI-powered rerouting recommendations via Google Gemini 2.5 Pro in real time

Unlike enterprise tools like SAP TM or Oracle TMS that alert only after delays occur, Supply Chain Sentinel is **predictive and agentic** — it detects cascading risk before shipments are impacted, then autonomously reasons through rerouting options and streams its decision live.

---

## ✨ Features

| Feature | Description |
| --- | --- |
| 🗺️ **Live Shipment Map** | 500 shipments on a dark world map with color-coded risk markers (green / amber / red / critical) |
| 📊 **Dynamic Risk Scoring** | 5-factor composite score per shipment: congestion, weather, geopolitical, carrier reliability, time pressure |
| 🔬 **SHAP-Style Risk Breakdown** | Animated bars showing exactly which factor drives each shipment's risk, with primary driver callout |
| 🌊 **BFS Cascade Propagation** | Disruptions spread through the NetworkX trade graph and re-score all connected shipments automatically |
| ⚡ **Disruption Injection** | Manually inject events (type, node, severity 0.1–1.0) and watch cascades propagate in real time |
| 🔁 **Auto Disruption Simulator** | Random disruptions fire automatically to simulate live network stress |
| 🤖 **Gemini 2.5 Pro AI Agent** | Multi-tool rerouting agent with SSE streaming showing live reasoning steps |
| 🔄 **Gemini 2.5 Flash Fallback** | Automatic model switch if primary is rate-limited or unavailable |
| 🧭 **Alternative Route Scoring** | Agent evaluates multiple route options and selects the lowest-risk path |
| 📋 **Live Disruption Feed** | Scrolling event log with severity indicators, auto-refreshing every 15 seconds |
| 📈 **Analytics Dashboard** | Risk trend (24h LineChart), shipment status (PieChart), carrier reliability (BarChart), trade lane risk (Table) |
| 🔐 **Role-Based Access Control** | Auth0 JWT RS256 — Logistics Manager (full access) and Read-Only Analyst (view only) |
| ♿ **WCAG 2.1 AA Accessibility** | Aria labels, keyboard navigation, ESC modal close, visible focus rings |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   SUPPLY CHAIN SENTINEL                      │
└─────────────────────────────────────────────────────────────┘

┌─────────────┐    JWT Token    ┌──────────────────────────────┐
│   Auth0     │◄───────────────►│   React Frontend              │
│ (RS256 JWT) │                 │   Vite + Tailwind CSS         │
└─────────────┘                 │   react-leaflet + Recharts    │
                                └────────────┬─────────────────┘
                                             │ HTTPS REST + SSE
                                             ▼
                             ┌─────────────────────────────────┐
                             │         FastAPI Backend          │
                             │  auth.py        (Auth0 + RBAC)  │
                             │  risk_engine.py (NetworkX)      │
                             │  risk_propagator.py (BFS)       │
                             │  disruption_simulator.py        │
                             │  rerouting_agent.py (Gemini)    │
                             │  agent_tools.py (4 tools)       │
                             └──────────┬──────────────────────┘
                                        │
                    ┌───────────────────┼──────────────────┐
                    ▼                   ▼                  ▼
         ┌──────────────────┐ ┌──────────────────┐ ┌────────────┐
         │ Supabase         │ │ Google Gemini    │ │  slowapi   │
         │ PostgreSQL       │ │ 2.5 Pro (main)   │ │  Limiter   │
         │ 500 shipments    │ │ 2.5 Flash        │ └────────────┘
         │ 15 carriers      │ │ (auto fallback)  │
         │ 20 nodes         │ └──────────────────┘
         └──────────────────┘
```

---

## 🛠️ Tech Stack

### Backend

- **FastAPI** — REST API + SSE streaming (13 endpoints)
- **Supabase PostgreSQL** — Database (psycopg2 pooler port 6543)
- **NetworkX** — Trade network graph + BFS cascade propagator
- **Google Gemini 2.5 Pro** — AI rerouting agent with tool calling
- **Google Gemini 2.5 Flash** — Automatic fallback model
- **Auth0 JWT RS256** — Authentication + RBAC
- **slowapi** — Rate limiting
- **Pydantic v2** — Data validation

### Frontend

- **React 18 + Vite** — UI framework
- **Tailwind CSS v4** — Dark theme design system
- **react-leaflet** — Live shipment world map (CartoDB dark tiles)
- **Recharts** — Analytics visualizations
- **Auth0 React SDK** — Authentication flow

### Infrastructure

- **Render** — Backend cloud hosting
- **Vercel** — Frontend cloud hosting + CDN
- **GitHub** — Version control + CI/CD

---

## 📁 Project Structure

```
supply-chain-sentinel/
├── backend/
│   ├── main.py                  # FastAPI app, 13 endpoints
│   ├── auth.py                  # Auth0 JWT + RBAC
│   ├── database.py              # psycopg2 Supabase singleton
│   ├── models.py                # Pydantic v2 schemas
│   ├── risk_engine.py           # NetworkX graph risk scoring
│   ├── risk_propagator.py       # BFS cascade propagator
│   ├── disruption_simulator.py  # Chaos/disruption engine
│   ├── rerouting_agent.py       # Gemini 2.5 Pro agent + SSE
│   ├── agent_tools.py           # 4 tool handlers for agent
│   ├── requirements.txt
│   └── Procfile                 # Render deploy config
├── frontend/
│   └── src/
│       ├── api/client.js        # Axios + TokenBridge
│       ├── pages/
│       │   ├── LoginPage.jsx
│       │   ├── Dashboard.jsx
│       │   ├── Analytics.jsx
│       │   └── Callback.jsx
│       ├── components/
│       │   ├── Map/ShipmentMap.jsx
│       │   ├── Map/MapLegend.jsx
│       │   ├── Layout/AppHeader.jsx
│       │   ├── Risk/RiskBreakdown.jsx
│       │   └── ErrorBoundary.jsx
│       ├── main.jsx
│       └── App.jsx
│   ├── vercel.json              # Vercel deploy config
│   └── package.json
├── data/
│   └── generate.py              # Seeds Supabase database
└── README.md
```

---

## 🚀 Local Development Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- Supabase account and project
- Auth0 account and application
- Google AI Studio API key (Gemini)

### 1. Clone the Repository

```bash
git clone https://github.com/ProKrish/supply-chain-sentinel.git
cd supply-chain-sentinel
```

### 2. Backend Setup

```bash
cd backend
python -m venv venv

# Windows
venv\Scripts\activate

# Mac/Linux
source venv/bin/activate

pip install -r requirements.txt
```

Create `backend/.env`:

```env
GEMINI_API_KEY=your_gemini_api_key
AUTH0_DOMAIN=your_auth0_domain
AUTH0_CLIENT_ID=your_auth0_client_id
AUTH0_AUDIENCE=https://supply-chain-sentinel-api
DATABASE_URL=postgresql://postgres.xxxx:PASSWORD@aws-0-region.pooler.supabase.com:6543/postgres
SUPABASE_URL=your_supabase_url
SUPABASE_ANON_KEY=your_supabase_anon_key
ALLOWED_ORIGINS=http://localhost:5173
```

Run the backend:

```bash
python main.py
```

Backend runs at: `http://localhost:8002`
Swagger docs at: `http://localhost:8002/docs`

### 3. Seed the Database

```bash
cd data
python generate.py
```

This creates 500 shipments, 15 carriers, 20 trade nodes, and 12 trade lanes in Supabase.

### 4. Frontend Setup

```bash
cd frontend
npm install
```

Create `frontend/.env`:

```env
VITE_AUTH0_DOMAIN=your_auth0_domain
VITE_AUTH0_CLIENT_ID=your_auth0_client_id
VITE_AUTH0_AUDIENCE=https://supply-chain-sentinel-api
VITE_API_URL=http://localhost:8002
```

Run the frontend:

```bash
npm run dev
```

Frontend runs at: `http://localhost:5173`

---

## ☁️ Deployment

### Backend → Render

1. Go to [render.com](https://render.com) → New Web Service
2. Connect your GitHub repo
3. Set **Root Directory** to `backend`
4. **Build Command:** `pip install -r requirements.txt`
5. **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
6. Add all environment variables from `.env`
7. Set `ALLOWED_ORIGINS` to your Vercel URL
8. Deploy

### Frontend → Vercel

1. Go to [vercel.com](https://vercel.com) → New Project
2. Import your GitHub repo
3. Set **Root Directory** to `frontend`
4. Add all environment variables from `.env`
5. Set `VITE_API_URL` to your Render backend URL
6. Deploy

### Auth0 Configuration

In Auth0 dashboard → Applications → Settings, add your Vercel URL to:

- **Allowed Callback URLs:** `https://your-app.vercel.app/callback`
- **Allowed Logout URLs:** `https://your-app.vercel.app`
- **Allowed Web Origins:** `https://your-app.vercel.app`

---

## 📡 API Endpoints

| Method | Endpoint | Auth | Description |
| --- | --- | --- | --- |
| GET | `/` | None | Health check |
| GET | `/health` | None | Database connection check |
| GET | `/shipments` | ✅ | List shipments (filter by status, risk) |
| GET | `/shipments/{id}` | ✅ | Shipment detail + risk breakdown |
| GET | `/graph` | ✅ | Trade network nodes + edges |
| GET | `/disruptions/active` | ✅ | Active disruptions |
| GET | `/disruptions/history` | ✅ | Last 50 disruption events |
| POST | `/disruptions/inject` | ✅ Manager | Inject disruption event |
| POST | `/disruptions/auto` | ✅ Manager | Fire random disruption |
| POST | `/agent/reroute` | ✅ Manager | Trigger Gemini rerouting agent |
| GET | `/agent/stream` | ✅ Manager | SSE stream of agent reasoning |
| GET | `/analytics/risk-trend` | ✅ | 24h risk trend data |
| GET | `/me` | ✅ | Current user info + role |

---

## 🤖 How the AI Agent Works

The Gemini 2.5 Pro rerouting agent uses a **tool-calling loop** with 4 tools:

```
1. get_shipment_details   → Fetches full shipment + current risk score
2. get_alternative_routes → Finds routes avoiding disrupted nodes
3. score_route            → Scores each alternative for risk + transit time
4. commit_reroute         → Commits the best route decision
```

The entire reasoning chain streams live to the dashboard via **Server-Sent Events (SSE)**. If Gemini 2.5 Pro hits rate limits, the agent automatically falls back to **Gemini 2.5 Flash** and continues without interruption.

---

## 🗺️ Risk Scoring Model

Each shipment receives a composite risk score from 5 factors:

| Factor | Type | Source |
| --- | --- | --- |
| Port Congestion | Dynamic | Node disruption level |
| Weather Risk | Dynamic | Disruption type = weather |
| Geopolitical Risk | Dynamic | Disruption type = geopolitical |
| Carrier Reliability | Static | Carrier historical score |
| Time Pressure | Dynamic | Deadline vs. estimated arrival |

**Risk Levels:**

- 🟢 `0.0 – 0.29` Low
- 🟡 `0.3 – 0.59` Medium
- 🔴 `0.6 – 0.79` High
- 🚨 `0.8 – 1.0` Critical

---

## 🔮 Roadmap

### Phase 1 — Intelligence (3–6 months)

- [ ] XGBoost predictive ML risk model trained on historical disruption data
- [ ] Live port data (MarineTraffic vessel positions) + weather (OpenWeatherMap storm tracking)
- [ ] Gemini natural language query bar (Cmd+K) — ask "Which Mumbai shipments are at risk this week?"

### Phase 2 — Platform (6–12 months)

- [ ] WhatsApp + email push alerts when shipment risk crosses 0.7 threshold
- [ ] Multi-tenant SaaS with Auth0 organization isolation — each logistics firm gets own workspace
- [ ] Carrier intelligence history — track on-time rates over time, auto-prefer reliable carriers

### Phase 3 — Enterprise (12–24 months)

- [ ] SAP TM + Oracle TMS REST API connectors — Sentinel becomes the risk brain behind existing tools
- [ ] Cargo insurance risk API — license live risk scores to marine cargo insurers for dynamic premium pricing
- [ ] OFAC/EU sanctions compliance tracking — auto-flag shipments transiting sanctioned ports before departure

---

## 💼 Business Model

> *"Free users see risk. Paying users act on it."*

| Tier | Price | Key Features |
| --- | --- | --- |
| **Free** | ₹0/month | Map view, risk scores, analytics (50 shipments) |
| **Pro** | ₹4,067/month | AI agent (50 queries), disruption injection, BFS simulation, 500 shipments |
| **Enterprise** | Custom | Unlimited everything, ERP integration, multi-tenant isolation, SLA + priority support |

**Revenue streams:**
- Monthly SaaS subscriptions (primary)
- Per-query AI pricing above plan limits — ₹8.30/query
- Risk data licensing to cargo insurance underwriters (Phase 3)

**Scale-up cost (production):** Supabase Pro ₹2,075 + Render Starter ₹581 + Gemini at scale ~₹249 = ~₹2,905/month supporting thousands of users

---

## 👨‍💻 Built By

**Krish Gupta** — [GitHub](https://github.com/ProKrish)

Built for **Google Solution Challenge 2026** in 11 days.

---

## 📄 License

MIT License — feel free to fork, build, and ship.

---

**Supply Chain Sentinel** — Predict. Detect. Reroute.

*Powered by Google Gemini 2.5 Pro · Built for Google Solution Challenge 2026*
