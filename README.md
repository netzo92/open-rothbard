# open-rothbard

**Autonomous anarcho-capitalist economic agent framework.**

Named after [Murray Rothbard](https://en.wikipedia.org/wiki/Murray_Rothbard) — each agent instance is a sovereign economic entity with its own crypto wallet, memory, and profit motive. No central authority. Workers are hired via voluntary exchange, paid upfront from the agent's own treasury, and replaced on the free market when cheaper alternatives exist.

Inspired by OpenClaw but revenue-focused: the system's purpose is to generate profit, route earnings to its own USDC treasury, and self-fund its own expansion.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                 RothbardAgent                    │
│           (LangGraph state machine)              │
│                                                  │
│  check_treasury → scan_markets → rank_opps       │
│       → select_strategy (Claude LLM)             │
│          ↓                  ↓                    │
│   execute_strategy        idle                   │
│          ↓                                       │
│   update_memory → idle → (loop)                  │
└─────────────────────────────────────────────────┘
         ↕                        ↕
   CDP Wallet                Docker workers
   (USDC treasury)           (spawned per task)
         ↕                        ↕
  ChromaDB + SQLite          FastAPI x402 server
  (semantic + episodic       (sell intelligence
   memory)                    to other agents)
```

## Revenue Strategies

| Strategy | Source | Mechanism |
|---|---|---|
| `trade` | DeFiLlama | Yield farming on Base — highest APY pools |
| `freelance` | Upwork RSS | Bid + complete tasks autonomously via Claude |
| `arbitrage` | CEX/DEX | Cross-venue price gap execution |
| `content` | Google Trends + affiliates | SEO articles + affiliate revenue |

Add a new strategy: create `rothbard/revenue/my_strategy.py`, implement `RevenueStrategy`, decorate with `@register`.

---

## Quickstart

### Prerequisites
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (`pip install uv`)
- Docker (for worker containers)
- Anthropic API key
- Coinbase CDP API keys (optional — runs in stub mode without)

### Setup

```bash
git clone https://github.com/metehanozten/open-rothbard
cd open-rothbard

# Install dependencies
uv sync

# Configure
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY and CDP keys
```

### Run (testnet)

```bash
# Start support services
docker compose up redis chroma -d

# Run the agent
uv run python -m rothbard.main
```

### Run with Docker Compose (full stack)

```bash
docker compose up --build
```

The agent logs each cycle:
```
[09:41:23] INFO  Cycle 1 | Treasury: 100.00 USDC
[09:41:25] INFO  Scanner found 12 opportunities
[09:41:27] INFO  Strategy selected: trade — Aave USDC at 8.3% APY is the safest option
[09:41:28] INFO  Executed trade: Deployed 10.00 USDC into Aave...
```

### Tests

```bash
uv run pytest
```

---

## x402 Payment Server

The agent runs a FastAPI server on port `8402` that other agents or users can pay to query:

```bash
# Free: agent status
curl http://localhost:8402/x402/status

# Paid: current market intelligence (requires x402 USDC payment header)
curl http://localhost:8402/x402/intelligence \
  -H "X-Payment: <base64-encoded-payment-proof>"
```

---

## Project Structure

```
rothbard/
├── config.py               # pydantic-settings (all config from .env)
├── main.py                 # entrypoint
├── core/
│   ├── agent.py            # LangGraph graph builder
│   ├── state.py            # AgentState TypedDict
│   ├── nodes.py            # graph node functions
│   ├── edges.py            # conditional router
│   └── tools.py            # LLM @tool wrappers
├── finance/
│   ├── wallet.py           # CDP wallet management
│   ├── treasury.py         # P&L ledger + routing rules
│   └── x402.py             # FastAPI x402 payment server
├── markets/
│   ├── scanner.py          # aggregates all sources
│   ├── scorer.py           # risk-adjusted ROI ranking
│   └── sources/            # DeFi, Upwork, arbitrage, content
├── revenue/
│   ├── base.py             # RevenueStrategy ABC
│   ├── registry.py         # plugin system
│   └── {trading,freelance,arbitrage,content}.py
├── infra/
│   ├── docker_manager.py   # spawn/kill worker containers
│   └── resource_budget.py  # infra spend limits
├── memory/
│   ├── episodic.py         # SQLite event history
│   ├── semantic.py         # ChromaDB vector memory
│   └── working.py          # AgentState helpers
└── tools/
    ├── web.py              # async HTTP fetching
    ├── api_caller.py       # authenticated API calls
    └── code_exec.py        # sandboxed Python execution
```

---

## Philosophy

> "In the free market, the consumer is king." — Murray Rothbard

Each agent is a sovereign economic actor. It owns its private keys, makes its own decisions, and competes on merit. There's no subsidized behavior, no bailouts, no central coordinator. If a strategy loses money, the agent learns from it (episodic memory) and deprioritizes it. The market decides what works.

---

## License

MIT
