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
from market_analyzer import MarketSnapshot, MarketState
from strategies.adx_logic import adx_signal, ADXConfig, Signal

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
    prev_adx: float = 0.0          # ADX прошлой свечи (для динамики)


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
                 adx_cfg: ADXConfig = None):
        self.exchange = exchange
        self.cfg = cfg
        self.state = TrendBotState()
        self.notifier = notifier
        self.user_id = user_id
        self.adx_cfg = adx_cfg or ADXConfig()   # пороги ADX-логики

    # ──────────────────────────────────────────
    #  Основной цикл
    # ──────────────────────────────────────────

    def tick(self, snapshot: MarketSnapshot) -> Dict:
        """Вызывается каждую свечу"""
        result = {"action": "none", "side": None, "pnl": 0.0, "reason": ""}

        # ── ADX-сигнал (вычисляем один раз на тик) ──
        current_position = "none"
        if self.state.position:
            current_position = self.state.position.side

        adx_sig: Signal = adx_signal(
            adx      = snapshot.adx,
            prev_adx = self.state.prev_adx,
            plus_di  = snapshot.plus_di,
            minus_di = snapshot.minus_di,
            position = current_position,
            cfg      = self.adx_cfg,
        )
        logger.info(
            f"[TREND] ADX signal: {adx_sig} | "
            f"ADX={snapshot.adx:.1f}(prev={self.state.prev_adx:.1f}) "
            f"+DI={snapshot.plus_di:.1f} -DI={snapshot.minus_di:.1f} "
            f"pos={current_position}"
        )

        # Сохраняем ADX для следующего тика
        self.state.prev_adx = snapshot.adx

        # ── Пауза при серии убытков ──
        if self.state.paused_until > time.time():
            result["reason"] = "pause_active"
            if self.notifier:
                self.notifier.notify_trend_skip(self.user_id, "pause_active", snapshot.close)
            return result

        # ── Задержка после убытка ──
        if self.state.pause_candles_left > 0:
            self.state.pause_candles_left -= 1
            result["reason"] = (
                f"delay_after_loss ({self.state.pause_candles_left} left)"
            )
            return result

        # ── Анти-сквиз: аномальная волатильность ──
        if self._check_abnormal_volatility(snapshot):
            logger.warning("[TREND] Abnormal volatility — skipping entry")
            result["reason"] = "high_volatility"
            if self.notifier:
                self.notifier.notify_trend_skip(self.user_id, "high_volatility", snapshot.close)
            return result

        # ── Управление открытой позицией ──
        if self.state.position:
            return self._manage_position(snapshot, adx_sig)

        # ── Поиск точки входа ──
        return self._find_entry(snapshot, adx_sig)

    # ──────────────────────────────────────────
    #  Управление позицией
    # ──────────────────────────────────────────

    def _manage_position(self, snapshot: MarketSnapshot, adx_sig: Signal) -> Dict:
        pos = self.state.position
        price = snapshot.close
        result = {"action": "hold", "side": pos.side, "pnl": 0.0, "reason": ""}

        # ── Анти-сквиз: резкое движение против позиции ──
        if self._check_squeeze(pos, price):
            logger.warning(f"[TREND] SQUEEZE detected! Closing {pos.side} @ {price}")
            pnl = self._close_position(price, "squeeze")
            result.update({"action": "close_squeeze", "pnl": pnl})
            return result

        # ── Ранний выход по ADX: DI развернулись или тренд угасает ──
        if adx_sig in ("exit_long", "exit_short"):
            logger.info(f"[TREND] ADX exit signal: {adx_sig} | Closing {pos.side} @ {price}")
            pnl = self._close_position(price, f"adx_{adx_sig}")
            result.update({"action": f"close_{adx_sig}", "pnl": pnl, "reason": adx_sig})
            return result

        # ── Проверка TP ──
        if (pos.side == "long" and price >= pos.tp_price) or (
            pos.side == "short" and price <= pos.tp_price
        ):
            pnl = self._close_position(price, "tp")
            result.update({"action": "close_tp", "pnl": pnl})
            return result

        # ── Проверка SL ──
        if (pos.side == "long" and price <= pos.sl_price) or (
            pos.side == "short" and price >= pos.sl_price
        ):
            pnl = self._close_position(price, "sl")
            result.update({"action": "close_sl", "pnl": pnl})
            # После SL → переворот через задержку
            result["reverse_signal"] = "short" if pos.side == "long" else "long"
            return result

        return result

    def _find_entry(self, snapshot: MarketSnapshot, adx_sig: Signal) -> Dict:
        result = {"action": "none", "side": None, "pnl": 0.0, "reason": ""}

        logger.info(
            f"[TREND] find_entry start | state={getattr(snapshot.state, 'value', snapshot.state)} "
            f"close={snapshot.close} adx_sig={adx_sig} rsi={snapshot.rsi}"
        )

        # ── Фильтр: только торгуем в тренде ──
        if snapshot.state not in (MarketState.TREND_UP, MarketState.TREND_DOWN):
            result["reason"] = "not_trending"
            logger.info(f"[TREND] skip entry | reason={result['reason']}")
            return result

        # ── ADX-фильтр: нет чёткого сигнала → не входим ──
        if adx_sig not in ("long", "short"):
            result["reason"] = f"adx_no_entry ({adx_sig})"
            logger.info(f"[TREND] skip entry | reason={result['reason']}")
            return result

        # Направление по ADX/DI (быстро и точно реагирует на разворот)
        adx_side = adx_sig   # "long" или "short"

        logger.info(f"[TREND] adx_side selected | adx_side={adx_side}")

        # ── RSI-фильтр (дополнительное подтверждение) ──
        rsi = snapshot.rsi or 50.0
        rsi_long_min  = getattr(self.cfg, "rsi_long_min",  45)
        rsi_short_max = getattr(self.cfg, "rsi_short_max", 55)

        if adx_side == "long" and rsi < rsi_long_min:
            result["reason"] = f"rsi_below_threshold ({rsi:.2f} < {rsi_long_min})"
            logger.info(f"[TREND] skip entry | reason={result['reason']}")
            return result

        if adx_side == "short" and rsi > rsi_short_max:
            result["reason"] = f"rsi_above_threshold ({rsi:.2f} > {rsi_short_max})"
            logger.info(f"[TREND] skip entry | reason={result['reason']}")
            return result

        # ── Определение стороны (WIN/LOSS логика) ──
        side = self._determine_side(adx_side)
        logger.info(
            f"[TREND] side determined | adx_side={adx_side} "
            f"last_result={self.state.last_result} final_side={side}"
        )

        # ── Расчёт размера позиции ──
        price = snapshot.close
        amount = self._calc_dynamic_size(price)

        logger.info(
            f"[TREND] amount calculated | price={price:.4f} "
            f"size_multiplier={self.state.current_size_multiplier} amount={amount}"
        )

        if amount <= 0:
            result["reason"] = "insufficient_balance"
            logger.warning(f"[TREND] skip entry | reason={result['reason']}")
            return result

        # ── Открытие позиции ──
        logger.info(f"[TREND] calling place_market_order | side={side} amount={amount}")
        order = self.exchange.place_market_order(side, amount)
        logger.info(f"[TREND] place_market_order result | order={order}")

        if not order:
            result["reason"] = "order_failed"
            logger.warning(f"[TREND] skip entry | reason={result['reason']}")
            if self.notifier:
                self.notifier.notify_order_failed(
                    self.user_id, "ТРЕНД", side, price,
                    "place_market_order вернул None — проверь API-ключи, баланс и плечо"
                )
            return result

        # ── Расчёт TP/SL ──
        tp_price, sl_price = self._calc_tp_sl(price, side)

        self.state.position = ActivePosition(
            side=side,
            entry_price=price,
            amount=amount,
            tp_price=tp_price,
            sl_price=sl_price,
            order_id=order.get("id"),
        )
        self.state.trade_count += 1

        logger.info(
            f"[TREND] OPEN {side.upper()} @ {price:.4f} | "
            f"TP={tp_price:.4f} SL={sl_price:.4f} | "
            f"Amount={amount} | RSI={rsi:.1f}"
        )

        # Telegram: открыта позиция
        if self.notifier:
            self.notifier.notify_trend_open(
                self.user_id, side, price, amount, tp_price, sl_price,
                rsi, snapshot.ema_fast, snapshot.ema_slow,
                self.state.last_result.value, self.state.current_size_multiplier,
            )

        result.update({"action": f"open_{side}", "side": side, "reason": "trend_entry"})
        return result

    # ──────────────────────────────────────────
    #  Вспомогательные методы
    # ──────────────────────────────────────────

    def _determine_side(self, trend_side: str) -> str:
        """WIN → продолжаем тренд, LOSS → переворот"""
        if self.state.last_result == TradeResult.LOSS:
            return "short" if trend_side == "long" else "long"
        return trend_side

    def _calc_dynamic_size(self, price: float) -> float:
        """Динамический размер позиции на основе серий"""
        cfg = self.cfg
        base_pct = cfg.base_position_pct * self.state.current_size_multiplier

        # Ограничиваем диапазон
        base_pct = max(cfg.min_position_pct, min(cfg.max_position_pct, base_pct))
        return self.exchange.calc_position_size(base_pct, price)

    def _calc_tp_sl(self, price: float, side: str):
        """Рассчитывает TP и SL"""
        if side == "long":
            tp = price * (1 + self.cfg.tp_pct)
            sl = price * (1 - self.cfg.sl_pct)
        else:
            tp = price * (1 - self.cfg.tp_pct)
            sl = price * (1 + self.cfg.sl_pct)
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

        pnl -= pnl * self.exchange.profile.leverage * 0.001  # комиссия

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
                    f"[TREND] Loss streak {self.state.loss_streak}! "
                    f"Pausing for {pause_secs//60} minutes."
                )

        logger.info(
            f"[TREND] CLOSE {pos.side.upper()} @ {price:.4f} | "
            f"PnL={pnl:.4f} | Reason={reason} | "
            f"Win={self.state.win_streak} Loss={self.state.loss_streak}"
        )

        # Telegram: позиция закрыта
        if self.notifier:
            self.notifier.notify_trend_close(
                self.user_id, pos.side, pos.entry_price, price, pnl, reason,
                self.state.win_streak, self.state.loss_streak,
            )

        self.state.position = None
        return pnl

    def _check_squeeze(self, pos: ActivePosition, price: float) -> bool:
        """Анти-сквиз: цена резко движется против позиции"""
        if pos.side == "long":
            drop = (pos.entry_price - price) / pos.entry_price
            return drop > self.cfg.squeeze_threshold
        else:
            rise = (price - pos.entry_price) / pos.entry_price
            return rise > self.cfg.squeeze_threshold

    def _check_abnormal_volatility(self, snapshot: MarketSnapshot) -> bool:
        """Анти-сквиз: аномально высокий ATR"""
        return snapshot.high_volatility

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
            "size_multiplier": round(self.state.current_size_multiplier, 3),
            "has_position": self.state.position is not None,
        }
