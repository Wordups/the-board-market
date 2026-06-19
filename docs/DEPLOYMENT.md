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
