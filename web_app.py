# ============================================================
#  web_app.py — веб-интерфейс Trading Bot (мобильный, тёмная тема)
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

HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Trading Bot</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.2/css/bootstrap.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  :root {
    --bg:     #0d1117; --card:   #161b22; --border: #30363d;
    --text:   #e6edf3; --muted:  #8b949e; --green:  #3fb950;
    --red:    #f85149; --yellow: #d29922; --blue:   #58a6ff;
    --accent: #1f6feb;
  }
  * { box-sizing: border-box; }
  body {
    background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 14px; margin: 0; padding-bottom: 90px;
  }
  .header {
    background: var(--card); border-bottom: 1px solid var(--border);
    padding: 12px 16px; display: flex; align-items: center;
    justify-content: space-between; position: sticky; top: 0; z-index: 100;
  }
  .header-title { font-size: 16px; font-weight: 700; }
  .status-dot {
    width: 8px; height: 8px; border-radius: 50%; background: var(--green);
    display: inline-block; margin-right: 6px; animation: pulse 2s infinite;
  }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
  .last-update { font-size: 11px; color: var(--muted); }

  /* Pair cards */
  .pair-card {
    background: var(--card); border: 1px solid var(--border);
    border-radius: 10px; padding: 14px 16px; margin: 10px 12px 0;
  }
  .pair-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }
  .pair-name { font-weight: 700; font-size: 15px; }
  .pair-price { font-size: 15px; font-weight: 600; }
  .badge-long  { background: rgba(63,185,80,.15);  color: var(--green); }
  .badge-short { background: rgba(248,81,73,.15);  color: var(--red);   }
  .badge-none  { background: rgba(139,148,158,.1); color: var(--muted); }
  .pos-row {
    display: flex; justify-content: space-between;
    font-size: 12px; color: var(--muted); margin-top: 4px;
  }
  .pnl-pos { color: var(--green); font-weight: 600; }
  .pnl-neg { color: var(--red);   font-weight: 600; }

  /* Activity badge */
  .state-searching  { background: rgba(88,166,255,.12); color: var(--blue);   font-size:11px; padding:2px 8px; border-radius:10px; }
  .state-in_position{ background: rgba(63,185,80,.15);  color: var(--green);  font-size:11px; padding:2px 8px; border-radius:10px; }
  .state-paused     { background: rgba(210,153,34,.12); color: var(--yellow); font-size:11px; padding:2px 8px; border-radius:10px; }
  .state-delay      { background: rgba(210,153,34,.12); color: var(--yellow); font-size:11px; padding:2px 8px; border-radius:10px; }
  .state-stale      { background: rgba(248,81,73,.15);  color: var(--red);    font-size:11px; padding:2px 8px; border-radius:10px; }

  /* Tick age bar */
  .tick-age { height: 3px; border-radius: 2px; margin-top: 8px; transition: background .5s; }

  /* Section */
  .section {
    margin: 16px 12px 0; background: var(--card);
    border: 1px solid var(--border); border-radius: 10px; overflow: hidden;
  }
  .section-header {
    padding: 12px 16px; font-weight: 700; font-size: 13px;
    color: var(--muted); text-transform: uppercase; letter-spacing: .5px;
    border-bottom: 1px solid var(--border);
    display: flex; justify-content: space-between; align-items: center;
  }
  .setting-row { padding: 12px 16px; border-bottom: 1px solid var(--border); }
  .setting-row:last-child { border-bottom: none; }
  .setting-label { display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; }
  .setting-name { font-size: 13px; }
  .setting-val  { font-size:13px; font-weight:700; color:var(--blue); min-width:52px; text-align:right; }
  .setting-hint { font-size:11px; color:var(--muted); margin-top:2px; }

  input[type=range] {
    -webkit-appearance: none; width:100%; height:4px; border-radius:2px;
    background:var(--border); outline:none; cursor:pointer;
  }
  input[type=range]::-webkit-slider-thumb {
    -webkit-appearance:none; width:18px; height:18px;
    border-radius:50%; background:var(--accent); border:2px solid var(--bg);
  }

  /* Pair selector */
  .pair-btn {
    background: var(--border); color: var(--muted); border: none;
    border-radius: 6px; padding: 5px 10px; font-size: 12px; font-weight: 600;
    cursor: pointer; transition: background .15s, color .15s;
  }
  .pair-btn.active { background: var(--accent); color: #fff; }

  /* Period buttons */
  .period-btn {
    background: var(--border); color: var(--muted); border: none;
    border-radius: 6px; padding: 4px 10px; font-size: 12px; font-weight: 600;
    cursor: pointer; transition: background .15s, color .15s;
  }
  .period-btn.active { background: var(--accent); color: #fff; }

  /* Save bar */
  .save-bar {
    position: fixed; bottom:0; left:0; right:0;
    background:var(--card); border-top:1px solid var(--border);
    padding:12px 16px; z-index:200;
  }
  .btn-save {
    width:100%; background:var(--accent); color:#fff; border:none;
    border-radius:8px; padding:13px; font-size:15px; font-weight:700;
    cursor:pointer; transition:opacity .2s;
  }
  .btn-save:active { opacity:.8; }
  .btn-save:disabled { opacity:.5; cursor:default; }

  /* Toast */
  .toast-wrap { position:fixed; top:60px; left:50%; transform:translateX(-50%); z-index:999; pointer-events:none; }
  .toast-msg  { background:var(--green); color:#fff; padding:10px 20px; border-radius:20px; font-weight:600; font-size:13px; opacity:0; transition:opacity .3s; }
  .toast-msg.show { opacity:1; }
  .toast-msg.err  { background:var(--red); }
</style>
</head>
<body>

<div class="header">
  <div><span class="status-dot"></span><span class="header-title">Trading Bot</span></div>
  <span class="last-update" id="last-update">--</span>
</div>
<div class="toast-wrap"><div class="toast-msg" id="toast"></div></div>

<!-- Pair cards -->
<div id="pairs-section"></div>

<!-- PnL Chart -->
<div class="section">
  <div class="section-header">
    <span>ИСТОРИЯ PNL</span>
    <div style="display:flex;gap:6px">
      <button class="period-btn" id="p1"  onclick="loadChart(1)">1д</button>
      <button class="period-btn active" id="p7" onclick="loadChart(7)">7д</button>
      <button class="period-btn" id="p30" onclick="loadChart(30)">30д</button>
    </div>
  </div>
  <div style="padding:12px 16px 16px">
    <div id="chart-msg" style="text-align:center;color:var(--muted);font-size:13px;padding:24px 0">Загрузка...</div>
    <canvas id="pnl-chart" style="display:none"></canvas>
  </div>
</div>

<!-- Settings -->
<div class="section">
  <div class="section-header">
    <span>НАСТРОЙКИ TP / SL</span>
    <div id="pair-selector" style="display:flex;gap:5px;flex-wrap:wrap"></div>
  </div>

  <div class="setting-row">
    <div class="setting-label">
      <span class="setting-name">Take Profit (%)</span>
      <span class="setting-val" id="val-tp_pct">--</span>
    </div>
    <input type="range" id="tp_pct" min="0.05" max="3.0" step="0.05"
      oninput="onSlider('tp_pct', this.value, '%', 100)">
    <div class="setting-hint">Цель прибыли на сделку</div>
  </div>

  <div class="setting-row">
    <div class="setting-label">
      <span class="setting-name">Stop Loss (%)</span>
      <span class="setting-val" id="val-sl_pct">--</span>
    </div>
    <input type="range" id="sl_pct" min="0.1" max="20.0" step="0.1"
      oninput="onSlider('sl_pct', this.value, '%', 100)">
    <div class="setting-hint">Максимальный убыток на сделку</div>
  </div>

  <div class="setting-row">
    <div class="setting-label">
      <span class="setting-name">Размер позиции (% депозита)</span>
      <span class="setting-val" id="val-position_pct">--</span>
    </div>
    <input type="range" id="position_pct" min="1" max="20" step="1"
      oninput="onSlider('position_pct', this.value, '%', 100)">
  </div>
</div>

<div style="height:16px"></div>

<div class="save-bar">
  <button class="btn-save" id="btn-save" onclick="saveSettings()">Сохранить настройки</button>
</div>

<script>
const settings = {};
let selectedPairs = [];   // [] = все пары
let activePairs   = [];   // список пар из /api/status

// ── Загрузка настроек ──
async function loadSettings() {
  try {
    const r    = await fetch('/api/settings');
    const data = await r.json();
    Object.assign(settings, data);
    applySettingsToUI(data);
  } catch(e) { console.error('loadSettings:', e); }
}

function applySettingsToUI(data) {
  const fields = [
    ['tp_pct',       100, '%'],
    ['sl_pct',       100, '%'],
    ['position_pct', 100, '%'],
  ];
  fields.forEach(function(f) {
    var key = f[0], mult = f[1], suffix = f[2];
    var el  = document.getElementById(key);
    var val = data[key];
    if (el && val !== undefined) {
      el.value = val * mult;
      var disp = document.getElementById('val-' + key);
      if (disp) disp.textContent = (val * mult).toFixed(2) + suffix;
    }
  });
}

function onSlider(key, rawVal, suffix, divisor) {
  var num = parseFloat(rawVal);
  settings[key] = num / divisor;
  var disp = document.getElementById('val-' + key);
  if (disp) disp.textContent = num.toFixed(2) + suffix;
}

// ── Сохранение ──
async function saveSettings() {
  var btn = document.getElementById('btn-save');
  btn.disabled = true;
  btn.textContent = 'Сохраняем...';
  try {
    var payload = { settings: settings, pairs: selectedPairs };
    var r = await fetch('/api/settings', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    var res = await r.json();
    var pairsLabel = selectedPairs.length ? selectedPairs.join(', ') : 'все пары';
    if (res.ok) showToast('Сохранено для: ' + pairsLabel, false);
    else        showToast('Ошибка сохранения', true);
  } catch(e) { showToast('Ошибка: ' + e.message, true); }
  btn.disabled = false;
  btn.textContent = 'Сохранить настройки';
}

// ── Выбор пар ──
function buildPairSelector(pairs) {
  var container = document.getElementById('pair-selector');
  if (!pairs.length) { container.innerHTML = ''; return; }

  // Кнопка "ВСЕ"
  var allBtn = document.createElement('button');
  allBtn.className = 'pair-btn' + (selectedPairs.length === 0 ? ' active' : '');
  allBtn.textContent = 'ВСЕ';
  allBtn.onclick = function() { selectedPairs = []; updatePairBtns(); };
  container.appendChild(allBtn);

  pairs.forEach(function(sym) {
    var btn = document.createElement('button');
    var short = sym.replace('/USDT', '');
    btn.className = 'pair-btn' + (selectedPairs.includes(sym) ? ' active' : '');
    btn.textContent = short;
    btn.dataset.sym = sym;
    btn.onclick = function() {
      if (selectedPairs.includes(sym)) {
        selectedPairs = selectedPairs.filter(function(s){ return s !== sym; });
      } else {
        selectedPairs.push(sym);
      }
      updatePairBtns();
    };
    container.appendChild(btn);
  });
}

function updatePairBtns() {
  var container = document.getElementById('pair-selector');
  var btns = container.querySelectorAll('.pair-btn');
  btns.forEach(function(btn) {
    if (!btn.dataset.sym) {
      btn.className = 'pair-btn' + (selectedPairs.length === 0 ? ' active' : '');
    } else {
      btn.className = 'pair-btn' + (selectedPairs.includes(btn.dataset.sym) ? ' active' : '');
    }
  });
}

// ── Статус пар ──
async function loadStatus() {
  try {
    var r    = await fetch('/api/status');
    var data = await r.json();
    var pairs = data.pairs || [];
    renderPairs(pairs);

    // Обновляем список активных пар
    var syms = pairs.map(function(p){ return p.symbol; });
    if (JSON.stringify(syms) !== JSON.stringify(activePairs)) {
      activePairs = syms;
      buildPairSelector(activePairs);
    }

    document.getElementById('last-update').textContent =
      new Date().toLocaleTimeString('ru-RU', {hour:'2-digit',minute:'2-digit',second:'2-digit'});
  } catch(e) { console.error('loadStatus:', e); }
}

function renderPairs(pairs) {
  var container = document.getElementById('pairs-section');
  if (!pairs.length) {
    container.innerHTML = '<div style="padding:20px 16px;color:var(--muted);text-align:center">Нет данных — бот ещё не запущен</div>';
    return;
  }
  var now = Date.now() / 1000;
  container.innerHTML = pairs.map(function(p) {
    var pos = p.position;
    var hasPos = pos && pos.side;
    var sideBadge = hasPos
      ? '<span class="badge rounded-pill badge-' + pos.side + '">' + (pos.side === 'long' ? 'LONG' : 'SHORT') + '</span>'
      : '<span class="badge rounded-pill badge-none">нет позиции</span>';

    // Состояние бота
    var age  = now - (p.updated_at || now);
    var state = age > 60 ? 'stale' : (p.bot_state || 'searching');
    var stateLabel = age > 60
      ? 'Нет ответа ' + Math.round(age) + 'с'
      : (p.bot_state_label || 'Ищу сигнал');

    // Цвет полоски свежести тика
    var barColor = age < 25 ? '#3fb950' : age < 60 ? '#d29922' : '#f85149';

    var pnlClass = p.session_pnl >= 0 ? 'pnl-pos' : 'pnl-neg';
    var pnlSign  = p.session_pnl >= 0 ? '+' : '';

    var posRows = '';
    if (hasPos) {
      posRows = '<div class="pos-row">' +
        '<span>Вход: <b>' + (pos.entry_price ? pos.entry_price.toFixed(2) : '--') + '</b></span>' +
        '<span>TP: <b style="color:var(--green)">' + (pos.tp_price ? pos.tp_price.toFixed(2) : '--') + '</b></span>' +
        '<span>SL: <b style="color:var(--red)">'   + (pos.sl_price ? pos.sl_price.toFixed(2) : '--') + '</b></span>' +
        '</div>';
    }

    return '<div class="pair-card">' +
      '<div class="pair-header">' +
        '<span class="pair-name">' + p.symbol + '</span>' +
        '<span class="pair-price">$' + (p.price||0).toLocaleString('en-US',{maximumFractionDigits:2}) + '</span>' +
      '</div>' +
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">' +
        sideBadge +
        '<span class="state-' + state + '">' + stateLabel + '</span>' +
      '</div>' +
      posRows +
      '<div class="pos-row" style="margin-top:8px">' +
        '<span>RSI: <b>' + p.rsi + '</b></span>' +
        '<span>W/L: <b style="color:var(--green)">' + (p.win_streak||0) + '</b> / <b style="color:var(--red)">' + (p.loss_streak||0) + '</b></span>' +
        '<span>PnL: <b class="' + pnlClass + '">' + pnlSign + (p.session_pnl||0).toFixed(4) + '</b></span>' +
      '</div>' +
      '<div class="tick-age" style="background:' + barColor + ';opacity:' + Math.max(0.2, 1 - age/120) + '"></div>' +
    '</div>';
  }).join('');
}

// ── PnL Chart ──
var pnlChart = null;

async function loadChart(days) {
  ['p1','p7','p30'].forEach(function(id){
    document.getElementById(id).classList.remove('active');
  });
  document.getElementById('p' + days).classList.add('active');

  var msg    = document.getElementById('chart-msg');
  var canvas = document.getElementById('pnl-chart');
  msg.style.display    = 'block';
  canvas.style.display = 'none';
  msg.textContent      = 'Загрузка...';

  try {
    var r    = await fetch('/api/balance_chart?days=' + days);
    var data = await r.json();

    if (!data.dates || data.dates.length === 0) {
      msg.textContent = data.error || 'Нет данных за этот период';
      return;
    }
    msg.style.display    = 'none';
    canvas.style.display = 'block';
    if (pnlChart) { pnlChart.destroy(); pnlChart = null; }

    var last    = data.values[data.values.length - 1];
    var color   = last >= 0 ? '#3fb950' : '#f85149';
    var showDot = data.dates.length <= 14;

    pnlChart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: data.dates,
        datasets: [{ label:'PnL USDT', data:data.values,
          borderColor:color, backgroundColor:color+'22', fill:true,
          tension:0.3, pointRadius:showDot?3:0, pointHoverRadius:5, borderWidth:2 }]
      },
      options: {
        responsive: true,
        plugins: {
          legend: { display:false },
          tooltip: { callbacks: { label: function(ctx){ return (ctx.raw>=0?'+':'')+ctx.raw.toFixed(4)+' USDT'; } } }
        },
        scales: {
          x: { ticks:{color:'#8b949e',maxTicksLimit:7,maxRotation:0}, grid:{color:'#30363d'} },
          y: { ticks:{color:'#8b949e', callback:function(v){return (v>=0?'+':'')+v.toFixed(2);}}, grid:{color:'#30363d'} }
        }
      }
    });
  } catch(e) {
    msg.style.display='block'; canvas.style.display='none';
    msg.textContent='Ошибка: '+e.message;
  }
}

// ── Toast ──
function showToast(msg, isError) {
  var t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast-msg show' + (isError ? ' err' : '');
  setTimeout(function(){ t.className='toast-msg'; }, 2500);
}

// ── Init ──
loadSettings();
loadStatus();
loadChart(7);
setInterval(loadStatus, 10000);
</script>
</body>
</html>"""


# ──────────────────────────────────────────────────────────────
#  Flask API
# ──────────────────────────────────────────────────────────────

def _read_status_files():
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
        logger.error("[WebApp] Flask не установлен.")
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
        return jsonify(dynamic_settings.load())

    @app.route("/api/settings", methods=["POST"])
    def api_settings_post():
        """
        Принимает {settings: {...}, pairs: ["BTC/USDT", ...]}
        Если pairs пустой — обновляет глобальные настройки.
        Если pairs заданы — обновляет только pair_overrides для этих пар.
        """
        try:
            body     = request.get_json(force=True)
            new_vals = body.get("settings", body)   # backward compat
            pairs    = body.get("pairs", [])

            current = dynamic_settings.load()

            if not pairs:
                # Глобальные настройки
                current["tp_pct"]       = float(new_vals.get("tp_pct",       current["tp_pct"]))
                current["sl_pct"]       = float(new_vals.get("sl_pct",       current["sl_pct"]))
                current["position_pct"] = float(new_vals.get("position_pct", current["position_pct"]))
            else:
                # Per-pair overrides
                overrides = current.get("pair_overrides", {})
                for sym in pairs:
                    overrides[sym] = {
                        "tp_pct": float(new_vals.get("tp_pct",       current["tp_pct"])),
                        "sl_pct": float(new_vals.get("sl_pct",       current["sl_pct"])),
                    }
                current["pair_overrides"] = overrides

            ok = dynamic_settings.save(current)
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

            daily: Dict[str, float] = {}
            for item in income:
                day = time.strftime("%d.%m", time.gmtime(item["time"] / 1000))
                daily[day] = daily.get(day, 0.0) + float(item["income"])

            if not daily:
                return jsonify({"dates": [], "values": [], "currency": "USDT"})

            now = time.gmtime()
            def day_key(d):
                try:
                    return time.mktime(time.strptime(d + "." + str(now.tm_year), "%d.%m.%Y"))
                except Exception:
                    return 0

            dates, values, cumsum = [], [], 0.0
            for day in sorted(daily.keys(), key=day_key):
                cumsum += daily[day]
                dates.append(day)
                values.append(round(cumsum, 4))

            return jsonify({"dates": dates, "values": values, "currency": "USDT"})

        except Exception as e:
            logger.error(f"[BalanceChart] {e}")
            return jsonify({"error": str(e), "dates": [], "values": []})

    return app


def start_web_server(port: int = 8080):
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
