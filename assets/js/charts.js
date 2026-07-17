// Candlestick + breakout-levels chart for the detail panel.
// Data: data/charts_today.json (written by engine/generate_board.py).
// Vanilla canvas, no dependencies; colors come from CSS custom properties so
// the chart follows the app theme.

(() => {
  let chartData = null;
  let loading = null;

  function loadCharts() {
    if (!loading) {
      loading = fetch("data/charts_today.json", { cache: "no-store" })
        .then(r => (r.ok ? r.json() : null))
        .catch(() => null)
        .then(json => { chartData = json; return json; });
    }
    return loading;
  }

  function cssColor(name, fallback) {
    const value = getComputedStyle(document.body).getPropertyValue(name).trim();
    return value || fallback;
  }

  function drawChart(canvas, series, setup) {
    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);

    const up = cssColor("--green", "#80d9a1");
    const down = cssColor("--red", "#ff776f");
    const ink = cssColor("--muted", "#9b9b96");
    const grid = cssColor("--line", "#272c28");

    const candles = series.candles;
    const pad = { top: 12, right: 64, bottom: 22, left: 8 };
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;

    const levels = [setup.stop, setup.target, setup.breakout?.trigger].filter(v => v > 0);
    let lo = Math.min(...candles.map(c => c[3]), ...levels);
    let hi = Math.max(...candles.map(c => c[2]), ...levels);
    const span = (hi - lo) || 1;
    lo -= span * 0.04; hi += span * 0.04;

    const x = i => pad.left + (i + 0.5) * (plotW / candles.length);
    const y = v => pad.top + (hi - v) / (hi - lo) * plotH;

    // Grid: 4 recessive horizontal lines with price labels.
    ctx.font = "10px system-ui, sans-serif";
    ctx.textBaseline = "middle";
    for (let g = 0; g <= 3; g++) {
      const v = lo + (hi - lo) * g / 3;
      ctx.strokeStyle = grid;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(pad.left, y(v));
      ctx.lineTo(pad.left + plotW, y(v));
      ctx.stroke();
      ctx.fillStyle = ink;
      ctx.textAlign = "left";
      ctx.fillText(v >= 1000 ? v.toFixed(0) : v.toFixed(2), pad.left + plotW + 6, y(v));
    }

    // Moving averages under the candles.
    const drawMA = (values, alpha) => {
      ctx.strokeStyle = ink;
      ctx.globalAlpha = alpha;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      let started = false;
      values.forEach((v, i) => {
        if (v == null) return;
        if (!started) { ctx.moveTo(x(i), y(v)); started = true; }
        else ctx.lineTo(x(i), y(v));
      });
      ctx.stroke();
      ctx.globalAlpha = 1;
    };
    drawMA(series.ma50, 0.35);
    drawMA(series.ma20, 0.6);

    // Candles: 2px-gapped bodies, 1px wicks.
    const bodyW = Math.max(2, plotW / candles.length - 2);
    candles.forEach((c, i) => {
      const [, open, high, low, close] = c;
      const color = close >= open ? up : down;
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x(i), y(high));
      ctx.lineTo(x(i), y(low));
      ctx.stroke();
      const top = y(Math.max(open, close));
      const bodyH = Math.max(1, Math.abs(y(open) - y(close)));
      ctx.fillRect(x(i) - bodyW / 2, top, bodyW, bodyH);
    });

    // Levels: trigger (solid), target/stop (dashed), direct-labeled on the right.
    const level = (value, color, label, dashed) => {
      if (!(value > 0)) return;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.setLineDash(dashed ? [4, 3] : []);
      ctx.beginPath();
      ctx.moveTo(pad.left, y(value));
      ctx.lineTo(pad.left + plotW, y(value));
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = color;
      ctx.textAlign = "left";
      ctx.fillText(label, pad.left + plotW + 6, Math.max(pad.top + 5, Math.min(y(value) - 8, height - pad.bottom - 5)));
    };
    level(setup.target, up, "target", true);
    level(setup.stop, down, "stop", true);
    if (setup.breakout?.trigger) level(setup.breakout.trigger, cssColor("--amber", "#ffb15a"), "breakout", false);

    // Date labels: first and last session.
    ctx.fillStyle = ink;
    ctx.textAlign = "left";
    ctx.fillText(candles[0][0], pad.left, height - 8);
    ctx.textAlign = "right";
    ctx.fillText(candles[candles.length - 1][0], pad.left + plotW, height - 8);
  }

  // Called by app.js after the detail panel renders.
  window.renderSetupChart = async function (setup) {
    const host = document.getElementById("setup-chart-box");
    if (!host) return;
    const data = await loadCharts();
    const series = data?.tickers?.[setup.ticker];
    if (!series || !series.candles?.length) {
      host.innerHTML = `<p class="chart-note">Chart data not published yet — next daily build adds it.</p>`;
      return;
    }
    const brk = setup.breakout || {};
    const state = brk.confirmed
      ? `<strong class="gain">BREAKOUT CONFIRMED</strong> · closed above ${Number(brk.trigger).toFixed(2)} on ${Number(brk.vol_ratio).toFixed(1)}× volume`
      : brk.trigger
        ? `Breakout trigger ${Number(brk.trigger).toFixed(2)} · ${Math.abs(Number(brk.pct_to_trigger)).toFixed(1)}% ${Number(brk.pct_to_trigger) >= 0 ? "above" : "below"} last close · vol ${Number(brk.vol_ratio ?? 0).toFixed(1)}× avg`
        : "Not enough history for a breakout read.";
    host.innerHTML = `
      <canvas id="setup-chart" aria-label="60-day candlestick chart for ${setup.ticker} with breakout, stop, and target levels" role="img"></canvas>
      <p class="chart-note">${state}</p>
      <p class="chart-note muted">60 daily candles · 20/50-day averages · levels: breakout trigger (20-day high), −8% stop, +16% target. Setup detection, not prediction.</p>`;
    const canvas = host.querySelector("#setup-chart");
    drawChart(canvas, series, setup);
    if (!host.dataset.resizeWired) {
      host.dataset.resizeWired = "1";
      window.addEventListener("resize", () => {
        const current = host.querySelector("#setup-chart");
        if (current && window.currentChartArgs) drawChart(current, ...window.currentChartArgs);
      });
    }
    window.currentChartArgs = [series, setup];
  };
})();
