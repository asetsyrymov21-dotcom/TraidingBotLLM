# ============================================================
#  Smart Adaptive Trading System — trend_strategy.py
#  Трендовый бот с полным набором улучшений
# ============================================================

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, List

from typing import TYPE_CHECKING

from config import TrendBotConfig
from exchange import ExchangeConnector
from market_analyzer import MarketSnapshot

if TYPE_CHECKING:
    from telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)


class TradeResult(Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    NONE = "NONE"


@dataclass
class ActivePosition:
    side: str  # "long" или "short"
    entry_price: float
    amount: float
    tp_price: float
    sl_price: float
    order_id: Optional[str] = None
    open_time: float = field(default_factory=time.time)
    best_price: float = 0.0                 # Лучшая цена за время жизни позиции
    trail_stop_price: Optional[float] = None  # Текущий уровень trailing stop
    trail_active: bool = False              # Trailing stop активирован?


@dataclass
class TrendBotState:
    position: Optional[ActivePosition] = None
    last_result: TradeResult = TradeResult.NONE
    win_streak: int = 0
    loss_streak: int = 0
    pause_candles_left: int = 0
    current_size_multiplier: float = 1.0
    paused_until: float = 0.0
    total_pnl: float = 0.0
    trade_count: int = 0
    win_count: int = 0


class TrendStrategy:
    """
    Трендовый бот.

    Улучшения:
    - Фильтр тренда EMA50/200
    - RSI-фильтр (>50 лонг, <50 шорт)
    - Динамический размер позиции (серии побед/убытков)
    - Задержка после убытка (1 свеча)
    - Ограничение серии убытков (3–5 → пауза)
    - 3 уровня анти-сквиз защиты
    - WIN → продолжаем, LOSS → переворот
    """

    def __init__(self, exchange: ExchangeConnector, cfg: TrendBotConfig,
                 notifier: Optional['TelegramNotifier'] = None, user_id: str = "",
                 symbol: str = ""):
        self.exchange = exchange
        self.cfg = cfg
        self.state = TrendBotState()
        self.notifier = notifier
        self.user_id = user_id
        self.symbol = symbol
        self._tag = f"[TREND:{symbol}]" if symbol else "[TREND]"

    # ──────────────────────────────────────────
    #  Основной цикл
    # ──────────────────────────────────────────

    def tick(self, snapshot: MarketSnapshot) -> Dict:
        """Вызывается каждую свечу"""
        result = {"action": "none", "side": None, "pnl": 0.0, "reason": ""}

        # ── Пауза при серии убытков ──
        if self.state.paused_until > time.time():
            result["reason"] = "pause_active"
            if self.notifier:
                self.notifier.notify_trend_skip(self.user_id, "pause_active", snapshot.close, symbol=self.symbol)
            return result

        # ── Задержка после убытка ──
        if self.state.pause_candles_left > 0:
            self.state.pause_candles_left -= 1
            result["reason"] = f"delay_after_loss ({self.state.pause_candles_left} left)"
            return result

        # ── Управление открытой позицией ──
        if self.state.position:
            return self._manage_position(snapshot)

        # ── Поиск точки входа ──
        return self._find_entry(snapshot)

    # ──────────────────────────────────────────
    #  Управление позицией
    # ──────────────────────────────────────────

    def _manage_position(self, snapshot: MarketSnapshot) -> Dict:
        pos = self.state.position
        price = snapshot.close
        result = {"action": "hold", "side": pos.side, "pnl": 0.0, "reason": ""}

        # ── Таймаут: позиция висит слишком долго ──
        max_hold = getattr(self.cfg, 'max_hold_minutes', 240) * 60
        if time.time() - pos.open_time > max_hold:
            hours = (time.time() - pos.open_time) / 3600
            logger.warning(
                f"{self._tag} TIMEOUT! Position open for {hours:.1f}h > {max_hold//60}min. Force closing."
            )
            pnl = self._close_position(price, "timeout")
            result.update({"action": "close_timeout", "pnl": pnl})
            return result

        # ── Анти-сквиз: резкое движение против позиции (порог 15%) ──
        if self._check_squeeze(pos, price):
            logger.warning(f"{self._tag} SQUEEZE detected! Closing {pos.side} @ {price}")
            pnl = self._close_position(price, "squeeze")
            result.update({"action": "close_squeeze", "pnl": pnl})
            return result

        # ── Обновление Trailing Stop ──
        self._update_trailing_stop(pos, price)

        # ── Проверка Trailing Stop (если активирован) ──
        if pos.trail_active and pos.trail_stop_price is not None:
            triggered = (
                (pos.side == "long"  and price <= pos.trail_stop_price) or
                (pos.side == "short" and price >= pos.trail_stop_price)
            )
            if triggered:
                logger.info(
                    f"{self._tag} TRAIL STOP triggered | {pos.side.upper()} @ {price:.4f} | "
                    f"trail_stop={pos.trail_stop_price:.4f} best={pos.best_price:.4f}"
                )
                pnl = self._close_position(price, "trail_stop")
                result.update({"action": "close_trail_stop", "pnl": pnl, "reason": "trail_stop"})
                return result

        # ── Проверка TP ──
        if (pos.side == "long" and price >= pos.tp_price) or (
            pos.side == "short" and price <= pos.tp_price
        ):
            pnl = self._close_position(price, "tp")
            result.update({"action": "close_tp", "pnl": pnl})
            return result

        # ── Проверка SL (только если trailing ещё не активирован) ──
        if not pos.trail_active:
            if (pos.side == "long" and price <= pos.sl_price) or (
                pos.side == "short" and price >= pos.sl_price
            ):
                pnl = self._close_position(price, "sl")
                result.update({"action": "close_sl", "pnl": pnl})
                result["reverse_signal"] = "short" if pos.side == "long" else "long"
                return result

        return result

    def _find_entry(self, snapshot: MarketSnapshot) -> Dict:
        result = {"action": "none", "side": None, "pnl": 0.0, "reason": ""}

        rsi = snapshot.rsi or 50.0

        logger.info(
            f"{self._tag} find_entry | close={snapshot.close:.4f} RSI={rsi:.1f}"
        )

        # ── Направление по RSI ──
        if rsi > self.cfg.rsi_long_min:
            side = "long"
        elif rsi < self.cfg.rsi_short_max:
            side = "short"
        else:
            result["reason"] = f"rsi_neutral ({rsi:.1f})"
            logger.info(f"{self._tag} skip entry | reason={result['reason']}")
            return result

        # ── Фильтр объёма: блокируем аномально тихие свечи (<60% среднего) ──
        if snapshot.avg_volume > 0 and snapshot.volume < snapshot.avg_volume * 0.6:
            result["reason"] = (
                f"low_volume ({snapshot.volume:.0f} < 60% avg {snapshot.avg_volume:.0f})"
            )
            logger.info(f"{self._tag} skip entry | reason={result['reason']}")
            return result

        # ── Расчёт размера позиции ──
        price = snapshot.close
        amount = self._calc_dynamic_size(price)

        if amount <= 0:
            result["reason"] = "insufficient_balance"
            logger.warning(f"{self._tag} skip entry | reason={result['reason']}")
            return result

        # ── Открытие позиции ──
        order = self.exchange.place_market_order(side, amount)

        if not order:
            result["reason"] = "order_failed"
            logger.warning(f"{self._tag} skip entry | reason={result['reason']}")
            if self.notifier:
                self.notifier.notify_order_failed(
                    self.user_id, "ТРЕНД", side, price,
                    "place_market_order вернул None — проверь API-ключи, баланс и плечо"
                )
            return result

        # ── Расчёт TP/SL (ATR-адаптивный) ──
        tp_price, sl_price = self._calc_tp_sl(price, side, snapshot=snapshot)

        self.state.position = ActivePosition(
            side=side,
            entry_price=price,
            amount=amount,
            tp_price=tp_price,
            sl_price=sl_price,
            order_id=order.get("id"),
            best_price=price,
        )
        self.state.trade_count += 1

        logger.info(
            f"{self._tag} OPEN {side.upper()} @ {price:.4f} | "
            f"TP={tp_price:.4f} SL={sl_price:.4f} | Amount={amount} | RSI={rsi:.1f}"
        )

        # Telegram: открыта позиция
        if self.notifier:
            self.notifier.notify_trend_open(
                self.user_id, side, price, amount, tp_price, sl_price,
                rsi, 0.0, 0.0,
                self.state.last_result.value, self.state.current_size_multiplier,
                symbol=self.symbol,
                leverage=self.exchange.profile.leverage,
            )

        result.update({"action": f"open_{side}", "side": side, "reason": "rsi_entry"})
        return result

    # ──────────────────────────────────────────
    #  Вспомогательные методы
    # ──────────────────────────────────────────

    def _calc_dynamic_size(self, price: float) -> float:
        """Динамический размер позиции на основе серий"""
        cfg = self.cfg
        base_pct = cfg.base_position_pct * self.state.current_size_multiplier

        # Ограничиваем диапазон
        base_pct = max(cfg.min_position_pct, min(cfg.max_position_pct, base_pct))
        return self.exchange.calc_position_size(base_pct, price)

    def _calc_tp_sl(self, price: float, side: str, snapshot=None):
        """Рассчитывает TP и SL с ATR-адаптацией."""
        atr_pct = (snapshot.atr_pct or 0.0) if snapshot else 0.0

        quiet_thr    = getattr(self.cfg, "atr_quiet_threshold",    0.003)
        volatile_thr = getattr(self.cfg, "atr_volatile_threshold", 0.008)
        tp_quiet     = getattr(self.cfg, "tp_quiet",               0.002)
        tp_normal    = getattr(self.cfg, "tp_normal",              0.005)
        tp_volatile  = getattr(self.cfg, "tp_volatile",            0.010)
        sl_mult      = getattr(self.cfg, "sl_multiplier",          8.0)

        if atr_pct > 0 and atr_pct < quiet_thr:
            tp_pct = tp_quiet
            regime = "quiet"
        elif atr_pct >= volatile_thr:
            tp_pct = tp_volatile
            regime = "volatile"
        else:
            tp_pct = tp_normal
            regime = "normal"

        sl_pct = tp_pct * sl_mult

        logger.info(
            f"{self._tag} adaptive_tp_sl | ATR%={atr_pct*100:.3f}% "
            f"regime={regime} TP={tp_pct*100:.2f}% SL={sl_pct*100:.2f}%"
        )

        if side == "long":
            tp = price * (1 + tp_pct)
            sl = price * (1 - sl_pct)
        else:
            tp = price * (1 - tp_pct)
            sl = price * (1 + sl_pct)
        return tp, sl

    def _close_position(self, price: float, reason: str) -> float:
        pos = self.state.position
        if not pos:
            return 0.0

        close_side = "sell" if pos.side == "long" else "buy"
        self.exchange.place_market_order(close_side, pos.amount, reduce_only=True)

        # Расчёт PnL
        if pos.side == "long":
            pnl = (price - pos.entry_price) * pos.amount
        else:
            pnl = (pos.entry_price - price) * pos.amount

        # Комиссия биржи: ~0.04% от размера позиции при открытии + закрытии
        # Размер позиции = amount * price, комиссия всегда вычитается (не зависит от знака pnl)
        _commission = abs(pos.amount * price * self.exchange.profile.leverage * 0.0008)
        pnl -= _commission  # комиссия

        self.state.total_pnl += pnl
        is_win = pnl > 0

        # Обновление серий и мультипликатора
        if is_win:
            self.state.win_streak += 1
            self.state.loss_streak = 0
            self.state.win_count += 1
            self.state.current_size_multiplier = min(
                self.state.current_size_multiplier * self.cfg.win_scale_up,
                3.0,
            )
            self.state.last_result = TradeResult.WIN
        else:
            self.state.loss_streak += 1
            self.state.win_streak = 0
            self.state.current_size_multiplier = max(
                self.state.current_size_multiplier * self.cfg.loss_scale_down,
                0.3,
            )
            self.state.last_result = TradeResult.LOSS
            self.state.pause_candles_left = self.cfg.delay_after_loss

            # Серия убытков → пауза
            if self.state.loss_streak >= self.cfg.loss_streak_pause:
                pause_secs = 20 * 60  # 20 минут
                self.state.paused_until = time.time() + pause_secs
                logger.warning(
                    f"{self._tag} Loss streak {self.state.loss_streak}! "
                    f"Pausing for {pause_secs//60} minutes."
                )

        logger.info(
            f"{self._tag} CLOSE {pos.side.upper()} @ {price:.4f} | "
            f"PnL={pnl:.4f} | Reason={reason} | "
            f"Win={self.state.win_streak} Loss={self.state.loss_streak}"
        )

        # Telegram: позиция закрыта
        if self.notifier:
            self.notifier.notify_trend_close(
                self.user_id, pos.side, pos.entry_price, price, pnl, reason,
                self.state.win_streak, self.state.loss_streak,
                symbol=self.symbol,
                tp_price=pos.tp_price,
                sl_price=pos.sl_price,
            )

        self.state.position = None
        return pnl

    def _update_trailing_stop(self, pos: ActivePosition, price: float) -> None:
        """
        Обновляет trailing stop по лучшей цене.
        Активируется когда прибыль >= trail_activate_pct.
        После активации trailing stop только подтягивается в сторону прибыли.
        """
        trail_pct      = self.cfg.trail_pct
        activate_pct   = self.cfg.trail_activate_pct

        if pos.side == "long":
            # Обновляем лучшую цену
            if price > pos.best_price:
                pos.best_price = price
            # Активируем trailing при достаточной прибыли
            if pos.best_price >= pos.entry_price * (1 + activate_pct):
                pos.trail_active = True
                new_trail = pos.best_price * (1 - trail_pct)
                # Trailing stop движется только вверх
                if pos.trail_stop_price is None or new_trail > pos.trail_stop_price:
                    pos.trail_stop_price = new_trail
                    logger.debug(
                        f"[TRAIL] LONG trail updated: best={pos.best_price:.4f} "
                        f"trail_stop={pos.trail_stop_price:.4f}"
                    )
        else:  # short
            # Для шорта лучшая цена — минимальная
            if pos.best_price == 0.0 or price < pos.best_price:
                pos.best_price = price
            # Активируем trailing при достаточной прибыли
            if pos.best_price <= pos.entry_price * (1 - activate_pct):
                pos.trail_active = True
                new_trail = pos.best_price * (1 + trail_pct)
                # Trailing stop движется только вниз
                if pos.trail_stop_price is None or new_trail < pos.trail_stop_price:
                    pos.trail_stop_price = new_trail
                    logger.debug(
                        f"[TRAIL] SHORT trail updated: best={pos.best_price:.4f} "
                        f"trail_stop={pos.trail_stop_price:.4f}"
                    )

    def _check_squeeze(self, pos: ActivePosition, price: float) -> bool:
        """Анти-сквиз: цена движется против позиции > squeeze_threshold (15%)"""
        if pos.side == "long":
            drop = (pos.entry_price - price) / pos.entry_price
            return drop > self.cfg.squeeze_threshold
        else:
            rise = (price - pos.entry_price) / pos.entry_price
            return rise > self.cfg.squeeze_threshold

    def manage_tp_sl_only(self, snapshot: MarketSnapshot) -> Dict:
        """
        Управляет позицией ТОЛЬКО через TP / Trail Stop / SL.
        Используется в wait-режиме (флэт) — без anti-squeeze и без
        volatility-проверок, чтобы позиция гарантированно дожила до TP/SL.
        """
        if not self.state.position:
            return {"action": "none", "pnl": 0.0, "reason": "no_position"}

        pos   = self.state.position
        price = snapshot.close
        result: Dict = {"action": "hold", "side": pos.side, "pnl": 0.0, "reason": ""}

        # ── Обновление Trailing Stop ──
        self._update_trailing_stop(pos, price)

        # ── Проверка Trailing Stop ──
        if pos.trail_active and pos.trail_stop_price is not None:
            triggered = (
                (pos.side == "long"  and price <= pos.trail_stop_price) or
                (pos.side == "short" and price >= pos.trail_stop_price)
            )
            if triggered:
                logger.info(
                    f"{self._tag} [wait] TRAIL STOP | {pos.side.upper()} @ {price:.4f} "
                    f"trail={pos.trail_stop_price:.4f}"
                )
                pnl = self._close_position(price, "trail_stop")
                result.update({"action": "close_trail_stop", "pnl": pnl})
                return result

        # ── Проверка TP ──
        if (pos.side == "long"  and price >= pos.tp_price) or \
           (pos.side == "short" and price <= pos.tp_price):
            pnl = self._close_position(price, "tp")
            result.update({"action": "close_tp", "pnl": pnl})
            return result

        # ── Проверка SL (только если trailing ещё не активирован) ──
        if not pos.trail_active:
            if (pos.side == "long"  and price <= pos.sl_price) or \
               (pos.side == "short" and price >= pos.sl_price):
                pnl = self._close_position(price, "sl")
                result.update({"action": "close_sl", "pnl": pnl})
                return result

        return result

    def force_close(self) -> float:
        """Принудительное закрытие позиции"""
        if self.state.position:
            ticker = self.exchange.fetch_ticker()
            price = ticker.get("last", self.state.position.entry_price)
            return self._close_position(price, "force_close")
        return 0.0

    def get_stats(self) -> Dict:
        winrate = self.state.win_count / max(self.state.trade_count, 1) * 100
        return {
            "total_pnl": round(self.state.total_pnl, 4),
            "trade_count": self.state.trade_count,
            "win_count": self.state.win_count,
            "win_rate": round(winrate, 1),
            "win_streak": self.state.win_streak,
            "loss_streak": self.state.loss_streak,
            "size_multiplier": round(self.state.current_size_multiplier, 2),
        }
