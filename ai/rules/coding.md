# Coding Rules — Trading Bot

## Навигация (обязательно)
1. Сначала читай PROJECT_MAP.md
2. По описанию открывай только нужный файл через Read
3. Не сканируй всю папку целиком

## Карта: что где менять
- TP / SL / плечо / % депозита → config.py
- Логика входа (RSI, MACD, BB) → strategies/entry_strategy.py
- Win/Loss система, анти-сквиз → strategies/trend_strategy.py
- Подключение к бирже, ордера → exchange.py
- Индикаторы (EMA, ADX, ATR, RSI, MACD, BB) → market_analyzer.py
- Риск-лимиты, дневной убыток → risk_manager.py
- Пользователи, API-ключи → user_manager.py
- Переключение стратегий, тик → bot_engine.py
- Telegram-уведомления → telegram_notifier.py
- Интервал тика, точка входа → main.py

## Change policy
- Diagnose first — сначала понять причину, потом трогать код
- Keep fix minimal — минимальные изменения
- Max 3 files per change
- Follow existing project style (нет type hints везде — не добавлять)
- После правки проверить: python -m py_compile <файл>

## Forbidden
- Большой рефакторинг без явного запроса
- Добавление новых зависимостей без причины (проект намеренно без лишних libs)
- Использовать MarketState / state в MarketSnapshot (удалено, не использовать)
- Grid-стратегию активировать (файл есть, но не вызывается — не трогать)
- Изменять null-байты — после Edit всегда проверять: python -m py_compile
