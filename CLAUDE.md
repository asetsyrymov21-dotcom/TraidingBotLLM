# CLAUDE.md — инструкции для Claude

## Навигация по проекту

**Не сканируй папку целиком.** Вместо этого:

1. Прочитай `PROJECT_MAP.md` — там описан каждый файл и за что он отвечает.
2. По описанию точечно открывай нужный файл через `Read`.

Пример:
- Нужно изменить TP/SL → `PROJECT_MAP.md` говорит: это в `config.py` → читаешь только `config.py`.
- Нужно изменить логику входа в тренде → это `strategies/trend_strategy.py`.
- Нужно добавить биржу → это `exchange.py`.

## Карта файлов (краткая)

| Файл | За что отвечает |
|---|---|
| `config.py` | Все параметры: TP, SL, ATR, ADX, плечо, % депозита |
| `exchange.py` | Подключение к Binance / Bybit, размещение ордеров |
| `market_analyzer.py` | Индикаторы (EMA, ADX, ATR, RSI, MACD, BB), определение TREND/FLAT |
| `risk_manager.py` | Дневной лимит убытков, просадка, комиссия системы |
| `user_manager.py` | Пользователи, API-ключи, data/users.json |
| `bot_engine.py` | Оркестратор: переключение стратегий, главный тик |
| `main.py` | Точка входа, MultiUserRunner, демо-режим |
| `setup_users.py` | Скрипт добавления пользователей |
| `strategies/grid_strategy.py` | GRID для флэта |
| `strategies/trend_strategy.py` | Трендовый бот (WIN/LOSS логика, анти-сквиз) |
| `telegram_notifier.py` | Telegram-уведомления о действиях бота |
| `strategies/entry_strategy.py` | Умный вход (RSI + MACD + Bollinger, правило 3/3) |

Полные описания — в `PROJECT_MAP.md`.
