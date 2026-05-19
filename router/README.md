# Takeoff Trigger Router

> Stateless Cloudflare Worker that routes events from Takeoff products to
> notification channels. Holds no data. See `../docs/EVENTS.md` for the contract.

## What this is

The notification layer for the entire Takeoff LLC product portfolio. Any
product (Board Market, Command Center, Midnight, Poof E Gone, etc.) can fire
events here. The router verifies the signature, applies routing rules based on
severity and time, and dispatches to push/email/SMS channels.

## What this is not

- Not a queue (events fire or are dropped)
- Not a database (zero state, zero storage)
- Not a retry mechanism (publishers handle their own failure logic)
- Not an authentication system (HMAC signing only proves source)

## Deploy

Prerequisites: Node 20+, Cloudflare account (free tier is fine).

```bash
npm install -g wrangler
cd router
npm install
wrangler login

# Set secrets (one per source)
wrangler secret put BOARD_MARKET_HMAC_SECRET
# (paste the secret when prompted, same secret used in BOARD_MARKET_HMAC_SECRET env var on publisher)

# Email channel
wrangler secret put RESEND_API_KEY        # from resend.com — free tier
wrangler secret put USER_EMAIL            # your destination email

# Deploy
wrangler deploy
```

After deploy you'll get a URL like `https://takeoff-trigger-router.brian.workers.dev`.
Set that as `BOARD_MARKET_ROUTER_URL` on the Board Market side.

## Local development

```bash
wrangler dev
# Worker available at http://localhost:8787
```

Test with a signed event:

```bash
# From the Board Market repo root
python3 -c "
from triggers import emit
import os
os.environ['BOARD_MARKET_ROUTER_URL'] = 'http://localhost:8787'
os.environ['BOARD_MARKET_HMAC_SECRET'] = 'test-secret-do-not-use-in-prod'
emit('play.stop_hit', 'TEST NVDA stop hit', 'Test event from local dev', payload={'ticker': 'NVDA'})
"
```

## Rules engine

Routing logic is in `src/index.ts` under `ROUTING_RULES`. Edit, redeploy.

Default behavior:
- CRITICAL → push + email, bypasses quiet hours
- HIGH during market hours (9:30–4 ET) → push only
- HIGH outside market hours → email only
- MEDIUM / LOW / INFO → no notification (feed-only in the publishing app)

## Quiet Day toggle

If `QUIET_DAY_FLAG_URL` is configured, the router queries it on every event.
If the endpoint returns `{"quiet_day": true}`, only CRITICAL events fire.
Everything else is silently dropped. The publisher's dashboard remains the
source of truth.

## Adding a new source product

1. Generate a fresh HMAC secret (`openssl rand -base64 32`)
2. Add it to `wrangler.toml` documentation and `secretForSource()` in `src/index.ts`
3. `wrangler secret put MY_PRODUCT_HMAC_SECRET`
4. `wrangler deploy`
5. Register the source in `../docs/EVENTS.md` source registry
6. Implement publisher in the new product (model after `triggers/emit.py`)

## Security posture

- HMAC verification on every inbound event
- HTTPS enforced by Cloudflare
- No event content logged (Cloudflare logs only have status codes)
- Secrets stored in Cloudflare's encrypted secret store
- No database, no persistent state — compromise yields routing rules only
- Compromise of a publisher's secret affects only that source's emit capability
