# EVENTS.md

> The contract between Takeoff LLC products. Every system that wants to notify
> the End User, or coordinate with another product, emits events to the router
> using this schema. The router holds no data. Subscribers handle their own state.
>
> Treat this doc the way you'd treat an XSIAM rule schema — version it carefully,
> never delete a field, only add. Breaking changes are expensive once products
> depend on it.

---

## The principle

A stateless event bus that lets independent Takeoff products talk without
direct coupling. The Board Market doesn't import Command Center code; it emits
an event, and if Command Center is listening, it acts.

**Publishers** fire events. **Subscribers** receive events. **The router**
routes. Nobody stores history except the publisher in its own DB.

## The envelope

Every event MUST conform to this envelope. Field order doesn't matter; field
presence does.

```json
{
  "schema_version": "1",
  "event_id": "01HXJ8KQZ3V8N7M2P4R6T9W3YA",
  "ts": "2026-05-18T19:32:00.000Z",
  "src": "board-market",
  "type": "play.stop_hit",
  "type_version": 1,
  "sev": "CRITICAL",
  "title": "NVDA stop hit",
  "body": "Exited at $184.50. P/L: -$13.60.",
  "deeplink": "https://wordups.github.io/the-board-market/plays/42",
  "payload": {
    "play_id": 42,
    "ticker": "NVDA",
    "exit_price": 184.50,
    "exit_reason": "STOP",
    "dollar_pnl": -13.60
  },
  "signature": "hmac-sha256-base64..."
}
```

### Field reference

| Field | Type | Required | Notes |
|---|---|---|---|
| `schema_version` | string | yes | Envelope version. Currently `"1"`. Bumped only for breaking envelope changes (not payload changes). |
| `event_id` | string (ULID) | yes | Unique per event. Subscribers use for idempotency. Use ULID, not UUID — sortable by time. |
| `ts` | ISO8601 UTC | yes | Event occurrence time, not delivery time. Always UTC, always trailing `Z`. |
| `src` | string | yes | Publisher product identifier. See registry below. |
| `type` | string | yes | `<resource>.<action>` within source's namespace. See type registry. |
| `type_version` | integer | yes | Version of this specific event type. Increment when payload shape changes. |
| `sev` | enum | yes | `CRITICAL` · `HIGH` · `MEDIUM` · `LOW` · `INFO` |
| `title` | string ≤80 chars | yes | Human-readable headline. Used as notification title. |
| `body` | string ≤300 chars | yes | Human-readable detail. Used as notification body. |
| `deeplink` | URL | no | Where to send the user when they tap the notification. |
| `payload` | object | no | Structured data for subscribers. Shape defined per type. |
| `signature` | string | yes | HMAC-SHA256 of canonical JSON, base64-encoded. See signing below. |

### Why ULID instead of UUID

ULIDs sort by time. When the router logs an error and you grep for events near
a timestamp, sortable IDs save you. UUIDs are random and force you to look up
the ts field separately. Small detail, real impact in incident response.

---

## Source registry

The `src` field MUST be one of:

| `src` | Product | Domain |
|---|---|---|
| `board-market` | The Board Market | Trading signals, plays, P/L |
| `board-system` | The Board System | Sports picks |
| `command-center` | Command Center | Financial dashboard |
| `midnight` | Midnight | Policy intelligence |
| `poof-e-gone` | Poof E Gone | IT asset disposal business |
| `stitchem` | STITCHem | Subscription box |
| `courtflow-pro` | CourtFlow Pro | Basketball trainer OS |
| `grind-squad` | GRIND SQUAD | Fitness gamification |
| `wordup` | WordUp | Prompt-to-build OS |

Adding a new source: append to this list, never reuse a retired source name.
Retired sources stay in the registry forever for historical reference.

---

## Type naming convention

`<resource>.<action>` within the source's namespace. Past-tense verbs.

Examples by source:

### `board-market`
- `play.created` — new play logged to ledger
- `play.stop_hit` — play exited via stop loss
- `play.target_hit` — play exited via take profit
- `play.time_exit` — play closed after max hold
- `play.cancelled` — play voided before entry
- `board.frozen` — daily board frozen at 9:30 ET
- `board.published` — pre-market board ready at 7:30 ET
- `signal.score_changed` — open play's score moved ≥10 pts
- `signal.congressional_cluster` — 3+ members bought ticker in 30d
- `signal.earnings_proximity` — open play within 5 days of earnings
- `signal.insider_buy` — Form 4 buy by officer/director >$50K
- `risk.drawdown_threshold` — bankroll dropped past 15%/30%/50% threshold
- `risk.position_limit` — would exceed max concurrent limit

### `command-center`
- `bill.payment_due` — bill within 5 days
- `bill.payment_failed` — autopay declined
- `credit.score_changed` — score moved ≥10 pts
- `account.balance_low` — checking below threshold
- `cashflow.deficit_projected` — projected negative balance

### `midnight`
- `audit.framework_gap` — control mapping gap detected
- `audit.deadline_approaching` — compliance deadline within 30 days
- `report.generated` — gap analysis output ready

### `poof-e-gone`
- `lead.received` — new business inquiry
- `contract.awarded` — SAM.gov contract win
- `invoice.paid` — customer payment received
- `pickup.scheduled` — service appointment confirmed

Naming rules:
- Past tense for things that happened (`payment_failed`, not `payment_failing`)
- Present continuous OK for state-like events (`approaching`, `projected`)
- Underscores for multi-word, never camelCase
- Never use generic types like `alert` or `notification` — be specific

---

## Severity tiers

Same XSIAM-style ladder, same defaults across all products.

| Severity | Default user delivery | Use when |
|---|---|---|
| `CRITICAL` | Push + email, bypasses quiet hours | User MUST know now, financial or safety impact |
| `HIGH` | Push during market hours, email after | User should know within hours, missing it has cost |
| `MEDIUM` | In-app banner, no push | User benefits from knowing today, no urgency |
| `LOW` | Feed-only | User can find it when they look |
| `INFO` | Feed-only, often hidden | Audit trail, system telemetry |

**Discipline:** Publishers MUST resist severity inflation. If everything is
CRITICAL, nothing is. Default to one tier lower than feels right.

Subscribers MAY override per-event severity in their own routing rules, but
SHOULD NOT escalate beyond what the publisher set. The publisher knows its
domain better than the router.

---

## HMAC signing

Every event MUST be signed. The router rejects unsigned events with HTTP 401.

### Algorithm

```
canonical_json = json.dumps(envelope_without_signature, sort_keys=True, separators=(",", ":"))
signature = base64( hmac_sha256( SHARED_SECRET, canonical_json ) )
```

### Why

The router is publicly addressable. Without HMAC, anyone who knows the URL
could spam events into your notification stream. Signed events mean
notification authority is gated by knowledge of the shared secret, which lives
in environment variables on the publisher and the router only.

### Secret management

- One secret per source. `BOARD_MARKET_HMAC_SECRET`, `COMMAND_CENTER_HMAC_SECRET`, etc.
- Router holds all source secrets, indexed by `src`.
- Rotate quarterly. Rotation is: generate new secret, deploy to publisher,
  deploy to router with both old and new accepted, give it 24h, drop old.

---

## Versioning

Two version concepts, intentionally separate.

**`schema_version`** — the envelope itself. Bumped only when fields are added
or changed in a way that breaks existing parsers. Currently `"1"`. Very stable;
expect this to change at most once a year if at all.

**`type_version`** — per-event-type, for payload shape changes. Increment when
you add or rename a field in the payload of that specific type. Example:

```
play.stop_hit v1:
  payload: { play_id, ticker, exit_price, exit_reason }

play.stop_hit v2:
  payload: { play_id, ticker, exit_price, exit_reason, dollar_pnl }  # added
```

Subscribers that only know v1 ignore v2 fields gracefully. Subscribers that
require v2 fields check `type_version >= 2` before parsing.

**Never delete a field.** Mark it deprecated in this doc, stop populating it
eventually, but the field name stays unused forever. This is the same
discipline as never deleting an enum value in a database.

---

## Idempotency

Subscribers MUST handle duplicate events. The router does best-effort dedup
but does not guarantee exactly-once delivery (we chose statelessness over
exactly-once for a reason).

How: subscribers maintain a small recent-event-ID cache (1000 most recent
event_ids in memory). If the incoming event_id is in the cache, ack and drop.

Because event_id is a ULID, the cache naturally expires the oldest entries.

---

## Failure modes and explicit non-guarantees

The router does not:
- Store events
- Retry failed deliveries
- Queue when a destination is down
- Reorder events
- Deduplicate across publishers
- Authenticate End Users (it doesn't know who they are)

If you need any of these, build it into the publisher or subscriber, not the
router. Statelessness is a feature.

What this means in practice:
- If the router is down for 5 minutes, those 5 minutes of events are lost.
- If a destination (push service, email API) is down, that delivery is lost.
- Mitigation: the Board's dashboard is the source of truth. The user can
  always go look. Notifications are convenience, not the system of record.

This is the right tradeoff for personal-scale tools. It would be wrong for
medical alerting or financial settlement.

---

## Publisher checklist

Before adding event emission to a product:

- [ ] Source registered in `EVENTS.md` source registry
- [ ] Each event type documented in source's section above with payload shape
- [ ] HMAC secret in environment variable, not in repo
- [ ] Emission is fire-and-forget — never blocks main flow
- [ ] Timeout on POST to router ≤ 3 seconds
- [ ] Failure to emit is logged but doesn't error
- [ ] Severity defaults to one tier lower than feels right
- [ ] `title` ≤ 80 chars, `body` ≤ 300 chars, both readable on a phone

---

## Subscriber checklist

Before adding event reception to a product:

- [ ] HTTPS endpoint exposed for inbound webhooks
- [ ] HMAC signature verified on every inbound event
- [ ] Event ID dedup cache (1000-entry LRU)
- [ ] `type_version` checked before parsing payload fields
- [ ] Unknown event types logged and dropped, never errored
- [ ] Subscriber processing time ≤ 5 seconds, async if longer
- [ ] Failure to process doesn't reject the webhook (return 200 anyway,
      log the error internally)

---

## Examples

### Stop hit on an open trading position

```json
{
  "schema_version": "1",
  "event_id": "01HXJ8KQZ3V8N7M2P4R6T9W3YA",
  "ts": "2026-05-18T14:32:00.000Z",
  "src": "board-market",
  "type": "play.stop_hit",
  "type_version": 1,
  "sev": "CRITICAL",
  "title": "NVDA stop hit",
  "body": "Exited at $184.50. P/L: -$13.60. 1 LOCK closed.",
  "deeplink": "https://wordups.github.io/the-board-market/plays/42",
  "payload": {
    "play_id": 42,
    "ticker": "NVDA",
    "tier": "LOCK",
    "entry_price": 187.42,
    "exit_price": 184.50,
    "exit_reason": "STOP",
    "held_days": 3,
    "pct_return": -1.56,
    "r_multiple": -1.00,
    "dollar_pnl": -13.60
  },
  "signature": "..."
}
```

### Congressional cluster detected on watchlist ticker

```json
{
  "schema_version": "1",
  "event_id": "01HXJ8L0AB1C2D3E4F5G6H7J8K",
  "ts": "2026-05-18T18:05:00.000Z",
  "src": "board-market",
  "type": "signal.congressional_cluster",
  "type_version": 1,
  "sev": "HIGH",
  "title": "Cluster: 4 members bought XLE",
  "body": "Threshold hit (3+ in 30d). Smart Money +4. New score: 82.",
  "deeplink": "https://wordups.github.io/the-board-market/signals/xle",
  "payload": {
    "ticker": "XLE",
    "member_count": 4,
    "window_days": 30,
    "score_before": 78,
    "score_after": 82
  },
  "signature": "..."
}
```

### Bill payment failed in Command Center

```json
{
  "schema_version": "1",
  "event_id": "01HXJ8MNPQRSTUVWXYZ012345A",
  "ts": "2026-05-18T11:00:00.000Z",
  "src": "command-center",
  "type": "bill.payment_failed",
  "type_version": 1,
  "sev": "CRITICAL",
  "title": "Autopay declined: Discover",
  "body": "$340 declined. Card 4011. Retry available in app.",
  "deeplink": "https://wordups.github.io/command-center/bills/discover",
  "payload": {
    "biller": "Discover",
    "amount": 340.00,
    "card_last_four": "4011",
    "decline_reason": "insufficient_funds"
  },
  "signature": "..."
}
```

---

## Future considerations (not Phase 2.6)

- **Subscribe side.** Phase 2.6 builds publishers + router + End-User delivery.
  Inter-product subscribe is Phase 4.5+.
- **Replay.** If we ever need replay, that's a separate persistence service,
  not the router. The router stays stateless.
- **Multi-user.** If The Board Market ever becomes multi-user, add `user_id_hash`
  to the envelope. Router uses hash for routing decisions, never sees identity.
- **Encryption at rest.** Not relevant — there is no "at rest" in a stateless router.
- **Encryption in transit.** Already covered by HTTPS to the router.
