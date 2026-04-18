#!/usr/bin/env python3
"""
get_chat_ids.py — Показывает chat_id всех пользователей, написавших боту.

Запуск:
    python get_chat_ids.py

Требует: TG_BOT_TOKEN в .env (или переменной окружения)

Как использовать:
    1. Попроси нового пользователя написать /start твоему боту
    2. Запусти этот скрипт
    3. Скопируй нужный chat_id
"""

import json
import os
import ssl
from urllib.request import urlopen, Request

# ── Загрузка токена ────────────────────────────────────────────────────────────
def load_token() -> str:
    # Сначала из переменной окружения
    token = os.environ.get("TG_BOT_TOKEN", "")

    # Потом из .env файла
    if not token:
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("TG_BOT_TOKEN="):
                        token = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break

    return token


# ── SSL без верификации (как в основном боте) ──────────────────────────────────
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def get_updates(token: str) -> list:
    url = f"https://api.telegram.org/bot{token}/getUpdates?limit=100"
    req = Request(url)
    try:
        with urlopen(req, context=_ssl_ctx, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("result", [])
    except Exception as e:
        print(f"❌ Ошибка запроса к Telegram API: {e}")
        return []


def main():
    print("=" * 50)
    print("  Telegram Chat ID Finder")
    print("=" * 50)

    token = load_token()
    if not token:
        print("\n❌ Токен не найден!")
        print("   Добавь TG_BOT_TOKEN в .env файл или переменную окружения.")
        return

    print(f"\n✅ Токен найден: ...{token[-6:]}")
    print("\n⏳ Получаю обновления от Telegram...\n")

    updates = get_updates(token)

    if not updates:
        print("📭 Обновлений нет.")
        print("   → Попроси пользователя написать /start боту и запусти скрипт снова.")
        return

    # Собираем уникальных пользователей
    seen = {}
    for update in updates:
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat", {})
        user = message.get("from", {})

        chat_id = chat.get("id")
        if not chat_id or chat_id in seen:
            continue

        seen[chat_id] = {
            "chat_id": chat_id,
            "first_name": user.get("first_name", ""),
            "last_name": user.get("last_name", ""),
            "username": user.get("username", ""),
            "chat_type": chat.get("type", ""),
            "text": message.get("text", ""),
        }

    if not seen:
        print("📭 Нет сообщений с chat_id.")
        print("   → Попроси пользователя написать /start боту и запусти скрипт снова.")
        return

    print(f"👥 Найдено пользователей: {len(seen)}\n")
    print("-" * 50)

    for info in seen.values():
        name_parts = [info["first_name"], info["last_name"]]
        name = " ".join(p for p in name_parts if p) or "(без имени)"
        username = f"@{info['username']}" if info["username"] else "(нет username)"

        print(f"  Имя:       {name}")
        print(f"  Username:  {username}")
        print(f"  Chat ID:   {info['chat_id']}   ← копируй это")
        print(f"  Тип чата:  {info['chat_type']}")
        print(f"  Посл. сообщение: {info['text'][:60]!r}")
        print("-" * 50)

    print("\n💡 Скопируй нужный Chat ID и вставь в .env как TG_CHAT_ID=<значение>")
    print("   или укажи при добавлении пользователя через setup_users.py\n")


if __name__ == "__main__":
    main()
