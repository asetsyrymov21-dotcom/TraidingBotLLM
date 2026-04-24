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
from strategies import TrendStrategy, EntryStrategy
from risk_manager import RiskManager
from telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)


class BotEngine:
    """
    Движок бота для одного пользователя и одной торговой пары.

    Логика:
    1. Каждый тик: загружаем свечи → анализируем рынок
    2. Тренд → TrendBot (основная стратегия)
    3. Флэт → ожидание (wait), позиция дожидается TP/SL
    4. Все действия проверяются через RiskManager

    Параметр symbol переопределяет profile.symbol — это позволяет
    создавать несколько BotEngine на один профиль (один на каждую пару).
    """

    def __init__(self, profile: UserProfile, config: SystemConfig,
                 notifier: Optional['TelegramNotifier'] = None,
                 symbol: Optional[str] = None,
                 deposit_pct_override: Optional[float] = None,
                 notify_start: bool = True):
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

        # Единая метка для логов: "alice:BTC/USDT" — чтобы в мультипарном
        # режиме было видно какой движок пишет в лог.
        self._log_label = f"{profile.user_id}:{profile.symbol}"

        # Telegram-уведомления
        self.notifier = notifier

        # Компоненты
        self.exchange = ExchangeConnector(profile)
        self.analyzer = MarketAnalyzer(self.config.market_analyzer, label=self._log_label)
        self.risk_mgr = RiskManager(
            self.config.risk,
            commission_pct=profile.commission_pct,
        )

        # Стратегии (передаём notifier и symbol для логов)
        self.trend_bot = TrendStrategy(
            self.exchange, self.config.trend_bot,
            notifier=notifier, user_id=profile.user_id, symbol=profile.symbol,
        )
        self.entry_bot = EntryStrategy(
            self.exchange, self.config.entry_bot,
            notifier=notifier, user_id=profile.user_id, symbol=profile.symbol,
        )

        # Состояние
        self._notify_start = notify_start  # False в мультипарном режиме
        self._current_mode: Optional[str] = None  # "trend" / "wait" / None
        self._last_snapshot: Optional[MarketSnapshot] = None
        self._last_risk_pnl_pct: str = "0.00%"     # Последний дневной PnL % (из тика)
        self._last_risk_drawdown_pct: str = "0.00%" # Последняя просадка % (из тика)
        self._tick_count: int = 0
        self._running: bool = False
        self._initialized: bool = False

    # ──────────────────────────────────────────
    #  Жизненный цикл
    # ──────────────────────────────────────────

    def start(self):
        """Запуск бота"""
        logger.info(f"[BOT:{self._log_label}] Starting... {self.profile.symbol}")
        self._running = True

        # Инициализация риск-менеджера
        balance = self.exchange.fetch_balance()
        self.risk_mgr.initialize(balance["total"])
        self._initialized = True
        logger.info(
            f"[BOT:{self._log_label}] Balance: {balance['total']:.2f} USDT"
        )

        # Telegram: бот запущен (только в однопарном режиме;
        # в мультипарном main.py шлёт одно объединённое сообщение)
        if self.notifier and self._notify_start:
            self.notifier.notify_bot_started(
                self.profile.user_id, self.profile.symbol,
                self.profile.exchange, balance["total"],
            )

    def stop(self):
        """Остановка бота — закрывает всё"""
        logger.info(f"[BOT:{self._log_label}] Stopping...")
        self._running = False

        # Закрываем все стратегии
        if self._current_mode == "trend":
            self.trend_bot.force_close()
            self.entry_bot.force_close()

        # Итоговая статистика
        stats = self.get_stats()
        logger.info(f"[BOT:{self._log_label}] Final stats: {stats}")

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
            logger.error(f"[BOT:{self._log_label}] fetch_ohlcv failed: {e}")
            return {"status": "error", "message": str(e)}

        snapshot = self.analyzer.analyze(ohlcv)
        if not snapshot:
            return {"status": "insufficient_data"}

        self._last_snapshot = snapshot
        result["market_state"] = snapshot.state.value
        result["price"] = snapshot.close

        # ── 2. Проверка риск-лимитов ──
        balance = self.exchange.fetch_balance()
        if self.notifier:
            self.notifier.update_balance(balance["total"])
        risk_report = self.risk_mgr.check_can_trade(balance["total"])
        self._last_risk_pnl_pct = f"{risk_report.daily_pnl_pct*100:.2f}%"
        self._last_risk_drawdown_pct = f"{risk_report.drawdown_pct*100:.2f}%"
        result["risk"] = {
            "can_trade": risk_report.can_trade,
            "daily_pnl_pct": self._last_risk_pnl_pct,
            "drawdown_pct": self._last_risk_drawdown_pct,
        }

        if not risk_report.can_trade:
            logger.warning(
                f"[BOT:{self._log_label}] TRADING BLOCKED: {risk_report.reason}"
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
                    symbol=self.profile.symbol,
                    ema_fast=snapshot.ema_fast,
                    ema_slow=snapshot.ema_slow,
                    atr=snapshot.atr,
                )

        result["mode"] = self._current_mode

        # ── 4. Тик стратегий ──
        # EntryStrategy — ГЛАВНАЯ (Win/Loss система).
        # Первый вход — по 3 индикаторам (RSI+MACD+BB) только в тренде.
        # Последующие — win/loss продолжение/переворот (в любом режиме).
        entry_result = self.entry_bot.tick(snapshot)
        result["actions"]["entry"] = entry_result

        # TrendStrategy — вторичная, запускается только если EntryStrategy без позиции
        if self.entry_bot.position is None and self._current_mode == "trend":
            trend_result = self.trend_bot.tick(snapshot)
            result["actions"]["trend"] = trend_result

        # В wait-режиме управляем открытой позицией TrendStrategy
        if self._current_mode == "wait" and self.trend_bot.state.position is not None:
            trend_result = self.trend_bot.tick(snapshot)
            result["actions"]["trend_manage"] = trend_result

        # ── 5. Обновление футера Telegram (баланс + PnL + сумма в сделке) ──
        if self.notifier:
            session_pnl = (
                self.entry_bot.total_pnl +
                self.trend_bot.state.total_pnl
            )
            in_trade_amount = 0.0
            if self.entry_bot.position:
                in_trade_amount = (
                    self.entry_bot.position.amount *
                    self.entry_bot.position.entry_price
                )
            elif self.trend_bot.state.position:
                in_trade_amount = (
                    self.trend_bot.state.position.amount *
                    self.trend_bot.state.position.entry_price
                )
            self.notifier.update_session_info(session_pnl, in_trade_amount)

        result["status"] = "ok"
        return result

    # ──────────────────────────────────────────
    #  Переключение режимов
    # ──────────────────────────────────────────

    def _determine_mode(self, snapshot: MarketSnapshot) -> str:
        """Определяет нужный режим на основе состояния рынка.
        На флэте ждём тренд, не торгуем."""
        if snapshot.state in (MarketState.TREND_UP, MarketState.TREND_DOWN):
            return "trend"
        return "wait"  # флэт / UNKNOWN → ожидание без сделок

    def _has_open_trend_positions(self) -> bool:
        """Проверяет есть ли открытые позиции от трендовых стратегий"""
        return (
            self.trend_bot.state.position is not None or
            self.entry_bot.position is not None
        )

    def _switch_mode(self, snapshot: MarketSnapshot, new_mode: str):
        """Переключает режим: trend / wait."""
        logger.info(
            f"[BOT:{self._log_label}] MODE SWITCH: "
            f"{self._current_mode} -> {new_mode} | {snapshot.state.value}"
        )

        if self._current_mode == "trend" and new_mode == "wait":
            # Уходим во флэт — НЕ закрываем позицию принудительно.
            # Она дойдёт до TP или SL сама (управление продолжается в tick).
            if self.trend_bot.state.position is not None:
                logger.info(
                    f"[BOT:{self._log_label}] Switching to wait — "
                    f"trend position will close via TP/SL naturally"
                )

    def _emergency_close(self):
        """Экстренное закрытие всех позиций"""
        logger.warning(f"[BOT:{self._log_label}] EMERGENCY CLOSE")
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
