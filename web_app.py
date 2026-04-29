# ============================================================
#  web_app.py — веб-интерфейс Trading Bot
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
    --bg:#0d1117; --card:#161b22; --border:#30363d;
    --text:#e6edf3; --muted:#8b949e; --green:#3fb950;
    --red:#f85149; --yellow:#d29922; --blue:#58a6ff; --accent:#1f6feb;
  }
  * { box-sizing:border-box; }
  body { background:var(--bg); color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
    font-size:14px; margin:0; padding-bottom:90px; }

  .header { background:var(--card); border-bottom:1px solid var(--border);
    padding:12px 16px; display:flex; align-items:center;
    justify-content:space-between; position:sticky; top:0; z-index:100; }
  .header-title { font-size:16px; font-weight:700; }
  .status-dot { width:8px; height:8px; border-radius:50%; background:var(--green);
    display:inline-block; margin-right:6px; animation:pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
  .last-update { font-size:11px; color:var(--muted); }

  /* Pair cards */
  .pair-card { background:var(--card); border:1px solid var(--border);
    border-radius:10px; padding:14px 16px; margin:10px 12px 0; cursor:pointer;
    transition:border-color .15s; }
  .pair-card:active { border-color:var(--accent); }
  .pair-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }
  .pair-name { font-weight:700; font-size:15px; }
  .pair-price { font-size:15px; font-weight:600; }
  .badge-long  { background:rgba(63,185,80,.15);  color:var(--green); }
  .badge-short { background:rgba(248,81,73,.15);  color:var(--red);   }
  .badge-none  { background:rgba(139,148,158,.1); color:var(--muted); }
  .pos-row { display:flex; justify-content:space-between; font-size:12px; color:var(--muted); margin-top:4px; }
  .pnl-pos { color:var(--green); font-weight:600; }
  .pnl-neg { color:var(--red);   font-weight:600; }

  /* State badges */
  .state-searching   { background:rgba(88,166,255,.12); color:var(--blue);   font-size:11px; padding:2px 8px; border-radius:10px; }
  .state-in_position { background:rgba(63,185,80,.15);  color:var(--green);  font-size:11px; padding:2px 8px; border-radius:10px; }
  .state-paused      { background:rgba(210,153,34,.12); color:var(--yellow); font-size:11px; padding:2px 8px; border-radius:10px; }
  .state-delay       { background:rgba(210,153,34,.12); color:var(--yellow); font-size:11px; padding:2px 8px; border-radius:10px; }
  .state-stale       { background:rgba(248,81,73,.15);  color:var(--red);    font-size:11px; padding:2px 8px; border-radius:10px; }
  .tick-age { height:3px; border-radius:2px; margin-top:8px; transition:background .5s; }

  /* Section */
  .section { margin:16px 12px 0; background:var(--card);
    border:1px solid var(--border); border-radius:10px; overflow:hidden; }
  .section-header { padding:12px 16px; font-weight:700; font-size:13px;
    color:var(--muted); text-transform:uppercase; letter-spacing:.5px;
    border-bottom:1px solid var(--border);
    display:flex; justify-content:space-between; align-items:center; }
  .setting-row { padding:12px 16px; border-bottom:1px solid var(--border); }
  .setting-row:last-child { border-bottom:none; }
  .setting-label { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }
  .setting-name { font-size:13px; }
  .setting-hint { font-size:11px; color:var(--muted); margin-top:4px; }

  input[type=range] { -webkit-appearance:none; width:100%; height:4px; border-radius:2px;
    background:var(--border); outline:none; cursor:pointer; }
  input[type=range]::-webkit-slider-thumb { -webkit-appearance:none; width:18px; height:18px;
    border-radius:50%; background:var(--accent); border:2px solid var(--bg); }

  /* Number input */
  .num-input { background:var(--bg); border:1px solid var(--border); border-radius:6px;
    color:var(--blue); padding:4px 8px; width:76px; font-size:13px; font-weight:700;
    text-align:right; outline:none; }
  .num-input:focus { border-color:var(--accent); }
  /* hide spinners */
  .num-input::-webkit-inner-spin-button, .num-input::-webkit-outer-spin-button { -webkit-appearance:none; }

  /* Pair/period buttons */
  .pair-btn, .period-btn { background:var(--border); color:var(--muted); border:none;
    border-radius:6px; padding:4px 10px; font-size:12px; font-weight:600;
    cursor:pointer; transition:background .15s,color .15s; }
  .pair-btn.active, .period-btn.active { background:var(--accent); color:#fff; }

  /* Save bar */
  .save-bar { position:fixed; bottom:0; left:0; right:0; background:var(--card);
    border-top:1px solid var(--border); padding:12px 16px; z-index:200; }
  .btn-save { width:100%; background:var(--accent); color:#fff; border:none;
    border-radius:8px; padding:13px; font-size:15px; font-weight:700;
    cursor:pointer; transition:opacity .2s; }
  .btn-save:active { opacity:.8; } .btn-save:disabled { opacity:.5; cursor:default; }

  /* Toast */
  .toast-wrap { position:fixed; top:60px; left:50%; transform:translateX(-50%);
    z-index:999; pointer-events:none; }
  .toast-msg { background:var(--green); color:#fff; padding:10px 20px; border-radius:20px;
    font-weight:600; font-size:13px; opacity:0; transition:opacity .3s; }
  .toast-msg.show { opacity:1; } .toast-msg.err { background:var(--red); }

  /* Pair detail panel */
  #pair-detail { display:none; position:fixed; inset:0; background:var(--bg);
    z-index:500; flex-direction:column; overflow:hidden; }
  #pair-detail.open { display:flex; }
  .detail-header { background:var(--card); border-bottom:1px solid var(--border);
    padding:12px 16px; display:flex; align-items:center;
    justify-content:space-between; flex-shrink:0; }
  .detail-title { font-size:16px; font-weight:700; }
  .detail-price { font-size:15px; font-weight:600; color:var(--blue); }
  .btn-close { background:var(--border); border:none; color:var(--text);
    border-radius:6px; padding:6px 14px; font-size:14px; cursor:pointer; }
  #chart-container { flex:1; min-height:0; }
  .detail-footer { background:var(--card); border-top:1px solid var(--border);
    padding:10px 16px; flex-shrink:0; display:flex; gap:16px; font-size:12px; }
  .detail-footer span { color:var(--muted); }
  .detail-footer b { font-size:13px; }
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
      <input type="number" class="num-input" id="num-tp_pct" min="0.05" max="3.0" step="0.05"
        oninput="onNumInput('tp_pct',this.value,100,'0.05','3.0')">
    </div>
    <input type="range" id="tp_pct" min="0.05" max="3.0" step="0.05"
      oninput="onSlider('tp_pct',this.value,100)">
    <div class="setting-hint">Цель прибыли на сделку</div>
  </div>

  <div class="setting-row">
    <div class="setting-label">
      <span class="setting-name">Stop Loss (%)</span>
      <input type="number" class="num-input" id="num-sl_pct" min="0.1" max="20.0" step="0.1"
        oninput="onNumInput('sl_pct',this.value,100,'0.1','20.0')">
    </div>
    <input type="range" id="sl_pct" min="0.1" max="20.0" step="0.1"
      oninput="onSlider('sl_pct',this.value,100)">
    <div class="setting-hint">Максимальный убыток на сделку</div>
  </div>

  <div class="setting-row">
    <div class="setting-label">
      <span class="setting-name">Размер позиции (% депозита)</span>
      <input type="number" class="num-input" id="num-position_pct" min="1" max="20" step="1"
        oninput="onNumInput('position_pct',this.value,100,'1','20')">
    </div>
    <input type="range" id="position_pct" min="1" max="20" step="1"
      oninput="onSlider('position_pct',this.value,100)">
  </div>
</div>

<div style="height:16px"></div>
<div class="save-bar">
  <button class="btn-save" id="btn-save" onclick="saveSettings()">Сохранить настройки</button>
</div>

<!-- Pair detail panel (candlestick chart) -->
<div id="pair-detail">
  <div class="detail-header">
    <div>
      <div class="detail-title" id="detail-title">--</div>
      <div id="detail-state" style="font-size:11px;color:var(--muted);margin-top:2px"></div>
    </div>
    <div style="display:flex;align-items:center;gap:12px">
      <span class="detail-price" id="detail-price">--</span>
      <button class="btn-close" onclick="closeDetail()">✕</button>
    </div>
  </div>
  <div id="chart-container"></div>
  <div class="detail-footer" id="detail-footer" style="display:none">
    <span>Вход: <b id="df-entry">--</b></span>
    <span>TP: <b id="df-tp" style="color:var(--green)">--</b></span>
    <span>SL: <b id="df-sl" style="color:var(--red)">--</b></span>
    <span>PnL: <b id="df-pnl">--</b></span>
  </div>
</div>

<script>
const settings = {};
let selectedPairs = [];
let activePairs   = [];
let pairsData     = [];

// ── Settings ──
async function loadSettings() {
  try {
    var r = await fetch('/api/settings');
    var d = await r.json();
    Object.assign(settings, d);
    applySettingsToUI(d);
  } catch(e) { console.error(e); }
}

function applySettingsToUI(data) {
  [['tp_pct',100],['sl_pct',100],['position_pct',100]].forEach(function(f){
    var key=f[0], mult=f[1];
    var slider = document.getElementById(key);
    var num    = document.getElementById('num-'+key);
    var val = data[key];
    if (val === undefined) return;
    var display = +(val * mult).toFixed(2);
    if (slider) slider.value = display;
    if (num)    num.value    = display;
  });
}

function onSlider(key, rawVal, mult) {
  var num = parseFloat(rawVal);
  settings[key] = num / mult;
  var ni = document.getElementById('num-'+key);
  if (ni) ni.value = num.toFixed(2);
}

function onNumInput(key, rawVal, mult, minV, maxV) {
  var num = parseFloat(rawVal);
  if (isNaN(num)) return;
  num = Math.min(Math.max(num, parseFloat(minV)), parseFloat(maxV));
  settings[key] = num / mult;
  var slider = document.getElementById(key);
  if (slider) slider.value = num;
}

async function saveSettings() {
  var btn = document.getElementById('btn-save');
  btn.disabled = true; btn.textContent = 'Сохраняем...';
  try {
    var r = await fetch('/api/settings', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({settings:settings, pairs:selectedPairs}),
    });
    var res = await r.json();
    var lbl = selectedPairs.length ? selectedPairs.join(', ') : 'все пары';
    if (res.ok) showToast('Сохранено: '+lbl, false);
    else        showToast('Ошибка', true);
  } catch(e) { showToast('Ошибка: '+e.message, true); }
  btn.disabled = false; btn.textContent = 'Сохранить настройки';
}

// ── Pair selector ──
function buildPairSelector(pairs) {
  var c = document.getElementById('pair-selector');
  c.innerHTML = '';
  var allBtn = document.createElement('button');
  allBtn.className = 'pair-btn'+(selectedPairs.length===0?' active':'');
  allBtn.textContent = 'ВСЕ';
  allBtn.onclick = function(){ selectedPairs=[]; updatePairBtns(); };
  c.appendChild(allBtn);
  pairs.forEach(function(sym){
    var btn = document.createElement('button');
    btn.className = 'pair-btn'+(selectedPairs.includes(sym)?' active':'');
    btn.textContent = sym.replace('/USDT','');
    btn.dataset.sym = sym;
    btn.onclick = function(){
      if (selectedPairs.includes(sym)) selectedPairs = selectedPairs.filter(function(s){return s!==sym;});
      else selectedPairs.push(sym);
      updatePairBtns();
    };
    c.appendChild(btn);
  });
}
function updatePairBtns() {
  document.querySelectorAll('#pair-selector .pair-btn').forEach(function(btn){
    if (!btn.dataset.sym) btn.className='pair-btn'+(selectedPairs.length===0?' active':'');
    else btn.className='pair-btn'+(selectedPairs.includes(btn.dataset.sym)?' active':'');
  });
}

// ── Status / pair cards ──
async function loadStatus() {
  try {
    var r = await fetch('/api/status');
    var data = await r.json();
    pairsData = data.pairs || [];
    renderPairs(pairsData);
    var syms = pairsData.map(function(p){return p.symbol;});
    if (JSON.stringify(syms) !== JSON.stringify(activePairs)){
      activePairs = syms; buildPairSelector(activePairs);
    }
    document.getElementById('last-update').textContent =
      new Date().toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit'});

    // Обновляем открытую панель если она открыта
    if (currentDetailSym) refreshDetailHeader();
  } catch(e) { console.error(e); }
}

function renderPairs(pairs) {
  var c = document.getElementById('pairs-section');
  if (!pairs.length) {
    c.innerHTML = '<div style="padding:20px 16px;color:var(--muted);text-align:center">Нет данных — бот ещё не запущен</div>';
    return;
  }
  var now = Date.now()/1000;
  c.innerHTML = pairs.map(function(p){
    var pos = p.position, hasPos = pos && pos.side;
    var sideBadge = hasPos
      ? '<span class="badge rounded-pill badge-'+pos.side+'">'+(pos.side==='long'?'LONG':'SHORT')+'</span>'
      : '<span class="badge rounded-pill badge-none">нет позиции</span>';
    var age = now - (p.updated_at||now);
    var state = age>60 ? 'stale' : (p.bot_state||'searching');
    var stateLabel = age>60 ? 'Нет ответа '+Math.round(age)+'с' : (p.bot_state_label||'Ищу сигнал');
    var barColor = age<25 ? '#3fb950' : age<60 ? '#d29922' : '#f85149';
    var pnlClass = p.session_pnl>=0 ? 'pnl-pos' : 'pnl-neg';
    var pnlSign  = p.session_pnl>=0 ? '+' : '';
    var posRows = '';
    if (hasPos) posRows =
      '<div class="pos-row">'+
        '<span>Вход: <b>'+(pos.entry_price?pos.entry_price.toFixed(2):'--')+'</b></span>'+
        '<span>TP: <b style="color:var(--green)">'+(pos.tp_price?pos.tp_price.toFixed(2):'--')+'</b></span>'+
        '<span>SL: <b style="color:var(--red)">'+(pos.sl_price?pos.sl_price.toFixed(2):'--')+'</b></span>'+
      '</div>';
    var safeSym = p.symbol.replace('/','_');
    return '<div class="pair-card" data-sym="'+p.symbol+'">'+
      '<div class="pair-header">'+
        '<span class="pair-name">'+p.symbol+'</span>'+
        '<span class="pair-price">$'+(p.price||0).toLocaleString('en-US',{maximumFractionDigits:2})+'</span>'+
      '</div>'+
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">'+
        sideBadge+
        '<span class="state-'+state+'">'+stateLabel+'</span>'+
      '</div>'+
      posRows+
      '<div class="pos-row" style="margin-top:8px">'+
        '<span>RSI: <b>'+p.rsi+'</b></span>'+
        '<span>W/L: <b style="color:var(--green)">'+(p.win_streak||0)+'</b>/<b style="color:var(--red)">'+(p.loss_streak||0)+'</b></span>'+
        '<span>PnL: <b class="'+pnlClass+'">'+pnlSign+(p.session_pnl||0).toFixed(4)+'</b></span>'+
      '</div>'+
      '<div class="tick-age" style="background:'+barColor+';opacity:'+Math.max(0.2,1-age/120)+'"></div>'+
    '</div>';
  }).join('');
}

// ── Pair card click delegation ──
document.addEventListener('click', function(e) {
  var card = e.target.closest('.pair-card');
  if (card && card.dataset.sym) openDetail(card.dataset.sym);
});

// ── PnL line chart ──
var pnlChart = null;
async function loadChart(days) {
  ['p1','p7','p30'].forEach(function(id){document.getElementById(id).classList.remove('active');});
  document.getElementById('p'+days).classList.add('active');
  var msg=document.getElementById('chart-msg'), canvas=document.getElementById('pnl-chart');
  msg.style.display='block'; canvas.style.display='none'; msg.textContent='Загрузка...';
  try {
    var r=await fetch('/api/balance_chart?days='+days);
    var data=await r.json();
    if (!data.dates||!data.dates.length){msg.textContent=data.error||'Нет данных'; return;}
    msg.style.display='none'; canvas.style.display='block';
    if (pnlChart){pnlChart.destroy();pnlChart=null;}
    var last=data.values[data.values.length-1], color=last>=0?'#3fb950':'#f85149';
    pnlChart=new Chart(canvas.getContext('2d'),{type:'line',data:{labels:data.dates,datasets:[{
      label:'PnL',data:data.values,borderColor:color,backgroundColor:color+'22',fill:true,
      tension:0.3,pointRadius:data.dates.length<=14?3:0,pointHoverRadius:5,borderWidth:2}]},
      options:{responsive:true,plugins:{legend:{display:false},tooltip:{callbacks:{label:function(ctx){
        return (ctx.raw>=0?'+':'')+ctx.raw.toFixed(4)+' USDT';
      }}}},scales:{
        x:{ticks:{color:'#8b949e',maxTicksLimit:7,maxRotation:0},grid:{color:'#30363d'}},
        y:{ticks:{color:'#8b949e',callback:function(v){return (v>=0?'+':'')+v.toFixed(2);}},grid:{color:'#30363d'}}
      }}});
  } catch(e){msg.style.display='block';canvas.style.display='none';msg.textContent='Ошибка: '+e.message;}
}

// ── Candlestick detail panel (canvas-based, no external deps) ──
var currentDetailSym = null;
var chartRefreshTimer = null;
var _lastOhlcvData = null;

async function openDetail(sym) {
  currentDetailSym = sym;
  var panel = document.getElementById('pair-detail');
  panel.classList.add('open');
  document.body.style.overflow = 'hidden';
  document.getElementById('detail-title').textContent = sym;
  document.getElementById('detail-state').textContent = '';
  document.getElementById('detail-price').textContent = '--';
  document.getElementById('detail-footer').style.display = 'none';
  await renderDetailChart(sym);
  chartRefreshTimer = setInterval(function(){ refreshDetailCandles(sym); }, 20000);
}

function closeDetail() {
  document.getElementById('pair-detail').classList.remove('open');
  document.body.style.overflow = '';
  currentDetailSym = null;
  _lastOhlcvData = null;
  if (chartRefreshTimer){ clearInterval(chartRefreshTimer); chartRefreshTimer=null; }
}

function drawCandleCanvas(container, data) {
  var candles = data.candles, tpPrice = data.tp_price,
      slPrice = data.sl_price, entryPrice = data.entry_price;
  container.innerHTML = '';
  var canvas = document.createElement('canvas');
  canvas.style.cssText = 'display:block;width:100%;height:100%';
  container.appendChild(canvas);

  var W = container.clientWidth  || 400;
  var H = container.clientHeight || 300;
  canvas.width  = W; canvas.height = H;
  var ctx = canvas.getContext('2d');

  var PAD = {top:20, right:72, bottom:36, left:6};
  var cW = W - PAD.left - PAD.right;
  var cH = H - PAD.top  - PAD.bottom;

  // Price range including TP/SL/Entry
  var prices = [];
  candles.forEach(function(c){ prices.push(c.high, c.low); });
  if (tpPrice)    prices.push(tpPrice);
  if (slPrice)    prices.push(slPrice);
  if (entryPrice) prices.push(entryPrice);
  var minP = Math.min.apply(null,prices), maxP = Math.max.apply(null,prices);
  var pad  = (maxP - minP) * 0.12 || minP * 0.01;
  minP -= pad; maxP += pad;
  var rangeP = maxP - minP;

  function toY(p){ return PAD.top + cH - (p - minP) / rangeP * cH; }
  var cand = Math.max(2, cW / candles.length);

  // Background
  ctx.fillStyle = '#0d1117';
  ctx.fillRect(0,0,W,H);

  // Grid
  ctx.strokeStyle = '#30363d'; ctx.lineWidth = 1;
  var priceTicks = 6;
  ctx.font = '10px sans-serif'; ctx.fillStyle = '#8b949e'; ctx.textAlign = 'left';
  for (var i=0; i<=priceTicks; i++){
    var pp = minP + rangeP/priceTicks*i;
    var yy = toY(pp);
    ctx.beginPath(); ctx.moveTo(PAD.left,yy); ctx.lineTo(W-PAD.right,yy); ctx.stroke();
    var lbl = pp >= 1000 ? pp.toFixed(0) : pp >= 1 ? pp.toFixed(2) : pp.toFixed(5);
    ctx.fillText(lbl, W-PAD.right+4, yy+4);
  }

  // Candles
  candles.forEach(function(c, i){
    var x = PAD.left + (i + 0.5) * cW / candles.length;
    var isUp = c.close >= c.open;
    var col  = isUp ? '#3fb950' : '#f85149';
    ctx.strokeStyle = col; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, toY(c.high)); ctx.lineTo(x, toY(c.low)); ctx.stroke();
    var bTop = toY(Math.max(c.open,c.close));
    var bBot = toY(Math.min(c.open,c.close));
    var bH   = Math.max(1, bBot - bTop);
    var bW   = Math.max(1, cand * 0.75);
    ctx.fillStyle = col;
    ctx.fillRect(x - bW/2, bTop, bW, bH);
  });

  // Horizontal price lines
  function hline(price, color, label){
    var y = toY(price);
    ctx.strokeStyle = color; ctx.lineWidth = 1.5;
    ctx.setLineDash([5,3]);
    ctx.beginPath(); ctx.moveTo(PAD.left,y); ctx.lineTo(W-PAD.right,y); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = color; ctx.font = 'bold 10px sans-serif'; ctx.textAlign = 'left';
    var p2 = price >= 1000 ? price.toFixed(1) : price >= 1 ? price.toFixed(3) : price.toFixed(6);
    ctx.fillText(label+' '+p2, W-PAD.right+4, y-2);
  }
  if (tpPrice)    hline(tpPrice,    '#3fb950', 'TP');
  if (slPrice)    hline(slPrice,    '#f85149', 'SL');
  if (entryPrice) hline(entryPrice, '#58a6ff', 'IN');

  // X-axis time labels
  var step = Math.max(1, Math.floor(candles.length/6));
  ctx.fillStyle = '#8b949e'; ctx.font = '10px sans-serif'; ctx.textAlign = 'center';
  candles.forEach(function(c, i){
    if (i % step === 0 || i === candles.length-1){
      var d = new Date(c.time * 1000);
      var tl = d.getHours().toString().padStart(2,'0')+':'+d.getMinutes().toString().padStart(2,'0');
      ctx.fillText(tl, PAD.left + (i+0.5)*cW/candles.length, H-PAD.bottom+14);
    }
  });
}

async function renderDetailChart(sym) {
  var container = document.getElementById('chart-container');
  container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--muted);font-size:14px">Загрузка свечей...</div>';
  try {
    var safeSym = sym.replace('/','_');
    var r = await fetch('/api/ohlcv/'+safeSym);
    var data = await r.json();
    if (!data.candles||!data.candles.length){
      container.innerHTML='<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--muted)">Нет данных</div>';
      return;
    }
    _lastOhlcvData = data;
    drawCandleCanvas(container, data);

    // Footer
    if (data.entry_price) {
      document.getElementById('detail-footer').style.display = 'flex';
      document.getElementById('df-entry').textContent = data.entry_price.toFixed(2);
      document.getElementById('df-tp').textContent = data.tp_price ? data.tp_price.toFixed(2) : '--';
      document.getElementById('df-sl').textContent = data.sl_price ? data.sl_price.toFixed(2) : '--';
    }
    refreshDetailHeader();
  } catch(e) {
    container.innerHTML='<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--muted)">Ошибка: '+e.message+'</div>';
  }
}

async function refreshDetailCandles(sym) {
  try {
    var safeSym = sym.replace('/','_');
    var r = await fetch('/api/ohlcv/'+safeSym);
    var data = await r.json();
    if (data.candles && data.candles.length) {
      _lastOhlcvData = data;
      var container = document.getElementById('chart-container');
      drawCandleCanvas(container, data);
    }
    refreshDetailHeader();
  } catch(e) {}
}

function refreshDetailHeader() {
  if (!currentDetailSym) return;
  var p = pairsData.find(function(x){return x.symbol===currentDetailSym;});
  if (!p) return;
  document.getElementById('detail-price').textContent =
    '$'+(p.price||0).toLocaleString('en-US',{maximumFractionDigits:2});
  document.getElementById('detail-state').textContent = p.bot_state_label || '';

  // PnL in footer
  var pnlEl = document.getElementById('df-pnl');
  if (pnlEl) {
    var pnl = p.session_pnl||0;
    pnlEl.textContent = (pnl>=0?'+':'')+pnl.toFixed(4)+' USDT';
    pnlEl.style.color = pnl>=0 ? 'var(--green)' : 'var(--red)';
  }
}

// ── Toast ──
function showToast(msg, isError) {
  var t=document.getElementById('toast');
  t.textContent=msg; t.className='toast-msg show'+(isError?' err':'');
  setTimeout(function(){t.className='toast-msg';},2500);
}

// ── Init ──
loadSettings(); loadStatus(); loadChart(7);
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


def _get_first_user():
    """Читает первого пользователя из users.json."""
    users_file = os.path.join("data", "users.json")
    if not os.path.exists(users_file):
        return None
    with open(users_file, encoding="utf-8") as f:
        users = json.load(f)
    if not users:
        return None
    return next(iter(users.values()))


def _notify_settings_changed(old: dict, new: dict, pairs: list):
    """Отправляет TG-уведомление об изменении настроек (читает токен из env)."""
    try:
        from telegram_notifier import TelegramNotifier
        token   = os.environ.get("TG_BOT_TOKEN", "")
        chat_id = os.environ.get("TG_CHAT_ID", "")
        # Запасной вариант: личный chat_id первого пользователя
        if not chat_id:
            user = _get_first_user()
            if user:
                chat_id = user.get("telegram_chat_id", "")
        if not token or not chat_id:
            return
        user     = _get_first_user()
        user_id  = user.get("user_id", "") if user else ""
        notifier = TelegramNotifier(bot_token=token, chat_id=chat_id, enabled=True)
        notifier.notify_settings_changed(old=old, new=new, pairs=pairs, user_id=user_id)
    except Exception as e:
        logger.debug(f"[WebApp] _notify_settings_changed: {e}")


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
        return jsonify({"ok": True, "pairs": _read_status_files(), "ts": time.time()})

    @app.route("/api/settings", methods=["GET"])
    def api_settings_get():
        return jsonify(dynamic_settings.load())

    @app.route("/api/settings", methods=["POST"])
    def api_settings_post():
        try:
            body     = request.get_json(force=True)
            new_vals = body.get("settings", body)
            pairs    = body.get("pairs", [])
            current  = dynamic_settings.load()
            old      = {k: v for k, v in current.items()}  # снапшот до изменений

            if not pairs:
                current["tp_pct"]       = float(new_vals.get("tp_pct",       current["tp_pct"]))
                current["sl_pct"]       = float(new_vals.get("sl_pct",       current["sl_pct"]))
                current["position_pct"] = float(new_vals.get("position_pct", current["position_pct"]))
            else:
                overrides = current.get("pair_overrides", {})
                for sym in pairs:
                    overrides[sym] = {
                        "tp_pct": float(new_vals.get("tp_pct", current["tp_pct"])),
                        "sl_pct": float(new_vals.get("sl_pct", current["sl_pct"])),
                    }
                current["pair_overrides"] = overrides

            saved = dynamic_settings.save(current)

            # Telegram: уведомление об изменении настроек
            if saved:
                try:
                    _notify_settings_changed(old, current, pairs)
                except Exception as _tg_err:
                    logger.debug(f"[WebApp] TG notify failed: {_tg_err}")

            return jsonify({"ok": saved})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.route("/api/ohlcv/<symbol>")
    def api_ohlcv(symbol):
        """symbol: BTC_USDT → BTC/USDT"""
        sym = symbol.replace("_", "/")
        try:
            import ccxt
            user = _get_first_user()
            if not user:
                return jsonify({"error": "no users", "candles": []})

            exchange = ccxt.binance({
                "apiKey":  user.get("api_key", ""),
                "secret":  user.get("api_secret", ""),
                "options": {"defaultType": "future"},
            })
            if user.get("is_testnet", True):
                exchange.set_sandbox_mode(True)

            ohlcv = exchange.fetch_ohlcv(sym, "1m", limit=120)
            candles = [{"time": c[0]//1000, "open": c[1], "high": c[2], "low": c[3], "close": c[4]}
                       for c in ohlcv]

            # Читаем позицию из status-файла
            safe_sym    = sym.replace("/", "_")
            status_path = os.path.join("data", "status", safe_sym + ".json")
            tp_price = sl_price = entry_price = None
            if os.path.exists(status_path):
                with open(status_path) as f:
                    st = json.load(f)
                pos = st.get("position")
                if pos:
                    tp_price    = pos.get("tp_price")
                    sl_price    = pos.get("sl_price")
                    entry_price = pos.get("entry_price")

            return jsonify({
                "candles":     candles,
                "tp_price":    tp_price,
                "sl_price":    sl_price,
                "entry_price": entry_price,
            })
        except Exception as e:
            logger.error(f"[OHLCV] {e}")
            return jsonify({"error": str(e), "candles": []})

    @app.route("/api/balance_chart")
    def api_balance_chart():
        days = int(request.args.get("days", 7))
        try:
            import ccxt
            user = _get_first_user()
            if not user:
                return jsonify({"error": "no users", "dates": [], "values": []})

            exchange = ccxt.binance({
                "apiKey":  user.get("api_key", ""),
                "secret":  user.get("api_secret", ""),
                "options": {"defaultType": "future"},
            })
            if user.get("is_testnet", True):
                exchange.set_sandbox_mode(True)

            start_ms = int((time.time() - days * 86400) * 1000)
            income = exchange.fapiPrivateGetIncome({
                "incomeType": "REALIZED_PNL", "startTime": start_ms, "limit": 1000,
            })

            daily: Dict[str, float] = {}
            for item in income:
                day = time.strftime("%d.%m", time.gmtime(item["time"] / 1000))
                daily[day] = daily.get(day, 0.0) + float(item["income"])

            if not daily:
                return jsonify({"dates": [], "values": [], "currency": "USDT"})

            now = time.gmtime()
            def day_key(d):
                try: return time.mktime(time.strptime(d+"."+str(now.tm_year), "%d.%m.%Y"))
                except: return 0

            dates, values, cs = [], [], 0.0
            for day in sorted(daily.keys(), key=day_key):
                cs += daily[day]; dates.append(day); values.append(round(cs, 4))

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
