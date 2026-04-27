#!/usr/bin/env python3
# ============================================================
#  Smart Adaptive Trading System — main.py
# ============================================================

import logging
import os
import signal
import sys
import threading
import time
from typing import Dict, List, Optional

from config import SystemConfig, UserProfile
from bot_engine import BotEngine
from user_manager import UserManager
from symbol_scanner import SymbolScanner
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


# ──────────────────────────────────────────
#  Контейнер: пользователь + все его движки
# ──────────────────────────────────────────

class UserContext:
    """
    Хранит все BotEngine одного пользователя и связанный SymbolScanner.
    Один пользователь → N пар → N движков.
    """

    def __init__(
        self,
        profile: UserProfile,
        config: SystemConfig,
        notifier: Optional[TelegramNotifier] = None,
    ):
        self.profile = profile
        self.config = config
        self.notifier = notifier

        # Движки: ключ = symbol
        self.engines: Dict[str, BotEngine] = {}

        # Сканер пар (только если top_n_symbols > 0)
        self.scanner: Optional[SymbolScanner] = None
        if profile.top_n_symbols > 0:
            self.scanner = SymbolScanner(
                exchange_name=profile.exchange,
                api_key=profile.api_key,
                api_secret=profile.api_secret,
                is_testnet=profile.is_testnet,
                top_n=profile.top_n_symbols,
            )

    @property
    def user_id(self) -> str:
        return self.profile.user_id

    def get_target_symbols(self) -> List[str]:
        """
        Возвращает актуальный список пар для торговли.
        Если top_n_symbols > 0 — берём из SymbolScanner.
        Иначе — из profile.get_active_symbols() (ручной список или одна пара).
        """
        if self.scanner:
            symbols = self.scanner.get_top_symbols()
            if symbols:
                return symbols
            logger.warning(
                f"[{self.user_id}] Scanner вернул пустой список — используем symbols из профиля"
            )
        return self.profile.get_active_symbols()

    def sync_engines(self):
        """
        Синхронизирует движки с актуальным списком пар.
        - Добавляет движки для новых пар
        - Останавливает и удаляет движки устаревших пар
        """
        target = set(self.get_target_symbols())
        current = set(self.engines.keys())

        # Пары, которые нужно добавить
        to_add = target - current
        # Пары, которые нужно удалить
        to_remove = current - target

        for sym in to_remove:
            logger.info(f"[{self.user_id}] Удаляем движок для {sym}")
            engine = self.engines.pop(sym)
            try:
                engine.stop()
            except Exception as e:
                logger.error(f"[{self.user_id}] Ошибка при остановке {sym}: {e}")

        n_total = len(target)
        per_pair_pct = self.profile.per_pair_deposit_pct(n_total)

        for sym in to_add:
            logger.info(
                f"[{self.user_id}] Запускаем движок для {sym} "
                f"(deposit_pct={per_pair_pct:.3f})"
            )
            try:
                engine = BotEngine(
                    profile=self.profile,
                    config=self.config,
                    notifier=self.notifier,
                    symbol=sym,
                    deposit_pct_override=per_pair_pct,
                    notify_start=False,  # объединённое уведомление шлётся из main.py
                )
                engine.start()
                self.engines[sym] = engine
            except Exception as e:
                logger.error(
                    f"[{self.user_id}] Не удалось запустить движок для {sym}: {e}"
                )

    def stop_all(self):
        """Останавливает все движки."""
        for sym, engine in list(self.engines.items()):
            try:
                engine.stop()
                logger.info(f"[{self.user_id}] Движок {sym} остановлен")
            except Exception as e:
                logger.error(f"[{self.user_id}] Ошибка при остановке {sym}: {e}")
        self.engines.clear()

    def tick_all(self) -> Dict[str, Dict]:
        """
        Запускает тик на всех активных движках.
        Все Telegram-уведомления за тик объединяются в одно сообщение.
        """
        # Начинаем пакетный режим — все сообщения накапливаются в буфере
        if self.notifier:
            self.notifier.start_batch()

        results = {}
        for sym, engine in list(self.engines.items()):
            if not engine.is_running:
                continue
            try:
                results[sym] = engine.tick()
            except Exception as e:
                logger.error(f"[{self.user_id}:{sym}] Ошибка тика: {e}", exc_info=True)
                results[sym] = {"status": "error", "message": str(e)}

        # Отправляем все накопленные уведомления одним TG-сообщением
        if self.notifier:
            self.notifier.flush_batch()

        return results


# ──────────────────────────────────────────
#  MultiUserRunner
# ──────────────────────────────────────────

class MultiUserRunner:
    """
    Запускает нескольких пользователей.
    Для каждого пользователя — N BotEngine (по одному на торговую пару).
    Список пар обновляется раз в 24 часа через SymbolScanner.
    """

    def __init__(self, config: SystemConfig, notifier: Optional[TelegramNotifier] = None):
        self.config = config
        self.notifier = notifier
        self.contexts: Dict[str, UserContext] = {}
        self._stop_event = threading.Event()
        self._tick_summary_interval = config.telegram.tick_summary_interval
        self._global_tick: int = 0

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def add_user(self, profile: UserProfile, user_notifier: Optional[TelegramNotifier] = None):
        """Регистрирует пользователя в раннере."""
        ctx = UserContext(
            profile=profile,
            config=self.config,
            notifier=user_notifier or self.notifier,
        )
        self.contexts[profile.user_id] = ctx
        logger.info(
            f"Добавлен пользователь '{profile.user_id}' "
            f"(top_n={profile.top_n_symbols}, "
            f"deposit_pct={profile.deposit_pct:.0%})"
        )

    def run(self, interval_seconds: int = 60):
        if not self.contexts:
            logger.error("Нет пользователей для запуска")
            return

        logger.info(
            f"Запуск {len(self.contexts)} пользователя(ей). "
            f"Интервал тика: {interval_seconds}s"
        )

        # Первичный запуск: инициализируем пары и движки для каждого юзера
        for uid, ctx in self.contexts.items():
            try:
                ctx.sync_engines()
                logger.info(
                    f"[{uid}] Запущено {len(ctx.engines)} движков: "
                    f"{list(ctx.engines.keys())}"
                )
            except Exception as e:
                logger.error(f"[{uid}] Ошибка при инициализации: {e}", exc_info=True)

        # Печатаем крупный баннер со списком всех активных пар по каждому юзеру
        self._print_pairs_banner()

        # Telegram: одно объединённое сообщение о старте на каждого пользователя
        self._notify_started_all()

        # Главный цикл
        while not self._stop_event.is_set():
            self._global_tick += 1

            for uid, ctx in list(self.contexts.items()):
                # Проверяем, нужно ли обновить список пар (каждые 24ч)
                if ctx.scanner and ctx.scanner.should_refresh():
                    logger.info(f"[{uid}] Обновляем список пар (прошло 24ч)...")
                    try:
                        ctx.scanner.force_refresh()
                        ctx.sync_engines()
                        logger.info(
                            f"[{uid}] Новые пары: {list(ctx.engines.keys())}"
                        )
                    except Exception as e:
                        logger.error(f"[{uid}] Ошибка обновления пар: {e}")

                # Тик по всем движкам пользователя
                tick_results = ctx.tick_all()
                for sym, result in tick_results.items():
                    self._log_tick_result(uid, sym, result)

                # Telegram: периодический саммари
                if (
                    self.notifier
                    and self._tick_summary_interval > 0
                    and self._global_tick % self._tick_summary_interval == 0
                ):
                    self._send_summary(uid, ctx)

            # Ждём следующий тик (по 1 сек — мгновенный Ctrl+C)
            for _ in range(interval_seconds):
                if self._stop_event.is_set():
                    break
                self._stop_event.wait(timeout=1)

        self._shutdown()

    def _shutdown(self):
        logger.info("Остановка всех движков...")
        for uid, ctx in self.contexts.items():
            try:
                ctx.stop_all()
                logger.info(f"[{uid}] Все движки остановлены")
            except Exception as e:
                logger.error(f"[{uid}] Ошибка при остановке: {e}")

    def _signal_handler(self, signum, frame):
        logger.info(f"Получен сигнал {signum}. Graceful shutdown...")
        self._stop_event.set()
        signal.signal(signal.SIGINT, self._force_exit)

    @staticmethod
    def _force_exit(signum, frame):
        logger.warning("Принудительный выход (двойной Ctrl+C)")
        os._exit(1)

    def _print_pairs_banner(self):
        """Печатает заметный баннер со списком активных пар по каждому юзеру.

        Нужен чтобы пользователь сразу видел, на каких парах реально стартовал
        бот — без этого в мультипарном режиме можно было подумать, что работает
        только BTC/USDT (поскольку он логируется первым в каждом тике).
        """
        line = "=" * 64
        logger.info(line)
        logger.info("АКТИВНЫЕ ТОРГОВЫЕ ПАРЫ")
        logger.info(line)
        for uid, ctx in self.contexts.items():
            symbols = list(ctx.engines.keys())
            if not symbols:
                logger.warning(f"  [{uid}] НЕТ АКТИВНЫХ ПАР — торговли не будет!")
                continue
            n = len(symbols)
            per_pair = ctx.profile.per_pair_deposit_pct(n)
            logger.info(
                f"  [{uid}] {n} пар(ы): {', '.join(symbols)} | "
                f"deposit_pct на пару={per_pair*100:.2f}% | "
                f"leverage=x{ctx.profile.leverage} | "
                f"{'TESTNET' if ctx.profile.is_testnet else 'LIVE'}"
            )
        logger.info(line)

    def _notify_started_all(self):
        """
        Отправляет одно объединённое Telegram-уведомление о старте
        на каждого пользователя — со списком всех активных пар.
        """
        for uid, ctx in self.contexts.items():
            notifier = ctx.notifier
            if not notifier:
                continue
            symbols = list(ctx.engines.keys())
            if not symbols:
                continue

            # Берём баланс из первого движка (он уже проинициализирован)
            balance = 0.0
            first_engine = next(iter(ctx.engines.values()), None)
            if first_engine:
                try:
                    bal = first_engine.exchange.fetch_balance()
                    balance = bal.get("total", 0.0)
                except Exception:
                    pass

            notifier.notify_bot_started_multi(
                user_id=uid,
                exchange=ctx.profile.exchange,
                symbols=symbols,
                balance=balance,
                leverage=ctx.profile.leverage,
                deposit_pct=ctx.profile.deposit_pct,
                is_testnet=ctx.profile.is_testnet,
            )

    def _log_tick_result(self, uid: str, symbol: str, result: Dict):
        status = result.get("status", "?")
        if status == "ok":
            price = result.get("price", 0)
            mode = result.get("mode", "?")
            risk = result.get("risk", {})
            tick = result.get("tick", 0)
            logger.info(
                f"[{uid}:{symbol}] Тик #{tick} | "
                f"Mode={mode} | Price={price:.4f} | "
                f"DayPnL={risk.get('daily_pnl_pct', '?')} | "
                f"DD={risk.get('drawdown_pct', '?')}"
            )
        elif status == "risk_blocked":
            logger.warning(f"[{uid}:{symbol}] ТОРГОВЛЯ ЗАБЛОКИРОВАНА РИСК-МЕНЕДЖЕРОМ")
        else:
            logger.debug(f"[{uid}:{symbol}] Тик: {status}")

    def _send_summary(self, uid: str, ctx: UserContext):
        """Отправляет сводку по всем парам пользователя в Telegram."""
        if not ctx.notifier:
            return
        # Используем первый попавшийся движок с данными для метрик
        for sym, engine in ctx.engines.items():
            snap = engine._last_snapshot
            if snap:
                ctx.notifier.notify_tick_summary(
                    uid, self._global_tick, snap.close,
                    engine._current_mode or "?",
                    engine._last_risk_pnl_pct,
                    engine._last_risk_drawdown_pct,
                )
                break


# ──────────────────────────────────────────
#  Вспомогательные функции
# ──────────────────────────────────────────

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


# ──────────────────────────────────────────
#  Точка входа
# ──────────────────────────────────────────

def main():
    setup_logging("bot.log", "INFO")
    os.makedirs("data", exist_ok=True)

    _load_env()

    config = SystemConfig()

    # ── Telegram ──
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
        logger.info("Telegram уведомления ВКЛЮЧЕНЫ")
    else:
        logger.info(
            "Telegram уведомления ВЫКЛЮЧЕНЫ. "
            "Задайте TG_BOT_TOKEN и TG_CHAT_ID для включения."
        )

    mgr = UserManager(data_dir="data")
    user_ids = mgr.list_users()

    if not user_ids:
        logger.error("Нет пользователей в data/users.json")
        return

    runner = MultiUserRunner(config, notifier=notifier)

    for uid in user_ids:
        profile = mgr.get_user(uid)
        if not profile:
            continue

        if profile.is_testnet:
            logger.info(f"Пользователь '{uid}' — TESTNET режим")
        else:
            logger.warning(f"Пользователь '{uid}' — LIVE режим (реальные деньги!)")

        user_chat_id = profile.telegram_chat_id or config.telegram.chat_id
        user_notifier = TelegramNotifier(
            bot_token=config.telegram.bot_token,
            chat_id=user_chat_id,
            enabled=bool(config.telegram.bot_token and user_chat_id),
        )

        try:
            runner.add_user(profile, user_notifier=user_notifier)
        except Exception as e:
            logger.error(f"Ошибка добавления пользователя '{uid}': {e}")

    if not runner.contexts:
        logger.error("Нет testnet-пользователей для запуска")
        return

    # Интервал тика = 20 секунд (соответствует таймфрейму 1m для быстрой торговли)
    # Можно переопределить через env: TICK_INTERVAL_SEC=60
    tick_interval = int(os.environ.get("TICK_INTERVAL_SEC", 20))
    logger.info(f"Интервал тика: {tick_interval}s")

    try:
        runner.run(interval_seconds=tick_interval)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt. Завершаем работу...")
        runner._shutdown()


if __name__ == "__main__":
    main()
