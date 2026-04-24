#!/bin/bash
# ============================================================
#  vps_setup_autodeploy.sh
#  Запускается ОДИН РАЗ на VPS чтобы настроить авто-деплой.
#
#  Что делает:
#  1. Создаёт /opt/trading-bot/auto_deploy.sh
#  2. Добавляет cron-задачу: каждую минуту проверяет GitHub
#     и если есть новые коммиты — делает git pull + restart
#
#  Запуск: ssh root@178.104.156.114 'bash -s' < vps_setup_autodeploy.sh
# ============================================================

BOT_DIR="/opt/trading-bot/TraidingBotLLM"
DEPLOY_LOG="/opt/trading-bot/deploy.log"
DEPLOY_SCRIPT="/opt/trading-bot/auto_deploy.sh"

echo "==> Создаём скрипт авто-деплоя..."

cat > "$DEPLOY_SCRIPT" << 'SCRIPT'
#!/bin/bash
BOT_DIR="/opt/trading-bot/TraidingBotLLM"
LOG="/opt/trading-bot/deploy.log"

cd "$BOT_DIR" || exit 1

# Получаем последние коммиты с GitHub (без мерджа)
git fetch origin master --quiet 2>>"$LOG"

LOCAL=$(git rev-parse HEAD 2>/dev/null)
REMOTE=$(git rev-parse origin/master 2>/dev/null)

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Новая версия обнаружена ($REMOTE)" >> "$LOG"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Обновляю код..." >> "$LOG"

    git pull origin master >> "$LOG" 2>&1
    if [ $? -ne 0 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ОШИБКА git pull — пробую сброс..." >> "$LOG"
        git reset --hard origin/master >> "$LOG" 2>&1
    fi

    # Обновляем зависимости только если изменился requirements.txt
    if git diff HEAD@{1} HEAD --name-only | grep -q "requirements.txt"; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Обновляю зависимости..." >> "$LOG"
        .venv/bin/pip install -r requirements.txt -q >> "$LOG" 2>&1
    fi

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Перезапускаю сервис..." >> "$LOG"
    systemctl restart tradingbot >> "$LOG" 2>&1

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ Деплой завершён" >> "$LOG"
fi
SCRIPT

chmod +x "$DEPLOY_SCRIPT"
echo "==> Скрипт создан: $DEPLOY_SCRIPT"

# Добавляем в cron (каждую минуту)
CRON_LINE="* * * * * $DEPLOY_SCRIPT"
( crontab -l 2>/dev/null | grep -v "auto_deploy"; echo "$CRON_LINE" ) | crontab -
echo "==> Cron-задача добавлена (каждую минуту)"

# Показываем текущий crontab
echo ""
echo "==> Текущий crontab:"
crontab -l

# Создаём лог если нет
touch "$DEPLOY_LOG"
chmod 644 "$DEPLOY_LOG"

echo ""
echo "✅ Готово! VPS будет сам проверять GitHub каждую минуту."
echo "   Логи авто-деплоя: tail -f $DEPLOY_LOG"
