# ============================================================
#  Smart Adaptive Trading System — bot_engine.py
#  Главный движок бота для одного пользователя
#  Оркестрирует все стратегии и управление рисками
# ============================================================

import logging
import time
from typing import Optional, Dict

from config import SystemConfig, UserProfile
from exchange import ExchangeConnector
from market_analyzer import MarketAnalyzer, MarketState, MarketSnapshot
from strategies import GridStrategy, TrendStrategy, EntryStrategy
from risk_manager import RiskManager
from telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)


class BotEngine:
    """
    Движок бота для одного пользователя и одной торговой пары.

    Логика:
    1. Каждый тик: загружаем свечи → анализируем рынок
    2. Флэт → GRID
    3. Тренд → TrendBot + EntryBot (параллельно, разный % депозита)
    4. Все действия проверяются через RiskManager

    Параметр symbol переопределяет profile.symbol — это позволяет
    создавать несколько BotEngine на один профиль (один на каждую пару).
    """

    def __init__(self, profile: UserProfile, config: SystemConfig,
                 notifier: Optional['TelegramNotifier'] = None,
                 symbol: Optional[str] = None,
                 deposit_pct_override: Optional[float] = None):
        # Если задан symbol — создаём копию профиля с нужной парой
        if symbol and symbol != profile.symbol:
            import copy
            profile = copy.copy(profile)
            profile.symbol = symbol

        # Если задан deposit_pct_override — применяем (для мультипарного режима)
        if deposit_pct_override is not None and deposit_pct_override != profile.deposit_pct:
            import copy
            profile = copy.copy(profile)
            profile.deposit_pct = deposit_pct_override

        self.profile = profile
        self.config = profile.get_effective_config(config)

        # Telegram-уведомления
        self.notifier = notifier

        # Компоненты
        self.exchange = ExchangeConnector(profile)
        self.analyzer = MarketAnalyzer(self.config.market_analyzer)
        self.risk_mgr = RiskManager(
            self.config.risk,
            commission_pct=profile.commission_pct,
        )

        # Стратегии (передаём notifier)
        self.grid_bot = GridStrategy(self.exchange, self.config.grid, notifier=notifier, user_id=profile.user_id)
        self.trend_bot = TrendStrategy(self.exchange, self.config.trend_bot, notifier=notifier, user_id=profile.user_id)
        self.entry_bot = EntryStrategy(self.exchange, self.config.entry_bot, notifier=notifier, user_id=profile.user_id)

        # Состояние
        self._current_mode: Optional[str] = None  # "grid" / "trend" / None
        self._last_snapshot: Optional[MarketSnapshot] = None
        self._tick_count: int = 0
        self._running: bool = False
        self._initialized: bool = False

    # ──────────────────────────────────────────
    #  Жизненный цикл
    # ──────────────────────────────────────────

    def start(self):
        """Запуск бота"""
        logger.info(f"[BOT:{self.profile.user_id}] Starting... {self.profile.symbol}")
        self._running = True

        # Инициализация риск-менеджера
        balance = self.exchange.fetch_balance()
        self.risk_mgr.initialize(balance["total"])
        self._initialized = True
        logger.info(
            f"[BOT:{self.profile.user_id}] Balance: {balance['total']:.2f} USDT"
        )

        # Telegram: бот запущен
        if self.notifier:
            self.notifier.notify_bot_started(
                self.profile.user_id, self.profile.symbol,
                self.profile.exchange, balance["total"],
            )

    def stop(self):
        """Остановка бота — закрывает всё"""
        logger.info(f"[BOT:{self.profile.user_id}] Stopping...")
        self._running = False

        # Закрываем все стратегии
        if self._current_mode == "grid":
            self.grid_bot.teardown()
        elif self._current_mode == "trend":
            self.trend_bot.force_close()
            self.entry_bot.force_close()

        # Итоговая статистика
        stats = self.get_stats()
        logger.info(f"[BOT:{self.profile.user_id}] Final stats: {stats}")

        # Telegram: бот остановлен
        if self.notifier:
            self.notifier.notify_bot_stopped(self.profile.user_id, stats)

    def tick(self) -> Dict:
        """
        Один шаг бота (вызывается каждую свечу).
        Возвращает словарь с результатами всех стратегий.
        """
        if not self._running or not self._initialized:
            return {"status": "not_running"}

        self._tick_count += 1
        result = {
            "tick": self._tick_count,
            "user": self.profile.user_id,
            "mode": self._current_mode,
            "actions": {},
        }

        # ── 1. Загрузка и анализ данных ──
        try:
            ohlcv = self.exchange.fetch_ohlcv(
                self.config.market_analyzer.timeframe,
                self.config.market_analyzer.candle_limit,
            )
        except Exception as e:
            logger.error(f"[BOT:{self.profile.user_id}] fetch_ohlcv failed: {e}")
            return {"status": "error", "message": str(e)}

        snapshot = self.analyzer.analyze(ohlcv)
        if not snapshot:
            return {"status": "insufficient_data"}

        self._last_snapshot = snapshot
        result["market_state"] = snapshot.state.value
        result["price"] = snapshot.close

        # ── 2. Проверка риск-лимитов ──
        balance = self.exchange.fetch_balance()
        risk_report = self.risk_mgr.check_can_trade(balance["total"])
        result["risk"] = {
            "can_trade": risk_report.can_trade,
            "daily_pnl_pct": f"{risk_report.daily_pnl_pct*100:.2f}%",
            "drawdown_pct": f"{risk_report.drawdown_pct*100:.2f}%",
        }

        if not risk_report.can_trade:
            logger.warning(
                f"[BOT:{self.profile.user_id}] TRADING BLOCKED: {risk_report.reason}"
            )
            # Telegram: торговля заблокирована
            if self.notifier:
                self.notifier.notify_risk_blocked(
                    self.profile.user_id, risk_report.reason,
                    result["risk"]["daily_pnl_pct"], result["risk"]["drawdown_pct"],
                )
            # Закрываем активные позиции при достижении лимитов
            self._emergency_close()
            result["status"] = "risk_blocked"
            return result

        # ── 3. Переключение стратегии ──
        new_mode = self._determine_mode(snapshot)
        old_mode = self._current_mode

        if new_mode != old_mode:
            self._switch_mode(snapshot, new_mode)
            self._current_mode = new_mode
            result["mode"] = self._current_mode
            result["mode_switch"] = f"{old_mode} -> {new_mode}"

            # Telegram: смена режима
            if self.notifier:
                self.notifier.notify_mode_switch(
                    self.profile.user_id, old_mode, new_mode,
                    snapshot.state.value, snapshot.close,
                    adx=snapshot.adx,
                )

        result["mode"] = self._current_mode

        # ── 4. Тик активной стратегии ──
        if self._current_mode == "grid":
            trend_has_pos = self.trend_bot.state.position is not None
            entry_has_pos = self.entry_bot.position is not None

            if trend_has_pos or entry_has_pos:
                # Есть открытые позиции от предыдущего тренд-режима.
                # Управляем ими (только TP/SL, новые позиции не открываем),
                # grid не запускаем пока они не закроются.
                if trend_has_pos:
                    trend_result = self.trend_bot.tick(snapshot)
                    result["actions"]["trend_manage"] = trend_result

                if entry_has_pos:
                    entry_result = self.entry_bot.tick(snapshot)
                    result["actions"]["entry_manage"] = entry_result

                result["actions"]["grid"] = {
                    "action": "pending",
                    "reason": "waiting_for_trend_positions_to_close",
                }

                # Если позиции только что закрылись — инициализируем grid
                if not self.trend_bot.state.position and not self.entry_bot.position:
                    logger.info(
                        f"[BOT:{self.profile.user_id}] Trend positions closed. "
                        f"Setting up GRID now."
                    )
                    success = self.grid_bot.setup(snapshot)
                    if not success:
                        logger.error(
                            f"[BOT:{self.profile.user_id}] Failed to setup GRID after transition"
                        )
            else:
                # Нет открытых тренд-позиций — работаем в штатном grid-режиме
                grid_result = self.grid_bot.tick(snapshot)
                result["actions"]["grid"] = grid_result

        elif self._current_mode == "trend":
            trend_result = self.trend_bot.tick(snapshot)
            entry_result = self.entry_bot.tick(snapshot)
            result["actions"]["trend"] = trend_result
            result["actions"]["entry"] = entry_result

            # Логируем завершённые сделки в риск-менеджер
            for r in [trend_result, entry_result]:
                if r.get("action", "").startswith("close_"):
                    strategy_name = "trend" if r is trend_result else "entry"
                    # NOTE: В production передавать реальные цены из ордера
                    pass

        result["status"] = "ok"
        return result

    # ──────────────────────────────────────────
    #  Переключение режимов
    # ──────────────────────────────────────────

    def _determine_mode(self, snapshot: MarketSnapshot) -> str:
        """Определяет нужный режим на основе состояния рынка"""
        if snapshot.state == MarketState.FLAT:
            return "grid"
        elif snapshot.state in (MarketState.TREND_UP, MarketState.TREND_DOWN):
            return "trend"
        return self._current_mode or "grid"

    def _has_open_trend_positions(self) -> bool:
        """Проверяет есть ли открытые позиции от трендовых стратегий"""
        return (
            self.trend_bot.state.position is not None or
            self.entry_bot.position is not None
        )

    def _switch_mode(self, snapshot: MarketSnapshot, new_mode: str):
        """Переключает стратегию, корректно завершая предыдущую"""
        logger.info(
            f"[BOT:{self.profile.user_id}] MODE SWITCH: "
            f"{self._current_mode} -> {new_mode} | {snapshot.state.value}"
        )

        if self._current_mode == "grid":
            # Grid: снимаем лимитные ордера, позиций нет
            self.grid_bot.teardown()

        elif self._current_mode == "trend":
            # Trend → НЕ закрываем принудительно.
            # Открытые позиции дойдут до TP или SL сами.
            # bot_engine продолжит вызывать tick для управления ими
            # даже находясь в режиме grid (см. tick()).
            if self._has_open_trend_positions():
                logger.info(
                    f"[BOT:{self.profile.user_id}] Trend positions still open — "
                    f"will manage until TP/SL, no force close"
                )

        # Инициализируем новый режим
        if new_mode == "grid":
            if not self._has_open_trend_positions():
                # Нет открытых позиций — сразу ставим сетку
                success = self.grid_bot.setup(snapshot)
                if not success:
                    logger.error(f"[BOT:{self.profile.user_id}] Failed to setup GRID")
            else:
                # Есть открытые позиции — откладываем grid setup до их закрытия
                logger.info(
                    f"[BOT:{self.profile.user_id}] Grid setup deferred — "
                    f"waiting for trend positions to close via TP/SL"
                )

    def _emergency_close(self):
        """Экстренное закрытие всех позиций"""
        logger.warning(f"[BOT:{self.profile.user_id}] EMERGENCY CLOSE")
        if self._current_mode == "grid":
            self.grid_bot.teardown()
        self.exchange.cancel_all_orders()
        self.exchange.close_all_positions()
        self._current_mode = None

        # Telegram: экстренное закрытие
        if self.notifier:
            self.notifier.notify_emergency_close(self.profile.user_id)

    # ──────────────────────────────────────────
    #  Статистика
    # ──────────────────────────────────────────

    def get_stats(self) -> Dict:
        balance = self.exchange.fetch_balance()
        return {
            "user": self.profile.user_id,
            "symbol": self.profile.symbol,
            "exchange": self.profile.exchange,
            "mode": self._current_mode,
            "tick_count": self._tick_count,
            "balance": balance,
            "risk": self.risk_mgr.get_session_stats(),
            "trend_bot": self.trend_bot.get_stats(),
            "entry_bot": self.entry_bot.get_stats(),
            "grid_bot": self.grid_bot.get_stats(),
            "market": {
                "state": (
                    self._last_snapshot.state.value
                    if self._last_snapshot
                    else "UNKNOWN"
                ),
                "price": self._last_snapshot.close if self._last_snapshot else 0,
            },
        }

    @property
    def is_running(self) -> bool:
        return self._running
