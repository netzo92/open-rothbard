"""Agent dashboard — served at /dashboard on the existing x402 FastAPI server.

/dashboard          → HTML page (auto-refreshes via /dashboard/api/stats)
/dashboard/api/stats → JSON snapshot of agent state for the page to consume
"""
from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from rothbard.memory import episodic

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# In-memory snapshot updated by node functions each cycle
_live: dict[str, Any] = {}


def update_live(**kwargs: Any) -> None:
    """Called by graph nodes to push live state into the dashboard."""
    _live.update(kwargs)

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Rothbard Agent Dashboard</title>
  <style>
    :root {
      --bg: #0d0d0d;
      --surface: #161616;
      --border: #2a2a2a;
      --accent: #22c55e;
      --accent-dim: #16a34a;
      --muted: #6b7280;
      --text: #e5e7eb;
      --red: #ef4444;
      --yellow: #eab308;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
      font-size: 13px;
      line-height: 1.6;
      padding: 24px;
    }
    header {
      display: flex;
      align-items: baseline;
      gap: 16px;
      margin-bottom: 24px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 12px;
    }
    header h1 { font-size: 18px; color: var(--accent); }
    header .subtitle { color: var(--muted); font-size: 12px; }
    #last-updated { margin-left: auto; color: var(--muted); font-size: 11px; }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 24px;
    }
    .card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 14px 16px;
    }
    .card-label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .05em; }
    .card-value { font-size: 22px; margin-top: 4px; color: var(--accent); }
    .card-value.neutral { color: var(--text); }
    .card-value.warning { color: var(--yellow); }
    section { margin-bottom: 28px; }
    section h2 {
      font-size: 13px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: .08em;
      margin-bottom: 10px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 6px;
      overflow: hidden;
    }
    th {
      text-align: left;
      padding: 8px 12px;
      font-size: 11px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: .05em;
      border-bottom: 1px solid var(--border);
    }
    td {
      padding: 8px 12px;
      border-bottom: 1px solid var(--border);
      color: var(--text);
      vertical-align: top;
      max-width: 320px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: rgba(255,255,255,.02); }
    .badge {
      display: inline-block;
      padding: 1px 7px;
      border-radius: 99px;
      font-size: 11px;
      font-weight: 600;
    }
    .badge-green { background: rgba(34,197,94,.15); color: var(--accent); }
    .badge-red   { background: rgba(239,68,68,.15);  color: var(--red); }
    .badge-yellow{ background: rgba(234,179,8,.15);  color: var(--yellow); }
    .badge-grey  { background: rgba(107,114,128,.15);color: var(--muted); }
    .empty { color: var(--muted); font-size: 12px; padding: 16px 12px; }
    .strategy { color: var(--accent-dim); }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
    .wallet-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 14px 16px;
      flex: 1;
      min-width: 0;
    }
    .wallet-label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .05em; }
    .wallet-network { display: inline-block; padding: 1px 8px; border-radius: 99px; font-size: 11px; font-weight: 700; margin-left: 6px; }
    .wallet-network.mainnet { background: rgba(239,68,68,.2); color: var(--red); }
    .wallet-network.testnet { background: rgba(34,197,94,.15); color: var(--accent); }
    .wallet-addr {
      font-family: inherit;
      font-size: 12px;
      color: var(--text);
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 6px 10px;
      margin-top: 8px;
      word-break: break-all;
      width: 100%;
      display: block;
    }
    .wallet-actions { display: flex; gap: 8px; margin-top: 8px; align-items: center; }
    .copy-btn {
      background: rgba(34,197,94,.1);
      border: 1px solid rgba(34,197,94,.3);
      color: var(--accent);
      border-radius: 4px;
      padding: 3px 10px;
      font-size: 11px;
      font-family: inherit;
      cursor: pointer;
    }
    .copy-btn:hover { background: rgba(34,197,94,.2); }
    .copy-btn.copied { color: var(--muted); border-color: var(--border); }
    .network-banner {
      padding: 10px 16px;
      border-radius: 6px;
      margin-bottom: 12px;
      font-size: 12px;
      font-weight: 600;
    }
    .network-banner.mainnet { background: rgba(239,68,68,.12); border: 1px solid rgba(239,68,68,.4); color: var(--red); }
    .network-banner.testnet { background: rgba(34,197,94,.08); border: 1px solid rgba(34,197,94,.2); color: var(--accent); }
    #error-banner {
      display: none;
      background: rgba(239,68,68,.1);
      border: 1px solid var(--red);
      border-radius: 6px;
      padding: 10px 14px;
      color: var(--red);
      margin-bottom: 16px;
    }
    #approvals-section { display: none; }
    .approval-card {
      background: var(--surface);
      border: 1px solid rgba(239,68,68,.5);
      border-radius: 6px;
      padding: 14px 16px;
      margin-bottom: 10px;
      animation: pulse-border 2s ease-in-out infinite;
    }
    @keyframes pulse-border {
      0%, 100% { border-color: rgba(239,68,68,.5); }
      50%       { border-color: rgba(239,68,68,.9); }
    }
    .approval-header {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 10px;
    }
    .approval-title { font-weight: 700; font-size: 13px; flex: 1; }
    .approval-details {
      font-size: 11px;
      color: var(--muted);
      margin-bottom: 12px;
      display: grid;
      grid-template-columns: max-content 1fr;
      gap: 2px 12px;
    }
    .approval-details dt { font-weight: 600; text-transform: capitalize; }
    .approval-details dd { color: var(--text); word-break: break-all; }
    .approval-actions { display: flex; gap: 8px; }
    .approve-btn, .deny-btn {
      padding: 5px 16px;
      border-radius: 4px;
      font-family: inherit;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
      border: none;
    }
    .approve-btn {
      background: rgba(34,197,94,.2);
      color: var(--accent);
      border: 1px solid rgba(34,197,94,.4);
    }
    .approve-btn:hover { background: rgba(34,197,94,.35); }
    .deny-btn {
      background: rgba(239,68,68,.15);
      color: var(--red);
      border: 1px solid rgba(239,68,68,.35);
    }
    .deny-btn:hover { background: rgba(239,68,68,.3); }
  </style>
</head>
<body>
  <header>
    <h1>⚡ Rothbard</h1>
    <span class="subtitle">Autonomous Economic Agent</span>
    <span id="last-updated">loading…</span>
  </header>

  <div id="error-banner">Could not reach /dashboard/api/stats — is the server running?</div>

  <section id="approvals-section">
    <h2 style="color:var(--red);">⚠ Pending Approvals</h2>
    <div id="approvals-list"></div>
  </section>

  <div class="grid" id="stat-cards">
    <div class="card"><div class="card-label">Cycle</div><div class="card-value neutral" id="stat-cycle">—</div></div>
    <div class="card"><div class="card-label">EVM Balance</div><div class="card-value" id="stat-evm">—</div></div>
    <div class="card"><div class="card-label">Confirmed Income</div><div class="card-value" id="stat-income">—</div></div>
    <div class="card"><div class="card-label">Total Expenses</div><div class="card-value warning" id="stat-expenses">—</div></div>
    <div class="card"><div class="card-label">Bounties Owed</div><div class="card-value warning" id="stat-owed" title="Expected from open+merged PRs, not yet received on-chain">—</div></div>
    <div class="card"><div class="card-label">Open PRs</div><div class="card-value neutral" id="stat-prs">—</div></div>
    <div class="card"><div class="card-label">Last Strategy</div><div class="card-value neutral strategy" id="stat-strategy">—</div></div>
  </div>

  <section id="wallets-section" style="display:none;">
    <h2>Treasury Wallets</h2>
    <div id="network-banner" class="network-banner"></div>
    <div style="display:flex;gap:12px;flex-wrap:wrap;">
      <div class="wallet-card">
        <div class="wallet-label">
          Solana
          <span id="sol-network-badge" class="wallet-network">—</span>
        </div>
        <code class="wallet-addr" id="sol-address">—</code>
        <div class="wallet-actions">
          <button class="copy-btn" onclick="copyAddr('sol-address', this)">Copy address</button>
          <a id="sol-explorer" href="#" target="_blank" style="font-size:11px;">View on Explorer ↗</a>
        </div>
      </div>
      <div class="wallet-card">
        <div class="wallet-label">
          Base / EVM
          <span id="evm-network-badge" class="wallet-network">—</span>
        </div>
        <code class="wallet-addr" id="evm-address">—</code>
        <div class="wallet-actions">
          <button class="copy-btn" onclick="copyAddr('evm-address', this)">Copy address</button>
          <a id="evm-explorer" href="#" target="_blank" style="font-size:11px;">View on Basescan ↗</a>
        </div>
      </div>
    </div>
  </section>

  <section>
    <h2>Recent Decisions</h2>
    <table id="episodes-table">
      <thead>
        <tr>
          <th>Cycle</th>
          <th>Strategy</th>
          <th>Outcome</th>
          <th>Action</th>
          <th>Time</th>
        </tr>
      </thead>
      <tbody id="episodes-body"><tr><td colspan="5" class="empty">Loading…</td></tr></tbody>
    </table>
  </section>

  <section>
    <h2>Pending GitHub PRs</h2>
    <table id="prs-table">
      <thead>
        <tr>
          <th>Repo</th>
          <th>Issue</th>
          <th>Expected Bounty</th>
          <th>Status</th>
          <th>Opened</th>
          <th>PR</th>
        </tr>
      </thead>
      <tbody id="prs-body"><tr><td colspan="6" class="empty">Loading…</td></tr></tbody>
    </table>
  </section>

  <section>
    <h2>Current Opportunities</h2>
    <div id="selection-reasoning" style="display:none;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:10px 14px;margin-bottom:10px;color:var(--muted);font-size:12px;"></div>
    <table id="opps-table">
      <thead>
        <tr>
          <th>Type</th>
          <th>Title</th>
          <th>Score</th>
          <th>ROI</th>
          <th>Risk</th>
          <th>Cost</th>
          <th>Status</th>
          <th>Reason</th>
        </tr>
      </thead>
      <tbody id="opps-body"><tr><td colspan="8" class="empty">Waiting for first scan…</td></tr></tbody>
    </table>
  </section>

  <section>
    <h2>Recent Ledger</h2>
    <table id="ledger-table">
      <thead>
        <tr>
          <th>Direction</th>
          <th>Category</th>
          <th>Amount (USDC)</th>
          <th>Strategy</th>
          <th>Details</th>
          <th>Time</th>
        </tr>
      </thead>
      <tbody id="ledger-body"><tr><td colspan="6" class="empty">Loading…</td></tr></tbody>
    </table>
  </section>

<script>
  const REFRESH_MS = 30_000;

  function badge(text, color) {
    return `<span class="badge badge-${color}">${text}</span>`;
  }

  function outcomeColor(outcome) {
    if (outcome === 'success') return 'green';
    if (outcome === 'failure') return 'red';
    return 'grey';
  }

  function statusColor(status) {
    if (status === 'merged') return 'green';
    if (status === 'closed') return 'red';
    return 'yellow';
  }

  function fmtTs(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleString();
  }

  function truncate(str, n) {
    if (!str) return '—';
    return str.length > n ? str.slice(0, n) + '…' : str;
  }

  function copyAddr(elId, btn) {
    const text = document.getElementById(elId).textContent;
    navigator.clipboard.writeText(text).then(() => {
      btn.textContent = 'Copied!';
      btn.classList.add('copied');
      setTimeout(() => { btn.textContent = 'Copy address'; btn.classList.remove('copied'); }, 2000);
    });
  }

  function renderWallets(d) {
    if (!d.sol_address && !d.evm_address) return;
    document.getElementById('wallets-section').style.display = 'block';

    const isMainnet = (d.sol_network === 'mainnet-beta') || (d.evm_network && !d.evm_network.includes('sepolia') && !d.evm_network.includes('testnet'));
    const banner = document.getElementById('network-banner');
    banner.className = 'network-banner ' + (isMainnet ? 'mainnet' : 'testnet');
    banner.textContent = isMainnet
      ? '🚨 MAINNET — transactions use real funds. Double-check addresses before sending.'
      : '✅ TESTNET — safe to experiment. Do not send real funds here.';

    // Solana — explicit cluster map so the URL is never ambiguous
    if (d.sol_address) {
      document.getElementById('sol-address').textContent = d.sol_address;
      const solNet = d.sol_network || 'mainnet-beta';
      const solBadge = document.getElementById('sol-network-badge');
      solBadge.textContent = solNet;
      solBadge.className = 'wallet-network ' + (solNet === 'mainnet-beta' ? 'mainnet' : 'testnet');
      // explorer.solana.com uses ?cluster=devnet / ?cluster=testnet; mainnet needs no param
      const SOL_CLUSTER = { 'mainnet-beta': '', 'devnet': '?cluster=devnet', 'testnet': '?cluster=testnet' };
      const solCluster = (solNet in SOL_CLUSTER) ? SOL_CLUSTER[solNet] : ('?cluster=' + solNet);
      document.getElementById('sol-explorer').href =
        `https://explorer.solana.com/address/${d.sol_address}${solCluster}`;
    }

    // EVM / Base — explicit network → explorer mapping
    if (d.evm_address) {
      document.getElementById('evm-address').textContent = d.evm_address;
      const evmNet = d.evm_network || '';
      const evmBadge = document.getElementById('evm-network-badge');
      evmBadge.textContent = evmNet;
      const evmIsTestnet = evmNet.includes('sepolia') || evmNet.includes('testnet') || evmNet.includes('goerli');
      evmBadge.className = 'wallet-network ' + (evmIsTestnet ? 'testnet' : 'mainnet');
      const EVM_EXPLORER = {
        'base-mainnet': 'https://basescan.org',
        'base-sepolia': 'https://sepolia.basescan.org',
        'ethereum': 'https://etherscan.io',
        'ethereum-goerli': 'https://goerli.etherscan.io',
      };
      const evmBase = EVM_EXPLORER[evmNet] || (evmIsTestnet ? 'https://sepolia.basescan.org' : 'https://basescan.org');
      document.getElementById('evm-explorer').href = `${evmBase}/address/${d.evm_address}`;
    }
  }

  async function refresh() {
    try {
      const resp = await fetch('/dashboard/api/stats');
      if (!resp.ok) throw new Error(resp.statusText);
      const d = await resp.json();
      document.getElementById('error-banner').style.display = 'none';

      // Wallet deposit section
      renderWallets(d);

      // Cards
      document.getElementById('stat-cycle').textContent = d.cycle ?? '—';
      document.getElementById('stat-evm').textContent = d.evm_balance_usdc != null
        ? `$${parseFloat(d.evm_balance_usdc).toFixed(2)}`
        : '—';
      document.getElementById('stat-income').textContent = `$${parseFloat(d.total_income_usdc || 0).toFixed(2)}`;
      document.getElementById('stat-expenses').textContent = `$${parseFloat(d.total_expenses_usdc || 0).toFixed(2)}`;
      document.getElementById('stat-owed').textContent = `$${parseFloat(d.bounties_owed_usdc || 0).toFixed(2)}`;
      document.getElementById('stat-prs').textContent = d.open_pr_count ?? 0;
      document.getElementById('stat-strategy').textContent = d.last_strategy ?? '—';

      // Episodes
      const epBody = document.getElementById('episodes-body');
      if (!d.recent_episodes || d.recent_episodes.length === 0) {
        epBody.innerHTML = '<tr><td colspan="5" class="empty">No episodes yet.</td></tr>';
      } else {
        epBody.innerHTML = d.recent_episodes.map(e => `
          <tr>
            <td>${e.cycle}</td>
            <td>${e.strategy || '—'}</td>
            <td>${badge(e.outcome, outcomeColor(e.outcome))}</td>
            <td title="${e.action || ''}">${truncate(e.action, 70)}</td>
            <td>${fmtTs(e.ts)}</td>
          </tr>
        `).join('');
      }

      // Pending PRs
      const prBody = document.getElementById('prs-body');
      if (!d.pending_prs || d.pending_prs.length === 0) {
        prBody.innerHTML = '<tr><td colspan="6" class="empty">No open PRs.</td></tr>';
      } else {
        prBody.innerHTML = d.pending_prs.map(pr => `
          <tr>
            <td>${pr.repo}</td>
            <td>#${pr.issue_number}</td>
            <td>$${parseFloat(pr.expected_bounty_usdc).toFixed(2)}</td>
            <td>${badge(pr.status, statusColor(pr.status))}</td>
            <td>${fmtTs(pr.opened_at)}</td>
            <td><a href="${pr.pr_url}" target="_blank">view</a></td>
          </tr>
        `).join('');
      }

      // Opportunities
      const reasoningEl = document.getElementById('selection-reasoning');
      if (d.selection_reasoning) {
        reasoningEl.style.display = 'block';
        reasoningEl.textContent = '⚖ LLM reasoning: ' + d.selection_reasoning;
      } else {
        reasoningEl.style.display = 'none';
      }
      const oppsBody = document.getElementById('opps-body');
      if (!d.opportunity_decisions || d.opportunity_decisions.length === 0) {
        oppsBody.innerHTML = '<tr><td colspan="8" class="empty">No opportunities in last scan.</td></tr>';
      } else {
        oppsBody.innerHTML = d.opportunity_decisions.map(o => {
          const statusColor = o.status === 'selected' ? 'green' : o.status === 'wait' ? 'grey' : 'yellow';
          return `<tr>
            <td>${badge(o.type, 'grey')}</td>
            <td title="${o.title}" style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${o.title}</td>
            <td>${o.score.toFixed(3)}</td>
            <td>$${o.roi.toFixed(2)}</td>
            <td>${o.risk}/10</td>
            <td>$${o.cost.toFixed(2)}</td>
            <td>${badge(o.status, statusColor)}</td>
            <td title="${o.reason}" style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted);">${o.reason}</td>
          </tr>`;
        }).join('');
      }

      // Ledger
      const ledgerBody = document.getElementById('ledger-body');
      if (!d.recent_ledger || d.recent_ledger.length === 0) {
        ledgerBody.innerHTML = '<tr><td colspan="6" class="empty">No ledger entries yet.</td></tr>';
      } else {
        ledgerBody.innerHTML = d.recent_ledger.map(l => `
          <tr>
            <td>${badge(l.direction, l.direction === 'credit' ? 'green' : 'red')}</td>
            <td>${l.category}</td>
            <td>${parseFloat(l.amount_usdc).toFixed(4)}</td>
            <td>${l.strategy || '—'}</td>
            <td title="${l.details || ''}">${truncate(l.details, 60)}</td>
            <td>${fmtTs(l.ts)}</td>
          </tr>
        `).join('');
      }

      document.getElementById('last-updated').textContent =
        'Updated ' + new Date().toLocaleTimeString();
    } catch (err) {
      document.getElementById('error-banner').style.display = 'block';
      document.getElementById('last-updated').textContent = 'Error — retrying…';
    }
  }

  // ── approval polling (every 3 s, independent of main refresh) ──────────────

  const RISK_COLOR = { low: 'green', medium: 'yellow', high: 'red' };

  async function refreshApprovals() {
    try {
      const resp = await fetch('/dashboard/api/approvals');
      if (!resp.ok) return;
      const approvals = await resp.json();
      const section = document.getElementById('approvals-section');
      const list = document.getElementById('approvals-list');

      if (!approvals || approvals.length === 0) {
        section.style.display = 'none';
        list.innerHTML = '';
        return;
      }
      section.style.display = 'block';

      // Re-render only if IDs changed (avoid button flicker)
      const existing = new Set([...list.querySelectorAll('.approval-card')].map(el => el.dataset.id));
      const incoming = new Set(approvals.map(a => a.id));

      // Remove resolved cards
      for (const el of list.querySelectorAll('.approval-card')) {
        if (!incoming.has(el.dataset.id)) el.remove();
      }
      // Add new cards
      for (const a of approvals) {
        if (existing.has(a.id)) continue;
        const riskColor = RISK_COLOR[a.risk] || 'yellow';
        const detailRows = Object.entries(a.details || {})
          .map(([k, v]) => `<dt>${k.replace(/_/g, ' ')}</dt><dd>${v}</dd>`)
          .join('');
        const card = document.createElement('div');
        card.className = 'approval-card';
        card.dataset.id = a.id;
        card.innerHTML = `
          <div class="approval-header">
            <span>${a.action_type === 'transaction' ? '💸' : a.action_type === 'container' ? '🐳' : a.action_type === 'strategy' ? '📈' : '⚡'}</span>
            <span class="approval-title">${a.title}</span>
            ${badge(a.risk.toUpperCase(), riskColor)}
          </div>
          <dl class="approval-details">${detailRows}</dl>
          <div class="approval-actions">
            <button class="approve-btn" onclick="resolveApproval('${a.id}', true, this.parentElement)">✓ Approve</button>
            <button class="deny-btn" onclick="resolveApproval('${a.id}', false, this.parentElement)">✗ Deny</button>
          </div>
        `;
        list.appendChild(card);
      }
    } catch (_) { /* server not ready */ }
  }

  async function resolveApproval(id, approved, actionsEl) {
    actionsEl.innerHTML = '<span style="color:var(--muted);font-size:12px;">Submitting…</span>';
    try {
      const resp = await fetch(`/dashboard/api/approvals/${id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved }),
      });
      if (!resp.ok) throw new Error(resp.statusText);
      // Card will disappear on the next poll
    } catch (err) {
      actionsEl.innerHTML = `<span style="color:var(--red);font-size:12px;">Error: ${err.message}</span>`;
    }
  }

  refresh();
  setInterval(refresh, REFRESH_MS);
  refreshApprovals();
  setInterval(refreshApprovals, 3_000);
</script>
</body>
</html>
"""


@router.get("", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    """Serve the agent dashboard UI."""
    return HTMLResponse(content=_HTML)


@router.get("/api/stats")
async def stats() -> dict[str, Any]:
    """JSON snapshot consumed by the dashboard page every 30 s."""
    try:
        episodes = await episodic.recent_episodes(n=20)
        open_prs = await episodic.get_open_prs()
        all_prs = await _all_prs(n=50)
        ledger = await _recent_ledger(n=20)
        income, expenses = await _ledger_totals()
    except Exception:
        # DB not ready yet
        episodes, open_prs, all_prs, ledger, income, expenses = [], [], [], [], Decimal("0"), Decimal("0")

    last_ep = episodes[0] if episodes else None

    # Bounties we believe we are owed: open + merged PRs (not closed/rejected)
    owed = sum(
        Decimal(pr.expected_bounty_usdc)
        for pr in all_prs
        if pr.status in ("open", "merged")
    )

    return {
        "cycle": last_ep.cycle if last_ep else 0,
        "evm_balance_usdc": None,  # filled by wallet at runtime
        "total_income_usdc": str(income),
        "total_expenses_usdc": str(expenses),
        "bounties_owed_usdc": str(owed),
        "open_pr_count": len(open_prs),
        "last_strategy": last_ep.strategy if last_ep else None,
        # live state pushed by nodes each cycle
        "selection_reasoning": _live.get("selection_reasoning"),
        "opportunity_decisions": _live.get("opportunity_decisions", []),
        # wallet deposit info
        "sol_address": _live.get("sol_address"),
        "sol_network": _live.get("sol_network"),
        "evm_address": _live.get("evm_address"),
        "evm_network": _live.get("evm_network"),
        "recent_episodes": [
            {
                "cycle": ep.cycle,
                "strategy": ep.strategy,
                "outcome": ep.outcome,
                "action": ep.action,
                "ts": ep.ts.isoformat() if ep.ts else None,
            }
            for ep in episodes
        ],
        "pending_prs": [
            {
                "repo": pr.repo,
                "issue_number": pr.issue_number,
                "expected_bounty_usdc": pr.expected_bounty_usdc,
                "status": pr.status,
                "opened_at": pr.opened_at.isoformat() if pr.opened_at else None,
                "pr_url": pr.pr_url,
            }
            for pr in all_prs
        ],
        "recent_ledger": ledger,
    }


# ── audit approval endpoints ──────────────────────────────────────────────────


class ApprovalRequest(BaseModel):
    approved: bool


@router.get("/api/approvals")
async def get_approvals() -> list[dict]:
    """Return list of pending audit actions waiting for operator approval."""
    from rothbard.core.audit import get_pending_approvals
    return get_pending_approvals()


@router.post("/api/approvals/{approval_id}")
async def post_approval(approval_id: str, body: ApprovalRequest) -> dict:
    """Approve or deny a pending audit action."""
    from rothbard.core.audit import resolve_approval
    ok = resolve_approval(approval_id, body.approved)
    if not ok:
        raise HTTPException(status_code=404, detail="Approval ID not found")
    return {"ok": True, "approved": body.approved}


# ── helpers ───────────────────────────────────────────────────────────────────


async def _all_prs(n: int = 50) -> list:
    from sqlalchemy import select
    from rothbard.memory.episodic import PendingPR, async_session

    async with async_session() as session:
        result = await session.execute(
            select(PendingPR).order_by(PendingPR.opened_at.desc()).limit(n)
        )
        return result.scalars().all()


async def _recent_ledger(n: int = 20) -> list[dict]:
    from sqlalchemy import select
    from rothbard.memory.episodic import LedgerEntry, async_session

    async with async_session() as session:
        result = await session.execute(
            select(LedgerEntry).order_by(LedgerEntry.ts.desc()).limit(n)
        )
        rows = result.scalars().all()

    return [
        {
            "direction": r.direction,
            "category": r.category,
            "amount_usdc": r.amount_usdc,
            "strategy": r.strategy,
            "details": r.details,
            "ts": r.ts.isoformat() if r.ts else None,
        }
        for r in rows
    ]


async def _ledger_totals() -> tuple[Decimal, Decimal]:
    from sqlalchemy import func, select
    from rothbard.memory.episodic import LedgerEntry, async_session

    async with async_session() as session:
        result = await session.execute(
            select(LedgerEntry.direction, func.sum(LedgerEntry.amount_usdc))
            .group_by(LedgerEntry.direction)
        )
        rows = result.all()

    income = Decimal("0")
    expenses = Decimal("0")
    for direction, total in rows:
        if total is None:
            continue
        if direction == "credit":
            income = Decimal(str(total))
        elif direction == "debit":
            expenses = Decimal(str(total))

    return income, expenses
