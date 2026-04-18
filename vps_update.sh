#!/bin/bash
# ============================================================
#  vps_update.sh — скрипт для VPS
#  Загружает последний код из GitHub и перезапускает бота.
#
#  Положи этот файл на VPS в папку с ботом.
#  Запуск вручную:  bash vps_update.sh
# ============================================================

# ── НАСТРОЙКИ ─────────────────────────────────────────────
SERVICE_NAME="trading-bot"               # имя systemd-сервиса
BOT_DIR="/root/TraidingBotLLM"           # путь к боту на VPS
# ──────────────────────────────────────────────────────────

set -e

echo "🔄 Обновляем код из GitHub..."
cd "$BOT_DIR"
git pull origin main

echo "📦 Проверяем зависимости..."
pip install -r requirements.txt --break-system-packages -q

echo "🔁 Перезапускаем сервис $SERVICE_NAME..."
sudo systemctl restart "$SERVICE_NAME"

echo "📋 Статус сервиса:"
sudo systemctl status "$SERVICE_NAME" --no-pager -l

echo "✅ Обновление завершено!"
