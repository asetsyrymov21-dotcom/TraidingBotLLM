#!/usr/bin/env python3
"""
Быстрый тест всех типов Telegram-уведомлений.
Запускать: python test_telegram.py
"""

import os
import sys
import time

# Загружаем .env
def _load_env(filepath: str = ".env"):
    if not os.path.exists(filepath):
        return
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)

_load_env()

from telegram_notifier import TelegramNotifier

TOKEN = os.environ.get("TG_BOT_TOKEN", "")
CHAT  = os.environ.get("TG_CHAT_ID", "")

if not TOKEN or not CHAT:
    print("❌ TG_BOT_TOKEN или TG_CHAT_ID не найдены! Проверь .env файл.")
    sys.exit(1)

notifier = TelegramNotifier(bot_token=TOKEN, chat_id=CHAT, enabled=True)
USER = "alice"

print(f"🤖 Отправляю тестовые уведомления в Telegram...")
print(f"   Token: {TOKEN[:20]}...")
print(f"   Chat ID: {CHAT}")
print()

# 1. Старт бота
print("1. notify_bot_started...")
notifier.notify_bot_started(USER, "BTC/USDT", "Binance Testnet", 1250.00)
time.sleep(1)

# 2. Смена режима → ТРЕНД
print("2. notify_mode_switch (→ TREND_UP)...")
notifier.notify_mode_switch(USER, None, "trend", "TREND_UP", 67450.50, adx=32.5)
time.sleep(1)

# 3. Открытие трендовой позиции
print("3. notify_trend_open (LONG)...")
notifier.notify_trend_open(
    user_id=USER,
    side="long",
    price=67450.50,
    amount=0.0015,
    tp=68666.21,
    sl=67708.30,
    rsi=56.3,
    ema_fast=67100.0,
    ema_slow=66500.0,
    last_result="WIN",
    size_mult=1.2,
)
time.sleep(1)

# 4. Закрытие трендовой позиции (профит)
print("4. notify_trend_close (TP hit)...")
notifier.notify_trend_close(
    user_id=USER,
    side="long",
    entry_price=67450.50,
    close_price=68666.21,
    pnl=+1.82,
    reason="tp",
    win_streak=2,
    loss_streak=0,
)
time.sleep(1)

# 5. Умный вход
print("5. notify_entry_open...")
notifier.notify_entry_open(
    user_id=USER,
    side="long",
    price=67800.0,
    amount=0.001,
    tp=69156.0,
    sl=67122.0,
    signal_reason="RSI=54 ✅ | MACD пересечение ✅ | BB нижняя зона ✅",
    confidence=3,
)
time.sleep(1)

# 6. Смена режима → FLAT / GRID
print("6. notify_mode_switch (→ FLAT/GRID)...")
notifier.notify_mode_switch(USER, "trend", "grid", "FLAT", 67600.0, adx=18.2)
time.sleep(1)

# 7. GRID активирована
print("7. notify_grid_setup...")
notifier.notify_grid_setup(
    user_id=USER,
    price=67600.0,
    range_low=67200.0,
    range_high=68000.0,
    levels=5,
    allocated=62.5,
)
time.sleep(1)

# 8. GRID ордер исполнен
print("8. notify_grid_fill (BUY)...")
notifier.notify_grid_fill(USER, "buy", 67200.0, 67360.0)
time.sleep(1)

# 9. Риск-блок
print("9. notify_risk_blocked...")
notifier.notify_risk_blocked(USER, "Дневной лимит убытков достигнут (-5%)", "-5.12%", "-3.8%")
time.sleep(1)

# 10. Тик саммари
print("10. notify_tick_summary...")
notifier.notify_tick_summary(USER, 10, 67450.0, "TREND_UP", "trend", "+1.23%", "-0.5%")
time.sleep(1)

# 11. Остановка бота
print("11. notify_bot_stopped...")
notifier.notify_bot_stopped(USER, {
    "risk": {"daily_pnl_pct": "+1.23%", "drawdown_pct": "-0.5%"},
    "trend_bot": {"total_pnl": 1.82, "trade_count": 3, "win_rate": 66.7},
    "entry_bot": {"total_pnl": 0.95, "trade_count": 2, "win_rate": 50.0},
    "grid_bot": {"realized_pnl": 0.34},
})

# Даём время фоновым потокам отправить
time.sleep(3)

print()
print("✅ Все уведомления отправлены! Проверь Telegram.")
