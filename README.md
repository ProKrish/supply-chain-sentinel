# 🛰️ Supply Chain Sentinel

> **Predict. Detect. Reroute.**
> A real-time AI-powered supply chain disruption detection and rerouting platform.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Vercel-black?style=for-the-badge&logo=vercel)](https://supply-chain-sentinel-rho.vercel.app)
[![Backend](https://img.shields.io/badge/Backend-Render-purple?style=for-the-badge&logo=render)](https://supply-chain-sentinel.onrender.com/docs)
[![GitHub](https://img.shields.io/badge/GitHub-ProKrish-181717?style=for-the-badge&logo=github)](https://github.com/ProKrish/supply-chain-sentinel)
[![Made with Gemini](https://img.shields.io/badge/AI-Gemini%202.5%20Pro-blue?style=for-the-badge&logo=google)](https://ai.google.dev/)

---

## 🌍 Live Links

| | URL |
|---|---|
| **Frontend (Live App)** | https://supply-chain-sentinel-rho.vercel.app |
| **Backend API** | https://supply-chain-sentinel.onrender.com |
| **API Docs (Swagger)** | https://supply-chain-sentinel.onrender.com/docs |

> ⚠️ **Note:** First load may take 30–50 seconds. Render free tier spins down after inactivity — this is expected. Refresh once if the page hangs.

---

## 🧠 What Is This?

Global supply chains lose billions annually to undetected disruptions — port congestion, geopolitical events, carrier failures, and extreme weather. Logistics managers receive no predictive warning, only reactive alerts after shipments are already delayed.

**Supply Chain Sentinel** solves this by:

- **Predicting** — Computing a live 5-factor risk score for every shipment across 20 global trade nodes
- **Detecting** — Propagating disruption cascades via BFS across the entire NetworkX trade graph
- **Rerouting** — Streaming AI-powered rerouting recommendations via Google Gemini 2.5 Pro in real time

---

## ✨ Features

| Feature | Description |
|---|---|
| 🗺️ **Live Shipment Map** | 500 shipments on a dark world map with color-coded risk markers |
| 📊 **Dynamic Risk Scoring** | 5-factor composite score: congestion, weather, geopolitical, carrier, time pressure |
| 🔬 **SHAP-Style Risk Breakdown** | Animated bars showing exactly which factor is driving each shipment's risk |
| 🌊 **BFS Cascade Propagation** | Disruptions spread through the trade graph and re-score all connected shipments |
| ⚡ **Disruption Injection** | Manually inject events (type, node, severity) and watch cascades in real time |
| 🤖 **Gemini 2.5 Pro AI Agent** | Multi-tool rerouting agent with SSE streaming showing live reasoning steps |
| 🔄 **Gemini 2.5 Flash Fallback** | Automatic model switch if primary is rate-limited |
| 📈 **Analytics Dashboard** | Risk trend (24h), shipment status, carrier reliability, trade lane risk table |
| 🔐 **Role-Based Access** | Auth0 JWT — Logistics Manager (full) and Read-Only Analyst |
| ♿ **WCAG 2.1 AA** | Aria labels, keyboard navigation, ESC modal close |

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

## 🔑 Test Credentials

| Role | Email | Password | Access |
|---|---|---|---|
| **Logistics Manager** | manager@sentinel.com | Manager@123 | Full — map, AI agent, disruption injection, analytics |
| **Read-Only Analyst** | analyst@sentinel.com | Analyst@123 | View only — map + analytics |

---

## 📡 API Endpoints

| Method | Endpoint | Auth | Description |
|---|---|---|---|
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
|---|---|---|
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
- [ ] XGBoost predictive ML risk model on historical data
- [ ] Live port data (MarineTraffic) + weather (OpenWeatherMap)
- [ ] Gemini natural language query bar (Cmd+K)

### Phase 2 — Platform (6–12 months)
- [ ] WhatsApp + email push alerts on risk threshold breach
- [ ] Multi-tenant SaaS with Auth0 organization isolation
- [ ] Carrier intelligence history + reliability trend tracking

### Phase 3 — Enterprise (12–24 months)
- [ ] SAP TM + Oracle TMS REST API connectors
- [ ] Cargo insurance risk API (dynamic premium pricing)
- [ ] OFAC/EU sanctions compliance tracking

---

## 💼 Business Model

> *"Free users see risk. Paying users act on it."*

| Tier | Price | Key Features |
|---|---|---|
| **Free** | $0/month | Map view, risk scores, analytics (50 shipments) |
| **Pro** | $49/month | AI agent (50 queries), disruption injection, 500 shipments |
| **Enterprise** | Custom | Unlimited everything, ERP integration, multi-tenant, SLA |

---

## 👨‍💻 Built By

**Krish Gupta** — [GitHub](https://github.com/ProKrish)

Built for **Google Solution Challenge 2026** in 11 days.

---

## 📄 License

MIT License — feel free to fork, build, and ship.

---

<div align="center">

**Supply Chain Sentinel** — Predict. Detect. Reroute.

*Powered by Google Gemini 2.5 Pro*

</div>
