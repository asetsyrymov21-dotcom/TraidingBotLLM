# ============================================================
#  dynamic_settings.py — горячая перезагрузка настроек из JSON
#  Бот читает этот файл каждый тик — изменения применяются
#  без перезапуска сервиса.
# ============================================================

import json
import os
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SETTINGS_FILE = os.path.join("data", "dynamic_settings.json")

# Значения по умолчанию — совпадают с config.py
DEFAULT_SETTINGS: Dict[str, Any] = {
    "tp_pct":       0.002,   # TP 0.2%
    "sl_pct":       0.016,   # SL 1.6%
    "position_pct": 0.05,    # 5% депозита на пару
    "leverage":     3,       # Плечо (применяется ко всем парам)
    "pair_overrides": {},    # {"BTC/USDT": {"tp_pct": 0.003, "sl_pct": 0.024}}
    "reversal_pause_sec": 0, # Пауза после разворота тренда (SL → вход в другую сторону), секунды
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


def apply_to_config(cfg, symbol: Optional[str] = None) -> None:
    """
    Применяет динамические настройки к объекту конфига (EntryBotConfig или TrendBotConfig).
    Если symbol задан — проверяет per-pair переопределения.
    Вызывается в начале каждого тика BotEngine.
    """
    if not _cache:
        load()
    s = _cache

    # Базовые TP/SL
    tp_pct = float(s.get("tp_pct", DEFAULT_SETTINGS["tp_pct"]))
    sl_pct = float(s.get("sl_pct", DEFAULT_SETTINGS["sl_pct"]))

    # Per-pair override
    if symbol:
        overrides = s.get("pair_overrides", {})
        if symbol in overrides:
            tp_pct = float(overrides[symbol].get("tp_pct", tp_pct))
            sl_pct = float(overrides[symbol].get("sl_pct", sl_pct))

    # Применяем TP — все режимы одинаковые
    for attr in ("tp_pct", "tp_quiet", "tp_normal", "tp_volatile"):
        if hasattr(cfg, attr):
            setattr(cfg, attr, tp_pct)

    # Применяем SL
    if hasattr(cfg, "sl_pct"):
        cfg.sl_pct = sl_pct

    # sl_multiplier из соотношения sl/tp (чтобы _calc_adaptive_tp_sl использовал правильный SL)
    if hasattr(cfg, "sl_multiplier") and tp_pct > 0:
        cfg.sl_multiplier = round(sl_pct / tp_pct, 4)

    # Размер позиции
    if "position_pct" in s and hasattr(cfg, "position_pct"):
        cfg.position_pct = float(s["position_pct"])
