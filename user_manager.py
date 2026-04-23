# ============================================================
#  Smart Adaptive Trading System — user_manager.py
#  Мультипользовательская система
# ============================================================

import json
import logging
import os
from typing import Dict, List, Optional

from config import UserProfile, SystemConfig

logger = logging.getLogger(__name__)

USERS_FILE = os.path.join("data", "users.json")


class UserManager:
    """
    Управляет пользователями системы.

    Возможности:
    - Добавление/удаление пользователей
    - Хранение API-ключей (в зашифрованном виде в production)
    - Индивидуальные настройки (плечо, %, стратегия)
    - Монетизация: комиссия с прибыли
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.users: Dict[str, UserProfile] = {}
        self._load_users()

    # ──────────────────────────────────────────
    #  CRUD операции
    # ──────────────────────────────────────────

    def add_user(
        self,
        user_id: str,
        exchange: str,
        api_key: str,
        api_secret: str,
        symbol: str = "BTC/USDT",
        leverage: int = 3,
        deposit_pct: float = 0.10,
        commission_pct: float = 0.20,
        is_testnet: bool = False,
        custom_config: Optional[Dict] = None,
        telegram_chat_id: str = "",
        symbols: Optional[List[str]] = None,
        top_n_symbols: int = 0,
    ) -> UserProfile:
        """Регистрирует нового пользователя.

        symbols — фиксированный список пар (приоритет над symbol).
        top_n_symbols — автоматический выбор топ-N пар по объёму (если >0).
        """
        if user_id in self.users:
            raise ValueError(f"User '{user_id}' already exists")

        profile = UserProfile(
            user_id=user_id,
            exchange=exchange.lower(),
            api_key=api_key,
            api_secret=api_secret,
            symbol=symbol,
            symbols=list(symbols) if symbols else [],
            top_n_symbols=top_n_symbols,
            leverage=leverage,
            deposit_pct=deposit_pct,
            commission_pct=commission_pct,
            is_testnet=is_testnet,
            custom_config=custom_config,
            telegram_chat_id=telegram_chat_id,
        )
        self.users[user_id] = profile
        self._save_users()
        active = profile.get_active_symbols()
        logger.info(
            f"[USERS] Added user '{user_id}' on {exchange.upper()} | "
            f"symbols={active} top_n={top_n_symbols}"
        )
        return profile

    def remove_user(self, user_id: str) -> bool:
        if user_id not in self.users:
            return False
        del self.users[user_id]
        self._save_users()
        logger.info(f"[USERS] Removed user '{user_id}'")
        return True

    def get_user(self, user_id: str) -> Optional[UserProfile]:
        return self.users.get(user_id)

    def list_users(self) -> List[str]:
        return list(self.users.keys())

    def update_user_settings(
        self,
        user_id: str,
        leverage: Optional[int] = None,
        deposit_pct: Optional[float] = None,
        commission_pct: Optional[float] = None,
        symbol: Optional[str] = None,
        custom_config: Optional[Dict] = None,
        symbols: Optional[List[str]] = None,
        top_n_symbols: Optional[int] = None,
    ) -> bool:
        """Обновляет настройки пользователя.

        symbols и top_n_symbols позволяют переключаться между режимами
        "ручной список пар" и "автоматический топ-N по объёму".
        """
        user = self.users.get(user_id)
        if not user:
            return False

        if leverage is not None:
            if not (1 <= leverage <= 20):
                raise ValueError(f"Leverage must be 1–20, got {leverage}")
            user.leverage = leverage

        if deposit_pct is not None:
            if not (0.01 <= deposit_pct <= 0.50):
                raise ValueError(f"deposit_pct must be 1%–50%, got {deposit_pct}")
            user.deposit_pct = deposit_pct

        if commission_pct is not None:
            user.commission_pct = commission_pct

        if symbol is not None:
            user.symbol = symbol

        if symbols is not None:
            user.symbols = list(symbols)

        if top_n_symbols is not None:
            if top_n_symbols < 0:
                raise ValueError(f"top_n_symbols must be >= 0, got {top_n_symbols}")
            user.top_n_symbols = top_n_symbols

        if custom_config is not None:
            user.custom_config = {**(user.custom_config or {}), **custom_config}

        self._save_users()
        logger.info(f"[USERS] Updated settings for '{user_id}'")
        return True

    # ──────────────────────────────────────────
    #  Персистентность (JSON-файл)
    # ──────────────────────────────────────────

    def _save_users(self):
        """Сохраняет пользователей в JSON (в production — зашифровать!)"""
        path = os.path.join(self.data_dir, "users.json")
        data = {}
        for uid, p in self.users.items():
            data[uid] = {
                "exchange": p.exchange,
                "api_key": p.api_key,       # В production: зашифровать
                "api_secret": p.api_secret,  # В production: зашифровать
                "symbol": p.symbol,
                "symbols": p.symbols,
                "top_n_symbols": p.top_n_symbols,
                "leverage": p.leverage,
                "deposit_pct": p.deposit_pct,
                "commission_pct": p.commission_pct,
                "is_testnet": p.is_testnet,
                "custom_config": p.custom_config,
                "telegram_chat_id": p.telegram_chat_id,
            }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def _load_users(self):
        """Загружает пользователей из JSON"""
        path = os.path.join(self.data_dir, "users.json")
        if not os.path.exists(path):
            return
        try:
            with open(path) as f:
                data = json.load(f)
            for uid, d in data.items():
                self.users[uid] = UserProfile(
                    user_id=uid,
                    exchange=d["exchange"],
                    api_key=d["api_key"],
                    api_secret=d["api_secret"],
                    symbol=d.get("symbol", "BTC/USDT"),
                    symbols=d.get("symbols", []),
                    top_n_symbols=d.get("top_n_symbols", 5),
                    leverage=d.get("leverage", 3),
                    deposit_pct=d.get("deposit_pct", 0.10),
                    commission_pct=d.get("commission_pct", 0.20),
                    is_testnet=d.get("is_testnet", False),
                    custom_config=d.get("custom_config"),
                    telegram_chat_id=d.get("telegram_chat_id", ""),
                )
            logger.info(f"[USERS] Loaded {len(self.users)} users")
        except Exception as e:
            logger.error(f"[USERS] Failed to load users: {e}")

    def print_summary(self):
        """Печатает сводку по всем пользователям"""
        print(f"\n{'='*70}")
        print(f"  USERS ({len(self.users)} total)")
        print(f"{'='*70}")
        for uid, p in self.users.items():
            if p.top_n_symbols > 0:
                pairs_desc = f"TOP-{p.top_n_symbols} (авто)"
            elif p.symbols:
                pairs_desc = ", ".join(p.symbols)
            else:
                pairs_desc = p.symbol
            print(
                f"  {uid:15s} | {p.exchange:8s} | {pairs_desc:30s} | "
                f"x{p.leverage} | {p.deposit_pct*100:.0f}% | "
                f"{'TESTNET' if p.is_testnet else 'LIVE'}"
            )
        print(f"{'='*70}\n")
