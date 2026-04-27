# User Rules — Trading Bot

## Ключевой инвариант
- Каждый пользователь (alice, bob, ...) полностью изолирован
- У каждого: свои API-ключи, свой RiskManager, свой BotEngine на каждую пару

## Где хранятся пользователи
- data/users.json — основной файл (не редактировать вручную)
- user_manager.py — CRUD: add_user, remove_user, get_user, update_user_settings
- setup_users.py — скрипт первичного добавления

## Перед изменением user-логики
1. Понять где user_id / username входит в запрос
2. Убедиться что изменение не затрагивает других пользователей
3. Проверить что RiskManager создаётся отдельно для каждого (не шарится)

## Индивидуальные параметры
- custom_config в UserProfile → переопределяет глобальные TP, SL, deposit_pct
- leverage, symbols, top_n_symbols — на уровне UserProfile

## Forbidden
- Глобальные запросы без фильтра по пользователю
- Шарить один RiskManager между пользователями
- Хранить API-ключи в логах / Telegram-уведомлениях
- Менять data/users.json напрямую (только через user_manager.py)
