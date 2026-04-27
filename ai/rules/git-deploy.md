# Git Deploy Rules — Trading Bot

## Инфраструктура деплоя
- VPS: root@178.104.156.114
- Сервис: tradingbot (systemd)
- Репо на VPS: /opt/trading-bot/TraidingBotLLM
- Авто-деплой: cron каждую минуту → /opt/trading-bot/auto_deploy.sh
- SSH ключ: $env:USERPROFILE\.ssh\id_ed25519

## Деплой вручную (PowerShell)
```powershell
.\deploy.ps1
```

## Деплой через git (авто)
```powershell
# commit + push → авто-деплой подтянет через ~1 минуту
git add -A
git commit -m "fix: описание"
git push
```

## Перед деплоем — чеклист
1. Проверить текущую ветку: `git branch`
2. Проверить незакоммиченные изменения: `git status`
3. Проверить что файлы компилируются: `python -m py_compile <изменённый файл>`
4. Убедиться что правка не ломает других пользователей (alice, bob изолированы)

## После деплоя — проверить
```powershell
$cmd = "journalctl -u tradingbot -n 20 --no-pager"
ssh -i "$env:USERPROFILE\.ssh\id_ed25519" root@178.104.156.114 $cmd
```

## Forbidden
- Direct push to main с нерабочим кодом
- Деплой без проверки py_compile (null-байты ломают бота)
- Деплой без понимания что изменилось
- Менять .env на VPS напрямую без бэкапа
