# ============================================================
#  dynamic_settings.py — горячая перезагрузка настроек из JSON
#  Бот читает этот файл каждый тик — изменения применяются
#  без перезапуска сервиса.
# ============================================================

import json
import os
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

SETTINGS_FILE = os.path.join("data", "dynamic_settings.json")

# Значения по умолчанию — совпадают с config.py
DEFAULT_SETTINGS: Dict[str, Any] = {
    # Общие
    "leverage":               3,
    "position_pct":           0.05,    # 5% депозита на пару
    "max_hold_minutes":       240,     # 4 часа таймаут
    "rsi_long_threshold":     50.0,
    "rsi_short_threshold":    50.0,
}

_cache: Dict[str, Any] = {}


def load() -> Dict[str, Any]:
    """Загружает настройки из файла. Если файл не существует — создаёт с дефолтами."""
    global _cache
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            _cache = {**DEFAULT_SETTINGS, **data}
            logger.debug(f"[DynSettings] Loaded from {SETTINGS_FILE}")
            return _cache
    except Exception as e:
        logger.error(f"[DynSettings] Failed to load: {e}")

    # Файл не найден или ошибка — используем дефолты и сохраняем
    _cache = dict(DEFAULT_SETTINGS)
    save(_cache)
    return _cache


def save(settings: Dict[str, Any]) -> bool:
    """Сохраняет настройки в JSON файл."""
    global _cache
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        merged = {**DEFAULT_SETTINGS, **settings}
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
        _cache = merged
        logger.info(f"[DynSettings] Saved to {SETTINGS_FILE}")
        return True
    except Exception as e:
        logger.error(f"[DynSettings] Failed to save: {e}")
        return False


def get(key: str, default: Any = None) -> Any:
    """Получает одно значение. Если кэш пустой — загружает файл."""
    if not _cache:
        load()
    return _cache.get(key, DEFAULT_SETTINGS.get(key, default))


def apply_to_config(cfg) -> None:
    """
    Применяет динамические настройки к объекту конфига (EntryBotConfig или TrendBotConfig).
    Вызывается в начале каждого тика BotEngine.
    """
    if not _cache:
        load()
    s = _cache

    # Общие
    if "max_hold_minutes" in s and hasattr(cfg, "max_hold_minutes"):
        cfg.max_hold_minutes = int(s["max_hold_minutes"])
    if "position_pct" in s and hasattr(cfg, "position_pct"):
        cfg.position_pct = float(s["position_pct"])
    if "rsi_long_threshold" in s and hasattr(cfg, "rsi_long_threshold"):
        cfg.rsi_long_threshold = float(s["rsi_long_threshold"])
    if "rsi_short_threshold" in s and hasattr(cfg, "rsi_short_threshold"):
        cfg.rsi_short_threshold = float(s["rsi_short_threshold"])
