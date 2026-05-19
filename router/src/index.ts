/**
 * Takeoff Trigger Router
 *
 * Stateless event dispatcher. Receives signed events from Takeoff products,
 * routes them to delivery channels based on severity rules.
 *
 * NO STATE. NO STORAGE. NO LOGS OF EVENT CONTENT.
 *
 * Deploy: wrangler deploy
 *
 * Environment bindings (set via wrangler.toml):
 *   BOARD_MARKET_HMAC_SECRET     — HMAC secret for board-market source
 *   COMMAND_CENTER_HMAC_SECRET   — HMAC secret for command-center source
 *   MIDNIGHT_HMAC_SECRET         — HMAC secret for midnight source
 *   POOF_E_GONE_HMAC_SECRET      — HMAC secret for poof-e-gone source
 *   RESEND_API_KEY               — for email delivery
 *   VAPID_PRIVATE_KEY            — for web push delivery
 *   VAPID_PUBLIC_KEY             — for web push delivery
 *   USER_EMAIL                   — End User's email
 *   USER_PUSH_SUBSCRIPTION       — JSON-encoded push subscription
 *   QUIET_DAY_FLAG_URL           — endpoint to check "Quiet Day" toggle
 */

interface Env {
  BOARD_MARKET_HMAC_SECRET: string;
  COMMAND_CENTER_HMAC_SECRET?: string;
  MIDNIGHT_HMAC_SECRET?: string;
  POOF_E_GONE_HMAC_SECRET?: string;
  RESEND_API_KEY?: string;
  VAPID_PRIVATE_KEY?: string;
  VAPID_PUBLIC_KEY?: string;
  USER_EMAIL?: string;
  USER_PUSH_SUBSCRIPTION?: string;
  QUIET_DAY_FLAG_URL?: string;
}

interface EventEnvelope {
  schema_version: string;
  event_id: string;
  ts: string;
  src: string;
  type: string;
  type_version: number;
  sev: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
  title: string;
  body: string;
  deeplink?: string;
  payload?: Record<string, unknown>;
  signature: string;
}

// ─────────────────────── Severity routing rules ───────────────────────
// First match wins. CRITICAL always goes through; LOW/INFO never push.

const ROUTING_RULES = [
  { sev: "CRITICAL", channels: ["push", "email"], bypass_quiet: true },
  { sev: "HIGH",     channels: ["push"],          market_hours_only: true },
  { sev: "HIGH",     channels: ["email"]                                    }, // outside market hours
  { sev: "MEDIUM",   channels: []                                           }, // feed-only, no notification
  { sev: "LOW",      channels: []                                           },
  { sev: "INFO",     channels: []                                           },
];

const QUIET_HOURS_START = 21;  // 9 PM ET
const QUIET_HOURS_END = 6;     // 6 AM ET

// ─────────────────────── Source → secret resolver ───────────────────────

function secretForSource(env: Env, src: string): string | undefined {
  switch (src) {
    case "board-market":   return env.BOARD_MARKET_HMAC_SECRET;
    case "command-center": return env.COMMAND_CENTER_HMAC_SECRET;
    case "midnight":       return env.MIDNIGHT_HMAC_SECRET;
    case "poof-e-gone":    return env.POOF_E_GONE_HMAC_SECRET;
    default:               return undefined;
  }
}

// ─────────────────────── HMAC verification ───────────────────────

async function verifySignature(envelope: EventEnvelope, secret: string): Promise<boolean> {
  const { signature, ...rest } = envelope;

  // Canonical JSON with sorted keys, no whitespace
  const canonical = canonicalJSON(rest);

  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["verify"]
  );

  const sigBytes = Uint8Array.from(atob(signature), c => c.charCodeAt(0));

  return crypto.subtle.verify(
    "HMAC",
    key,
    sigBytes,
    new TextEncoder().encode(canonical)
  );
}

function canonicalJSON(obj: Record<string, unknown>): string {
  const sorted: Record<string, unknown> = {};
  for (const k of Object.keys(obj).sort()) sorted[k] = obj[k];
  return JSON.stringify(sorted).replace(/\s/g, "");
}

// ─────────────────────── Routing logic ───────────────────────

function isMarketHours(ts: string): boolean {
  const d = new Date(ts);
  // Convert UTC to ET (UTC-4 during DST, UTC-5 standard)
  const etHour = (d.getUTCHours() - 4 + 24) % 24;
  const dow = d.getUTCDay();
  return dow >= 1 && dow <= 5 && etHour >= 9 && etHour < 16;
}

function isQuietHours(ts: string): boolean {
  const d = new Date(ts);
  const etHour = (d.getUTCHours() - 4 + 24) % 24;
  return etHour >= QUIET_HOURS_START || etHour < QUIET_HOURS_END;
}

async function isQuietDayActive(env: Env): Promise<boolean> {
  if (!env.QUIET_DAY_FLAG_URL) return false;
  try {
    const r = await fetch(env.QUIET_DAY_FLAG_URL, { signal: AbortSignal.timeout(2000) });
    if (!r.ok) return false;
    const data = await r.json() as { quiet_day: boolean };
    return data.quiet_day === true;
  } catch {
    return false; // fail-open
  }
}

function selectChannels(envelope: EventEnvelope, quietActive: boolean): string[] {
  for (const rule of ROUTING_RULES) {
    if (rule.sev !== envelope.sev) continue;
    if (rule.market_hours_only && !isMarketHours(envelope.ts)) continue;

    // Quiet hours / quiet day enforcement
    if (quietActive && !rule.bypass_quiet) return [];
    if (isQuietHours(envelope.ts) && !rule.bypass_quiet) {
      // outside market hours, fall through to next rule for the same sev
      continue;
    }

    return rule.channels;
  }
  return [];
}

// ─────────────────────── Delivery channels ───────────────────────

async function deliverEmail(env: Env, envelope: EventEnvelope): Promise<void> {
  if (!env.RESEND_API_KEY || !env.USER_EMAIL) return;
  await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.RESEND_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: "Takeoff Triggers <triggers@notifications.takeoff.local>",
      to: env.USER_EMAIL,
      subject: `[${envelope.sev}] ${envelope.title}`,
      text: `${envelope.body}\n\n${envelope.deeplink ?? ""}\n\nSource: ${envelope.src}`,
    }),
    signal: AbortSignal.timeout(5000),
  });
}

async function deliverPush(env: Env, envelope: EventEnvelope): Promise<void> {
  // VAPID web push implementation — abbreviated stub.
  // Production: use web-push library or the Web Push protocol directly.
  // For Phase 2.6 ship, log intent and return; real implementation per P2.63.
  if (!env.USER_PUSH_SUBSCRIPTION) return;
  // TODO P2.63: implement actual VAPID-authenticated push
}

async function dispatch(env: Env, envelope: EventEnvelope, channels: string[]): Promise<void> {
  const promises: Promise<void>[] = [];
  for (const ch of channels) {
    if (ch === "email") promises.push(deliverEmail(env, envelope));
    if (ch === "push") promises.push(deliverPush(env, envelope));
  }
  // Best-effort: don't fail the whole request if one channel fails
  await Promise.allSettled(promises);
}

// ─────────────────────── Worker entry ───────────────────────

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    let envelope: EventEnvelope;
    try {
      envelope = await request.json() as EventEnvelope;
    } catch {
      return new Response("Invalid JSON", { status: 400 });
    }

    // Basic envelope validation
    const required = ["schema_version", "event_id", "ts", "src", "type",
                      "type_version", "sev", "title", "body", "signature"];
    for (const field of required) {
      if (!(field in envelope)) {
        return new Response(`Missing field: ${field}`, { status: 400 });
      }
    }

    // Resolve secret for source
    const secret = secretForSource(env, envelope.src);
    if (!secret) {
      return new Response("Unknown source", { status: 401 });
    }

    // Verify HMAC
    const valid = await verifySignature(envelope, secret);
    if (!valid) {
      return new Response("Invalid signature", { status: 401 });
    }

    // Check Quiet Day toggle
    const quietActive = await isQuietDayActive(env);

    // Apply routing rules
    const channels = selectChannels(envelope, quietActive);

    // Dispatch
    if (channels.length > 0) {
      await dispatch(env, envelope, channels);
    }

    // Return minimal response. INTENTIONALLY no echo of envelope content
    // (the response goes through Cloudflare logs which we don't control).
    return new Response(JSON.stringify({ ok: true, channels: channels.length }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  },
};
