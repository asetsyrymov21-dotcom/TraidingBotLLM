# ============================================================
#  web_app.py — веб-интерфейс Trading Bot (мобильный, тёмная тема)
#  Запускается в отдельном потоке из main.py
#  Доступен по адресу: http://<VPS_IP>:8080
# ============================================================

import json
import logging
import os
import threading
import time
from typing import Any, Dict

import dynamic_settings

logger = logging.getLogger(__name__)

STATUS_DIR = os.path.join("data", "status")

# ──────────────────────────────────────────────────────────────
#  HTML (mobile-first, dark theme)
# ──────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Trading Bot</title>
<link rel="stylesheet"
  href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.2/css/bootstrap.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  :root {
    --bg:       #0d1117;
    --card:     #161b22;
    --border:   #30363d;
    --text:     #e6edf3;
    --muted:    #8b949e;
    --green:    #3fb950;
    --red:      #f85149;
    --yellow:   #d29922;
    --blue:     #58a6ff;
    --accent:   #1f6feb;
  }
  * { box-sizing: border-box; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 14px;
    margin: 0;
    padding-bottom: 90px;
  }

  /* ── Header ── */
  .header {
    background: var(--card);
    border-bottom: 1px solid var(--border);
    padding: 12px 16px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 100;
  }
  .header-title { font-size: 16px; font-weight: 700; }
  .status-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--green);
    display: inline-block;
    margin-right: 6px;
    animation: pulse 2s infinite;
  }
  @keyframes pulse {
    0%,100% { opacity: 1; }
    50%      { opacity: .4; }
  }
  .last-update { font-size: 11px; color: var(--muted); }

  /* ── Pair cards ── */
  .pair-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px;
    margin: 10px 12px 0;
  }
  .pair-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
  }
  .pair-name { font-weight: 700; font-size: 15px; }
  .pair-price { font-size: 15px; font-weight: 600; }

  .badge-long  { background: rgba(63,185,80,.15);  color: var(--green); }
  .badge-short { background: rgba(248,81,73,.15);  color: var(--red);   }
  .badge-none  { background: rgba(139,148,158,.1); color: var(--muted); }
  .regime-quiet    { color: var(--blue);   font-size: 11px; }
  .regime-normal   { color: var(--yellow); font-size: 11px; }
  .regime-volatile { color: var(--red);    font-size: 11px; }

  .pos-row {
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    color: var(--muted);
    margin-top: 4px;
  }
  .pnl-pos { color: var(--green); font-weight: 600; }
  .pnl-neg { color: var(--red);   font-weight: 600; }

  /* ── Settings ── */
  .section {
    margin: 16px 12px 0;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
  }
  .section-header {
    padding: 12px 16px;
    font-weight: 700;
    font-size: 13px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: .5px;
    border-bottom: 1px solid var(--border);
  }
  .setting-row {
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
  }
  .setting-row:last-child { border-bottom: none; }
  .setting-label {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 6px;
  }
  .setting-name { font-size: 13px; }
  .setting-val  {
    font-size: 13px;
    font-weight: 700;
    color: var(--blue);
    min-width: 52px;
    text-align: right;
  }
  .setting-hint { font-size: 11px; color: var(--muted); margin-top: 2px; }

  input[type=range] {
    -webkit-appearance: none;
    width: 100%;
    height: 4px;
    border-radius: 2px;
    background: var(--border);
    outline: none;
    cursor: pointer;
  }
  input[type=range]::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 18px; height: 18px;
    border-radius: 50%;
    background: var(--accent);
    border: 2px solid var(--bg);
  }
  input[type=number] {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    padding: 6px 10px;
    width: 100%;
    font-size: 14px;
    margin-top: 4px;
  }
  input[type=number]:focus {
    outline: none;
    border-color: var(--accent);
  }

  /* ── Save bar ── */
  .save-bar {
    position: fixed;
    bottom: 0; left: 0; right: 0;
    background: var(--card);
    border-top: 1px solid var(--border);
    padding: 12px 16px;
    z-index: 200;
  }
  .btn-save {
    width: 100%;
    background: var(--accent);
    color: #fff;
    border: none;
    border-radius: 8px;
    padding: 13px;
    font-size: 15px;
    font-weight: 700;
    cursor: pointer;
    transition: opacity .2s;
  }
  .btn-save:active { opacity: .8; }
  .btn-save:disabled { opacity: .5; cursor: default; }

  /* ── Toast ── */
  .toast-wrap {
    position: fixed;
    top: 60px; left: 50%;
    transform: translateX(-50%);
    z-index: 999;
    pointer-events: none;
  }
  .toast-msg {
    background: var(--green);
    color: #fff;
    padding: 10px 20px;
    border-radius: 20px;
    font-weight: 600;
    font-size: 13px;
    opacity: 0;
    transition: opacity .3s;
  }
  .toast-msg.show { opacity: 1; }
  .toast-msg.err  { background: var(--red); }

  /* ── Period buttons ── */
  .period-btn {
    background: var(--border);
    color: var(--muted);
    border: none;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: background .15s, color .15s;
  }
  .period-btn.active {
    background: var(--accent);
    color: #fff;
  }
</style>
</head>
<body>

<!-- Header -->
<div class="header">
  <div>
    <span class="status-dot" id="dot"></span>
    <span class="header-title">Trading Bot</span>
  </div>
  <span class="last-update" id="last-update">--</span>
</div>

<!-- Toast -->
<div class="toast-wrap"><div class="toast-msg" id="toast"></div></div>

<!-- Pair status cards -->
<div id="pairs-section"></div>

<!-- PnL Chart -->
<div class="section">
  <div class="section-header" style="display:flex;justify-content:space-between;align-items:center">
    <span>ИСТОРИЯ PNL</span>
    <div style="display:flex;gap:6px">
      <button class="period-btn" id="p1"  onclick="loadChart(1)">1д</button>
      <button class="period-btn active" id="p7"  onclick="loadChart(7)">7д</button>
      <button class="period-btn" id="p30" onclick="loadChart(30)">30д</button>
    </div>
  </div>
  <div style="padding:12px 16px 16px">
    <div id="chart-msg" style="text-align:center;color:var(--muted);font-size:13px;padding:24px 0">
      Загрузка...
    </div>
    <canvas id="pnl-chart" style="display:none"></canvas>
  </div>
</div>

<!-- General Settings -->
<div class="section">
  <div class="section-header">ОБЩИЕ НАСТРОЙКИ</div>

  <div class="setting-row">
    <div class="setting-label">
      <span class="setting-name">Таймаут позиции (минуты)</span>
      <span class="setting-val" id="val-max_hold_minutes">--</span>
    </div>
    <input type="range" id="max_hold_minutes"
      min="30" max="480" step="30"
      oninput="onSlider('max_hold_minutes', this.value, 'мин', 1)">
    <div class="setting-hint">Позиция принудительно закроется через это время</div>
  </div>

  <div class="setting-row">
    <div class="setting-label">
      <span class="setting-name">Размер позиции (% депозита)</span>
      <span class="setting-val" id="val-position_pct">--</span>
    </div>
    <input type="range" id="position_pct"
      min="1" max="20" step="1"
      oninput="onSlider('position_pct', this.value, '%', 100)">
  </div>

  <div class="setting-row">
    <div class="setting-label">
      <span class="setting-name">RSI порог лонга</span>
      <span class="setting-val" id="val-rsi_long_threshold">--</span>
    </div>
    <input type="range" id="rsi_long_threshold"
      min="40" max="60" step="1"
      oninput="onSlider('rsi_long_threshold', this.value, '', 1)">
    <div class="setting-hint">RSI выше этого — LONG (первый вход)</div>
  </div>

  <div class="setting-row">
    <div class="setting-label">
      <span class="setting-name">RSI порог шорта</span>
      <span class="setting-val" id="val-rsi_short_threshold">--</span>
    </div>
    <input type="range" id="rsi_short_threshold"
      min="40" max="60" step="1"
      oninput="onSlider('rsi_short_threshold', this.value, '', 1)">
    <div class="setting-hint">RSI ниже этого — SHORT (первый вход)</div>
  </div>
</div>

<!-- spacer -->
<div style="height:16px"></div>

<!-- Save bar -->
<div class="save-bar">
  <button class="btn-save" id="btn-save" onclick="saveSettings()">
    Сохранить настройки
  </button>
</div>

<script>
const settings = {};

// -- Загрузка настроек --
async function loadSettings() {
  try {
    const r = await fetch('/api/settings');
    const data = await r.json();
    Object.assign(settings, data);
    applySettingsToUI(data);
  } catch(e) { console.error('loadSettings:', e); }
}

function applySettingsToUI(data) {
  const fields = [
    ['max_hold_minutes',       1,   'мин'],
    ['position_pct',           100, '%'],
    ['rsi_long_threshold',     1,   ''],
    ['rsi_short_threshold',    1,   ''],
  ];
  fields.forEach(([key, mult, suffix]) => {
    const el = document.getElementById(key);
    const val = data[key];
    if (el && val !== undefined) {
      el.value = val * mult;
      const disp = document.getElementById('val-' + key);
      if (disp) disp.textContent = (val * mult).toFixed(mult === 1 ? 0 : 2) + suffix;
    }
  });
}

function onSlider(key, rawVal, suffix, divisor) {
  const num = parseFloat(rawVal);
  settings[key] = num / divisor;
  const disp = document.getElementById('val-' + key);
  if (disp) disp.textContent = num.toFixed(divisor === 1 ? 0 : 2) + suffix;
}

// -- Сохранение --
async function saveSettings() {
  const btn = document.getElementById('btn-save');
  btn.disabled = true;
  btn.textContent = 'Сохраняем...';
  try {
    const r = await fetch('/api/settings', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(settings),
    });
    const res = await r.json();
    if (res.ok) showToast('Сохранено! Применится через ~20 сек', false);
    else        showToast('Ошибка сохранения', true);
  } catch(e) {
    showToast('Ошибка: ' + e.message, true);
  }
  btn.disabled = false;
  btn.textContent = 'Сохранить настройки';
}

// -- Статус пар --
async function loadStatus() {
  try {
    const r = await fetch('/api/status');
    const data = await r.json();
    renderPairs(data.pairs || []);
    const upd = document.getElementById('last-update');
    upd.textContent = new Date().toLocaleTimeString('ru-RU', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
  } catch(e) { console.error('loadStatus:', e); }
}

function renderPairs(pairs) {
  const container = document.getElementById('pairs-section');
  if (!pairs.length) {
    container.innerHTML = '<div style="padding:20px 16px;color:var(--muted);text-align:center">Нет данных — бот ещё не запущен</div>';
    return;
  }
  container.innerHTML = pairs.map(p => {
    const pos = p.position;
    const hasPos = pos && pos.side;
    const sideBadge = hasPos
      ? '<span class="badge rounded-pill badge-' + pos.side + '">' + (pos.side === 'long' ? 'LONG' : 'SHORT') + '</span>'
      : '<span class="badge rounded-pill badge-none">нет позиции</span>';

    const regimeClass = 'regime-' + (p.market_regime || 'normal');
    const regimeLabels = {quiet: 'Тихий', normal: 'Нормальный', volatile: 'Волатильный'};
    const regime = regimeLabels[p.market_regime] || p.market_regime;

    const pnlClass = p.session_pnl >= 0 ? 'pnl-pos' : 'pnl-neg';
    const pnlSign  = p.session_pnl >= 0 ? '+' : '';

    let posRows = '';
    if (hasPos) {
      posRows =
        '<div class="pos-row">' +
        '<span>Вход: <b>' + (pos.entry_price ? pos.entry_price.toFixed(2) : '--') + '</b></span>' +
        '<span>TP: <b style="color:var(--green)">' + (pos.tp_price ? pos.tp_price.toFixed(2) : '--') + '</b></span>' +
        '<span>SL: <b style="color:var(--red)">' + (pos.sl_price ? pos.sl_price.toFixed(2) : '--') + '</b></span>' +
        '</div>';
    }

    return '<div class="pair-card">' +
      '<div class="pair-header">' +
        '<span class="pair-name">' + p.symbol + '</span>' +
        '<span class="pair-price">$' + (p.price||0).toLocaleString('en-US', {maximumFractionDigits:2}) + '</span>' +
      '</div>' +
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">' +
        sideBadge +
        '<span class="' + regimeClass + '">' + regime + ' | ATR ' + (p.atr_pct||0).toFixed(3) + '%</span>' +
      '</div>' +
      posRows +
      '<div class="pos-row" style="margin-top:8px">' +
        '<span>RSI: <b>' + p.rsi + '</b></span>' +
        '<span>PnL: <b class="' + pnlClass + '">' + pnlSign + (p.session_pnl||0).toFixed(4) + ' USDT</b></span>' +
        '<span>Сделок: <b>' + (p.trade_count||0) + '</b></span>' +
      '</div>' +
    '</div>';
  }).join('');
}

// -- PnL Chart --
let pnlChart = null;

async function loadChart(days) {
  ['p1','p7','p30'].forEach(function(id) {
    document.getElementById(id).classList.remove('active');
  });
  document.getElementById('p' + days).classList.add('active');

  const msg    = document.getElementById('chart-msg');
  const canvas = document.getElementById('pnl-chart');
  msg.style.display    = 'block';
  canvas.style.display = 'none';
  msg.textContent = 'Загрузка...';

  try {
    const r    = await fetch('/api/balance_chart?days=' + days);
    const data = await r.json();

    if (!data.dates || data.dates.length === 0) {
      msg.textContent = data.error || 'Нет данных за этот период';
      return;
    }

    msg.style.display    = 'none';
    canvas.style.display = 'block';

    if (pnlChart) { pnlChart.destroy(); pnlChart = null; }

    const last    = data.values[data.values.length - 1];
    const color   = last >= 0 ? '#3fb950' : '#f85149';
    const showDot = data.dates.length <= 14;

    pnlChart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: data.dates,
        datasets: [{
          label: 'PnL USDT',
          data: data.values,
          borderColor: color,
          backgroundColor: color + '22',
          fill: true,
          tension: 0.3,
          pointRadius: showDot ? 3 : 0,
          pointHoverRadius: 5,
          borderWidth: 2
        }]
      },
      options: {
        responsive: true,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function(ctx) {
                return (ctx.raw >= 0 ? '+' : '') + ctx.raw.toFixed(4) + ' USDT';
              }
            }
          }
        },
        scales: {
          x: {
            ticks: { color: '#8b949e', maxTicksLimit: 7, maxRotation: 0 },
            grid:  { color: '#30363d' }
          },
          y: {
            ticks: {
              color: '#8b949e',
              callback: function(v) { return (v >= 0 ? '+' : '') + v.toFixed(2); }
            },
            grid: { color: '#30363d' }
          }
        }
      }
    });
  } catch(e) {
    msg.style.display    = 'block';
    canvas.style.display = 'none';
    msg.textContent = 'Ошибка: ' + e.message;
  }
}

// -- Toast --
function showToast(msg, isError) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast-msg show' + (isError ? ' err' : '');
  setTimeout(function() { t.className = 'toast-msg'; }, 2500);
}

// -- Init --
loadSettings();
loadStatus();
loadChart(7);
setInterval(loadStatus, 15000);
</script>
</body>
</html>"""


# ──────────────────────────────────────────────────────────────
#  Flask API
# ──────────────────────────────────────────────────────────────

def _read_status_files():
    """Читает все JSON-файлы из data/status/ и возвращает список."""
    pairs = []
    if not os.path.isdir(STATUS_DIR):
        return pairs
    for fname in sorted(os.listdir(STATUS_DIR)):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(STATUS_DIR, fname)) as f:
                pairs.append(json.load(f))
        except Exception:
            pass
    return pairs


def create_app():
    try:
        from flask import Flask, jsonify, request
    except ImportError:
        logger.error("[WebApp] Flask не установлен. Запусти: pip install flask --break-system-packages")
        return None

    app = Flask(__name__)
    app.logger.setLevel(logging.WARNING)

    @app.route("/")
    def index():
        return HTML

    @app.route("/api/status")
    def api_status():
        pairs = _read_status_files()
        return jsonify({"ok": True, "pairs": pairs, "ts": time.time()})

    @app.route("/api/settings", methods=["GET"])
    def api_settings_get():
        s = dynamic_settings.load()
        return jsonify(s)

    @app.route("/api/settings", methods=["POST"])
    def api_settings_post():
        try:
            data = request.get_json(force=True)
            ok = dynamic_settings.save(data)
            return jsonify({"ok": ok})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.route("/api/balance_chart")
    def api_balance_chart():
        days    = int(request.args.get("days", 7))
        user_id = request.args.get("user", None)
        try:
            import ccxt
            users_file = os.path.join("data", "users.json")
            if not os.path.exists(users_file):
                return jsonify({"error": "users.json not found", "dates": [], "values": []})

            with open(users_file, encoding="utf-8") as f:
                users = json.load(f)
            if not users:
                return jsonify({"error": "no users", "dates": [], "values": []})

            user = users.get(user_id) if user_id else next(iter(users.values()))
            if not user:
                return jsonify({"error": "user not found", "dates": [], "values": []})

            is_testnet = user.get("is_testnet", True)
            exchange = ccxt.binance({
                "apiKey":  user.get("api_key", ""),
                "secret":  user.get("api_secret", ""),
                "options": {"defaultType": "future"},
            })
            if is_testnet:
                exchange.set_sandbox_mode(True)

            start_ms = int((time.time() - days * 86400) * 1000)
            income = exchange.fapiPrivateGetIncome({
                "incomeType": "REALIZED_PNL",
                "startTime":  start_ms,
                "limit":      1000,
            })

            # Агрегируем PnL по дням
            daily: Dict[str, float] = {}
            for item in income:
                ts_sec = item["time"] / 1000
                day = time.strftime("%d.%m", time.gmtime(ts_sec))
                daily[day] = daily.get(day, 0.0) + float(item["income"])

            if not daily:
                return jsonify({"dates": [], "values": [], "currency": "USDT"})

            # Сортируем по хронологии и считаем кумулятивный PnL
            now = time.gmtime()
            def day_sort_key(d):
                try:
                    return time.mktime(time.strptime(
                        d + "." + str(now.tm_year), "%d.%m.%Y"
                    ))
                except Exception:
                    return 0

            dates, values, cumsum = [], [], 0.0
            for day in sorted(daily.keys(), key=day_sort_key):
                cumsum += daily[day]
                dates.append(day)
                values.append(round(cumsum, 4))

            return jsonify({"dates": dates, "values": values, "currency": "USDT"})

        except Exception as e:
            logger.error(f"[BalanceChart] {e}")
            return jsonify({"error": str(e), "dates": [], "values": []})

    return app


def start_web_server(port: int = 8080):
    """Запускает Flask в daemon-потоке. Вызывать из main.py."""
    app = create_app()
    if app is None:
        return

    def _run():
        try:
            app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
        except Exception as e:
            logger.error(f"[WebApp] Ошибка сервера: {e}")

    t = threading.Thread(target=_run, daemon=True, name="WebApp")
    t.start()
    logger.info(f"[WebApp] Запущен на порту {port} -> http://0.0.0.0:{port}")
