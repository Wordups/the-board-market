# DESIGN.md

> Visual and interaction design spec. Matches The Board System aesthetic.
> Do not invent a new design language — extend the existing one.

---

## Aesthetic identity

**Mood:** Dark editorial, sports-analytics-meets-trading-terminal. Confident, dense, no fluff.

**Reference points:**
- Bloomberg Terminal (information density)
- Linear (motion, typography)
- The Athletic (editorial darkness)
- Brian's existing Board System (sibling continuity)

**Anti-patterns:**
- Stock photo "professional trader" imagery
- Generic SaaS gradients (purple-to-blue, blue-to-teal)
- Coingecko / Robinhood "fintech bro" green
- Bootstrap defaults
- Material Design / Tailwind defaults without customization

---

## Color system

CSS variables. Single source of truth in `assets/css/tokens.css`.

```css
:root {
  /* Base */
  --bg-primary: #0a0a0c;
  --bg-secondary: #14141a;
  --bg-tertiary: #1d1d26;
  --bg-card: #16161e;
  --bg-elevated: #1f1f29;

  /* Text */
  --text-primary: #e8e8ed;
  --text-secondary: #a0a0ac;
  --text-tertiary: #6e6e7a;
  --text-faded: #4a4a55;

  /* Tier accents */
  --tier-lock: #ffb347;        /* amber — high conviction */
  --tier-live: #7cc7ff;        /* cool blue — qualified */
  --tier-bench: #6e6e7a;       /* muted — watchlist */
  --tier-frozen: #4a4a55;      /* locked board indicator */

  /* P/L semantics */
  --gain: #4ade80;             /* green — restrained, not Robinhood */
  --loss: #f87171;             /* red — clear but not alarming */
  --neutral: #a0a0ac;

  /* Score gradient */
  --score-bg: linear-gradient(90deg, #1d1d26 0%, #2a2a36 100%);
  --score-fill-lock: linear-gradient(90deg, #ffb347 0%, #ff9528 100%);
  --score-fill-live: linear-gradient(90deg, #7cc7ff 0%, #4a9eda 100%);

  /* Borders */
  --border-subtle: #26262f;
  --border-medium: #33333d;
  --border-strong: #4a4a55;

  /* Functional */
  --accent: #ffb347;
  --warning: #fbbf24;
  --danger: #f87171;
}
```

---

## Typography

```css
:root {
  --font-display: 'JetBrains Mono', 'IBM Plex Mono', monospace;
  --font-body: 'Inter Tight', 'IBM Plex Sans', system-ui, sans-serif;
  --font-numeric: 'JetBrains Mono', monospace;  /* always for prices/scores */
}
```

**Rules:**
- All prices, scores, percentages, and tabular numbers in `--font-numeric` with `font-variant-numeric: tabular-nums`
- Ticker symbols in `--font-display` (monospace), letter-spacing: 0.5px, font-weight: 600
- Headers in `--font-display`, uppercase, letter-spacing: 1.5px
- Body in `--font-body`
- Never use Roboto or Open Sans. They feel like every dashboard ever.

---

## Layout

**Grid:** 12-column on desktop, fluid stack on mobile. Max content width 1440px.

**Spacing scale (rem):**
`0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8`

**Density:** Higher than typical SaaS. This is a tool for an operator, not a marketing page. Don't over-pad.

---

## Component spec — key surfaces

### Today's Board (the hero view)

```
┌────────────────────────────────────────────────────────────────────┐
│  THE BOARD: MARKETS                          MAY 18, 2026 · MON    │
│  REGIME: BULL · VIX 17.82 · 10Y 4.62%       ❄️ FROZEN AT 09:30 ET │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  🔒 LOCK                                                          │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ NVDA  $187.42  +1.2%  ▲          SCORE 89  R/R 2.8       │    │
│  │ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 89/100   │    │
│  │ Catalyst: Earnings Wed AMC                                │    │
│  │ Tape: Breakout from 5-day base                            │    │
│  │ Tech 18  Cat 17  RS 13  SM 12  Macro 14  Sent 15          │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                    │
│  📊 LIVE (2)                                                      │
│  ...                                                               │
│                                                                    │
│  🪑 BENCH (12)                                                    │
│  Compact list with score, no factor breakdown                      │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

**Score bars:** Filled gradient from left, width = score%. Color matches tier.

**Tier headers:** Emoji + bold tier name + count badge. Color matches `--tier-*` variable.

**Factor breakdown:** Mini horizontal bars or a compact 6-column row. Hover shows full notes.

### Ledger view

Table of plays. Columns:
`Date • Ticker • Tier • Mode • Entry • Stop • Target • Status • P/L`

Filters: Open / Closed / All. Date range. Tier. Mode.

Row click expands to show full factor breakdown at entry and exit context.

### Equity curve

Single chart, full-width. Line graph in `--accent` color over `--bg-card`. Annotated drawdown periods. Hover crosshair shows date, bankroll, # of open plays at that point.

### Performance metrics card

```
┌──────────────────────────────────────┐
│ ROLLING 30D                          │
│                                      │
│  WIN RATE         62.5%      ▲ +3.2  │
│  AVG R            1.94                │
│  EXPECTANCY      +2.1%                │
│  CLOSED PLAYS     16                  │
│                                      │
│  LOCK             71% (5/7)           │
│  LIVE             56% (5/9)           │
└──────────────────────────────────────┘
```

### Connection status

Bottom-right footer chip:
- 🟢 Schwab synced 2 min ago
- 🟡 Plaid synced 12 min ago
- 🔴 Schwab disconnected — click to reauth

---

## Motion

- **Score bar fill:** 600ms ease-out on first render. No bouncy springs.
- **Tier card hover:** subtle `translateY(-2px)` + border lighten, 150ms.
- **Freeze gate transition:** at 9:30 AM ET, board animates a thin amber line sweep across, then locks. One-time, deliberate, doesn't repeat.
- **Equity curve drawing:** stroke-dashoffset animation, 1.2s ease-out.
- No skeleton loaders. Show real data or nothing.

---

## Responsiveness

- **Desktop (>1024px):** Full grid, sidebar + main + right rail
- **Tablet (768–1024px):** Two-column, sidebar collapses to top
- **Mobile (<768px):** Single column stack. Compact bench view. Equity curve simplified to last 30 days only.

Mobile is supported but not the primary surface. Brian is reading this on a desktop or laptop.

---

## Accessibility (mandatory, not optional)

- All color combinations pass WCAG AA contrast (4.5:1 body, 3:1 large)
- Tier indication never relies on color alone (always has emoji + label)
- Focus rings visible and styled (`outline: 2px solid var(--accent); outline-offset: 2px`)
- Tab order logical
- Score bars have aria-valuenow / aria-valuemax
- Charts have accessible alternative (data table view toggle)

---

## File structure

```
assets/
├── css/
│   ├── tokens.css         # CSS variables
│   ├── base.css           # reset, typography, layout
│   ├── components/
│   │   ├── tier-card.css
│   │   ├── score-bar.css
│   │   ├── ledger-table.css
│   │   └── equity-curve.css
│   └── pages/
│       ├── board.css
│       ├── ledger.css
│       └── settings.css
├── js/
│   ├── board.js
│   ├── ledger.js
│   ├── freeze-gate.js
│   ├── equity-curve.js     # d3 or chart.js
│   └── api.js              # fetch wrappers
└── fonts/                  # self-hosted JetBrains Mono, Inter Tight
```

No framework. Vanilla JS, ES modules, native fetch. The Board System is built this way; match it.
