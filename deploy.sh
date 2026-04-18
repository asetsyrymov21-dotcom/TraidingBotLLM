#!/bin/bash
# ============================================================
#  deploy.sh — локальный скрипт деплоя
#  Использование:
#    ./deploy.sh                    # коммит с авто-сообщением
#    ./deploy.sh "описание правки"  # коммит с твоим сообщением
# ============================================================

# ── НАСТРОЙКИ ─────────────────────────────────────────────
VPS_USER="root"
VPS_HOST="178.104.156.114"
SSH_KEY="~/.ssh/id_ed25519"
BOT_DIR="/opt/trading-bot/TraidingBotLLM"
# ──────────────────────────────────────────────────────────

set -e

# Удаляем зависший lock-файл если есть
LOCK_FILE=".git/index.lock"
if [ -f "$LOCK_FILE" ]; then
  echo -e "${YELLOW}⚠️  Найден зависший git lock — удаляю...${NC}"
  rm -f "$LOCK_FILE"
fi

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}🚀 Деплой бота...${NC}"

# ── 1. Git commit + push ──
echo -e "\n${YELLOW}[1/4] Git...${NC}"
git add -A
if git diff --staged --quiet; then
  echo "Нет новых изменений."
else
  COMMIT_MSG="${1:-"update $(date '+%Y-%m-%d %H:%M')"}"
  git commit -m "$COMMIT_MSG"
  echo -e "${GREEN}✅ Коммит: $COMMIT_MSG${NC}"
fi
git push origin master
echo -e "${GREEN}✅ Запушено в GitHub${NC}"

# ── 2. SSH: git pull ──
echo -e "\n${YELLOW}[2/4] Обновляем код на VPS...${NC}"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VPS_USER@$VPS_HOST" \
  "cd $BOT_DIR && git pull origin master"
echo -e "${GREEN}✅ Код обновлён${NC}"

# ── 3. SSH: обновить зависимости ──
echo -e "\n${YELLOW}[3/4] Обновляем зависимости...${NC}"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VPS_USER@$VPS_HOST" \
  "cd $BOT_DIR && .venv/bin/pip install -r requirements.txt -q"
echo -e "${GREEN}✅ Зависимости обновлены${NC}"

# ── 4. SSH: перезапустить сервис ──
echo -e "\n${YELLOW}[4/4] Перезапускаем бота...${NC}"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VPS_USER@$VPS_HOST" \
  "systemctl restart tradingbot"
echo -e "${GREEN}✅ Бот перезапущен!${NC}"

echo -e "\n${GREEN}🎉 Деплой завершён!${NC}"
echo -e "Логи: ssh $VPS_USER@$VPS_HOST 'journalctl -u tradingbot -f'"
