#!/usr/bin/env python3
# ============================================================
#  Smart Adaptive Trading System — main.py
# ============================================================

import logging
import os
import signal
import sys
import threading
from typing import Dict

from config import SystemConfig, UserProfile
from bot_engine import BotEngine
from user_manager import UserManager
from telegram_notifier import TelegramNotifier


def setup_logging(log_file: str = "bot.log", level: str = "INFO"):
    os.makedirs("logs", exist_ok=True)
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(os.path.join("logs", log_file)),
        ],
    )


logger = logging.getLogger(__name__)


class MultiUserRunner:
    def __init__(self, config: SystemConfig, notifier: TelegramNotifier = None):
        self.config = config
        self.notifier = notifier
        self.engines: Dict[str, BotEngine] = {}
        self.threads: Dict[str, threading.Thread] = {}
        self._stop_event = threading.Event()
        self._tick_summary_interval = config.telegram.tick_summary_interval

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def add_user(self, profile: UserProfile):
        engine = BotEngine(profile, self.config, notifier=self.notifier)
        self.engines[profile.user_id] = engine
        logger.info(f"Added user '{profile.user_id}' to runner")

    def run(self, interval_seconds: int = 60):
        logger.info(
            f"Starting {len(self.engines)} user(s). Tick interval: {interval_seconds}s"
        )

        for uid, engine in self.engines.items():
            try:
                engine.start()
            except Exception as e:
                logger.error(f"Failed to start engine for '{uid}': {e}")

        while not self._stop_event.is_set():
            for uid, engine in list(self.engines.items()):
                if not engine.is_running:
                    continue
                try:
                    result = engine.tick()
                    self._log_tick_result(uid, result)
                except Exception as e:
                    logger.error(f"Tick error for '{uid}': {e}", exc_info=True)

            # Ждём следующий тик кусочками по 1 сек — так Ctrl+C реагирует мгновенно
            for _ in range(interval_seconds):
                if self._stop_event.is_set():
                    break
                try:
                    self._stop_event.wait(timeout=1)
                except KeyboardInterrupt:
                    self._stop_event.set()
                    break

        self._shutdown()

    def _shutdown(self):
        logger.info("Shutting down all engines...")
        for uid, engine in self.engines.items():
            try:
                engine.stop()
                logger.info(f"Engine '{uid}' stopped")
            except Exception as e:
                logger.error(f"Error stopping '{uid}': {e}")

    def _signal_handler(self, signum, frame):
        logger.info(f"Signal {signum} received. Stopping gracefully...")
        self._stop_event.set()
        # Повторное нажатие Ctrl+C → принудительный выход
        signal.signal(signal.SIGINT, self._force_exit)

    @staticmethod
    def _force_exit(signum, frame):
        logger.warning("Force exit (double Ctrl+C)")
        os._exit(1)

    def _log_tick_result(self, uid: str, result: Dict):
        if result.get("status") == "ok":
            market = result.get("market_state", "?")
            price = result.get("price", 0)
            mode = result.get("mode", "?")
            risk = result.get("risk", {})
            tick_num = result.get("tick", 0)
            logger.info(
                f"[{uid}] Tick #{tick_num} | "
                f"Market={market} | Mode={mode} | Price={price:.4f} | "
                f"DayPnL={risk.get('daily_pnl_pct', '?')} | "
                f"DD={risk.get('drawdown_pct', '?')}"
            )
            # Telegram: периодический саммари
            if (self.notifier and self._tick_summary_interval > 0
                    and tick_num % self._tick_summary_interval == 0):
                self.notifier.notify_tick_summary(
                    uid, tick_num, price, market, mode,
                    risk.get("daily_pnl_pct", "?"),
                    risk.get("drawdown_pct", "?"),
                )
        elif result.get("status") == "risk_blocked":
            logger.warning(f"[{uid}] TRADING BLOCKED BY RISK MANAGER")
        else:
            logger.debug(f"[{uid}] Tick result: {result.get('status', '?')}")


def _load_env(filepath: str = ".env"):
    """Загружает переменные из .env файла в os.environ"""
    if not os.path.exists(filepath):
        return
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)


def main():
    setup_logging("bot.log", "INFO")
    os.makedirs("data", exist_ok=True)

    # Загружаем .env файл
    _load_env()

    config = SystemConfig()

    # ── Telegram: настройка из переменных окружения или config ──
    tg_token = os.environ.get("TG_BOT_TOKEN", config.telegram.bot_token)
    tg_chat = os.environ.get("TG_CHAT_ID", config.telegram.chat_id)
    tg_enabled = bool(tg_token and tg_chat)

    if tg_enabled:
        config.telegram.enabled = True
        config.telegram.bot_token = tg_token
        config.telegram.chat_id = tg_chat

    notifier = TelegramNotifier(
        bot_token=config.telegram.bot_token,
        chat_id=config.telegram.chat_id,
        enabled=config.telegram.enabled,
    )

    if tg_enabled:
        logger.info("Telegram notifications ENABLED")
    else:
        logger.info(
            "Telegram notifications DISABLED. "
            "Set TG_BOT_TOKEN and TG_CHAT_ID env vars to enable."
        )

    mgr = UserManager(data_dir="data")

    user_ids = mgr.list_users()
    if not user_ids:
        logger.error("No users found in data/users.json")
        return

    runner = MultiUserRunner(config, notifier=notifier)

    for uid in user_ids:
        profile = mgr.get_user(uid)
        if not profile:
            continue

        # Пока для безопасности запускаем только testnet
        if not profile.is_testnet:
            logger.warning(f"Skipping LIVE user '{uid}'")
            continue

        # Личный notifier: используем chat_id пользователя если задан, иначе общий
        user_chat_id = profile.telegram_chat_id or config.telegram.chat_id
        user_notifier = TelegramNotifier(
            bot_token=config.telegram.bot_token,
            chat_id=user_chat_id,
            enabled=bool(config.telegram.bot_token and user_chat_id),
        )

        try:
            engine = BotEngine(profile, config, notifier=user_notifier)
            runner.engines[uid] = engine
            logger.info(f"Added user '{uid}' to runner")
        except Exception as e:
            logger.error(f"Failed to add user '{uid}': {e}")

    if not runner.engines:
        logger.error("No testnet users available to run")
        return

    try:
        runner.run(interval_seconds=60)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt caught. Shutting down...")
        runner._shutdown()


if __name__ == "__main__":
    main()
