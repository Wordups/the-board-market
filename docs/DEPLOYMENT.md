# Deployment architecture

## Recommended split

### GitHub Pages — public, static, read-only

The Pages artifact contains only:

- `index.html`
- `assets/`
- `data/board_today.json`

The workflow regenerates the public market snapshot before deployment. It runs
on pushes to `main`, manually through `workflow_dispatch`, and every weekday
before the US market opens.

The build also sets `window.BOARD_PUBLIC_STATIC = true`, which disables private
API controls even when Pages is served through a custom domain.

One-time repository setting: **Settings → Pages → Source → GitHub Actions**.

Expected URL: `https://wordups.github.io/the-board-market/`

### Private backend — not GitHub Pages

These features require FastAPI plus private, persistent storage:

- Paper Pilot state
- Schwab OAuth callback and encrypted tokens
- Account balances, positions, and transactions
- Fidelity imports
- Authentication

Do not publish `.env`, `.state/`, broker tokens, account identifiers, or personal
positions in a Pages artifact. The included workflow cannot access or package
those paths.

Keep the backend local while validating Paper Pilot. When remote access is
needed, deploy FastAPI to an authenticated service with persistent storage and
HTTPS, then register that HTTPS callback URL with Schwab. Order placement stays
disabled until the Phase 6 hard gate passes.

### Live cycle scheduling (PRIVATE ONLY)

`engine/live_cycle.py` runs the unattended daily LIVE cycle: refresh board →
place capped orders → reconcile. It needs Schwab tokens + `LIVE_TRADING_ENABLED`,
so it must run on the **private** machine, **never** on GitHub Actions.

Prereqs (one-time): complete the Schwab OAuth login (`/api/schwab/login`), set
`SCHWAB_ACCOUNT_HASH`, fund the account, set `LIVE_TRADING_ENABLED=true`, and keep
`LIVE_CAPITAL_CAP=100` until the model earns more. With the kill switch off the
script is a safe no-op (refreshes the board, places nothing).

Linux/macOS cron — weekdays 9:40 AM ET (pre-noon, post-open):

```
40 9 * * 1-5  cd /path/to/the-board-market && . .venv/bin/activate && python engine/live_cycle.py >> .state/live_cycle.log 2>&1
```

Windows Task Scheduler:

```
schtasks /Create /TN "BoardMarketLive" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 09:40 ^
  /TR "cmd /c cd /d C:\path\to\the-board-market && .venv\Scripts\python engine\live_cycle.py"
```

Watch `.state/live_cycle.log` for the first several runs before trusting it unattended.
