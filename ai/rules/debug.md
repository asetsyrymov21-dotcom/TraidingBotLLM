# Debug Rules — Trading Bot

## При любой ошибке — сначала инфраструктура, потом код

### Шаг 1: Проверить логи бота (VPS)
```bash
journalctl -u tradingbot -n 50 --no-pager
journalctl -u tradingbot --no-pager | grep -E 'ERROR|Traceback|Exception' | tail -30
```

### Шаг 2: Проверить статус сервиса
```bash
systemctl status tradingbot
```

### Шаг 3: Проверить авто-деплой
```bash
cat /opt/trading-bot/auto_deploy.sh
# cron обновляет репо каждую минуту
# если новый код не подтянулся — проверить git на VPS
git -C /opt/trading-bot/TraidingBotLLM log --oneline -5
```

### Шаг 4: Проверить доступность биржи
- Testnet: demo-fapi.binance.com
- Ошибки типа "server unavailable", timeout, 5xx → проблема на стороне биржи, не в коде

### Шаг 5: Только после этого → анализировать код

## SSH команды (PowerShell)
```powershell
# Использовать переменную $cmd чтобы избежать проблем с кавычками
$cmd = "journalctl -u tradingbot -n 50 --no-pager"
ssh -i "$env:USERPROFILE\.ssh\id_ed25519" root@178.104.156.114 $cmd
```

## Частые проблемы

| Симптом | Причина | Где смотреть |
|---|---|---|
| Bot не торгует | Risk limit reached | risk_manager.py / логи |
| Нет уведомлений в TG | TG_BOT_TOKEN / TG_CHAT_ID | .env / telegram_notifier.py |
| Неверный размер позиции | deposit_pct / leverage | config.py / user_manager.py |
| Exchange error | API ключи / testnet флаг | exchange.py / .env |
| Null-байты в файле | Edit-tool артефакт | python -m py_compile <файл> |

## Forbidden
- Угадывать фикс без root cause
- Менять логику стратегий чтобы "попробовать"
- Пушить в main до понимания причины
