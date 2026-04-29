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

## Правило: менять все зависимости сразу

Когда добавляешь или меняешь любой параметр/фичу — **сразу** проверяй и обновляй ВСЕ места где он используется. Не по одному за раз.

**Чеклист для нового параметра в настройках:**
1. `dynamic_settings.py` — добавить в `DEFAULT_SETTINGS`
2. `web_app.py` (HTML) — слайдер/инпут
3. `web_app.py` (JS `applySettingsToUI`) — загрузка значения в UI
4. `web_app.py` (POST `/api/settings`) — сохранение (глобальные параметры — вне `if not pairs`, per-pair — внутри `else`)
5. `telegram_notifier.py` (`LABELS` в `notify_settings_changed`) — уведомление об изменении
6. Стратегия где параметр используется (`trend_strategy.py`, `entry_strategy.py`, etc.)

**Чеклист для новой логики в стратегии:**
1. Добавить поле в dataclass состояния (`TrendBotState`, etc.)
2. Обновить логику в `tick()` / `_close_position()` / etc.
3. Если параметр приходит из dynamic_settings — убедиться что `apply_to_config` его передаёт (проверить имя атрибута — `position_pct` vs `base_position_pct`)
4. Если нужно уведомление — добавить в `telegram_notifier.py`

**Правило:** перед тем как писать код — пробежаться grep'ом по всем файлам где встречается похожий параметр, и сразу внести все изменения в одном PR.

## Деплой

**Команда:** `.\deploy.ps1` из `C:\Users\midori\Desktop\Trading_Bot`  
**Опционально:** `.\deploy.ps1 "описание правки"` — задаёт сообщение коммита вручную.

**Что делает скрипт (4 шага):**
1. `git add -A` + `git commit` + `git push origin master` → GitHub
2. SSH на VPS → `git pull origin master` (путь: `/opt/trading-bot/TraidingBotLLM`)
3. SSH на VPS → `.venv/bin/pip install -r requirements.txt -q`
4. SSH на VPS → `systemctl restart tradingbot`

**SSH-ключ:** `~/.ssh/id_ed25519`  
**VPS:** `root@178.104.156.114`  
**Сервис:** `tradingbot` (systemd)

**Логи после деплоя:**
```bash
journalctl -u tradingbot -f
```

**Важно — правила редактирования файлов:**
- Файлы >16KB писать через bash `python3` скрипт (не через Edit/Write напрямую) — иначе файл обрезается из-за Windows CRLF / маунта
- После правки всегда проверять `wc -l` и `tail -5` — убедиться что файл не обрезан
- Если файл испорчен — восстанавливать через `git show HEAD:файл > /tmp/fix.py && python3 -c "open(...,'wb').write(open('/tmp/fix.py','rb').read())"`
- Из sandbox SSH до VPS недоступен (`Network is unreachable`) — деплой только через `.\deploy.ps1` на Windows или `git push` из bash + ручной `git pull` на VPS
