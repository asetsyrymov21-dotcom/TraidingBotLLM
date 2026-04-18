# ============================================================
#  Smart Adaptive Trading System — grid_strategy.py
#  GRID-стратегия для флэтового рынка
#  Динамическая ширина сетки на основе ATR
# ============================================================

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict

from typing import TYPE_CHECKING

from config import GridConfig
from exchange import ExchangeConnector
from market_analyzer import MarketSnapshot

if TYPE_CHECKING:
    from telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)


@dataclass
class GridLevel:
    price: float
    order_id: Optional[str]
    side: str        # "buy" или "sell"
    amount: float
    filled: bool = False


@dataclass
class GridState:
    active: bool = False
    range_high: float = 0.0
    range_low: float = 0.0
    levels: List[GridLevel] = field(default_factory=list)
    entry_price: float = 0.0
    total_allocated: float = 0.0
    realized_pnl: float = 0.0


class GridStrategy:
    """
    GRID-стратегия для флэтового рынка.

    Логика:
    1. Определяет диапазон на основе ATR
    2. Расставляет сетку ордеров (buy ниже, sell выше)
    3. При выходе цены из диапазона → закрывает всё
    4. Динамически пересчитывает сетку при обновлении ATR
    """

    def __init__(self, exchange: ExchangeConnector, cfg: GridConfig,
                 notifier=None, user_id: str = ""):
        self.exchange = exchange
        self.cfg = cfg
        self.state = GridState()
        self.notifier = notifier
        self.user_id = user_id

    # ──────────────────────────────────────────
    #  Основной цикл
    # ──────────────────────────────────────────

    def tick(self, snapshot: MarketSnapshot) -> Dict:
        """
        Вызывается каждую свечу.
        Возвращает словарь с результатом действий.
        """
        price = snapshot.close
        atr   = snapshot.atr
        result = {"action": "none", "pnl": 0.0}

        if not self.state.active:
            return result

        # ── Проверка выхода из диапазона ──
        if self._check_breakout(price, atr):
            logger.warning(
                f"[GRID] Breakout! Price={price:.4f} out of "
                f"[{self.state.range_low:.4f}, {self.state.range_high:.4f}]"
            )
            pnl = self._close_all()
            # Telegram: выход из диапазона
            if self.notifier:
                self.notifier.notify_grid_breakout(self.user_id, price, pnl)
            self.state = GridState()
            result = {"action": "exit_breakout", "pnl": pnl}
            return result

        # ── Проверка исполненных ордеров и перестановка ──
        self._process_filled_orders(price)

        result["action"] = "grid_active"
        return result

    def setup(self, snapshot: MarketSnapshot) -> bool:
        """
        Инициализирует сетку при входе в флэт.
        Возвращает True если сетка успешно создана.
        """
        if self.state.active:
            logger.info("[GRID] Already active, skipping setup")
            return True

        price = snapshot.close
        atr   = snapshot.atr

        # Расчёт диапазона
        step         = atr * self.cfg.atr_multiplier
        total_range  = step * self.cfg.grid_levels
        range_high   = price + total_range / 2
        range_low    = price - total_range / 2

        # Расчёт размера позиции на уровень
        balance      = self.exchange.fetch_balance()
        total_alloc  = balance["free"] * self.cfg.max_deposit_pct
        per_level    = total_alloc / self.cfg.grid_levels
        amount       = self.exchange.calc_position_size(per_level / balance["free"], price)

        if amount <= 0:
            logger.error("[GRID] Cannot calculate position size")
            return False

        logger.info(
            f"[GRID] Setting up: range=[{range_low:.4f}, {range_high:.4f}] "
            f"step={step:.4f} levels={self.cfg.grid_levels} amount={amount}"
        )

        self.state.range_high    = range_high
        self.state.range_low     = range_low
        self.state.entry_price   = price
        self.state.total_allocated = total_alloc
        self.state.active        = True

        # Расставляем ордера
        self._place_grid_orders(price, step, amount, range_low, range_high)

        # Telegram: сетка активирована
        if self.notifier:
            self.notifier.notify_grid_setup(
                self.user_id, price, range_low, range_high,
                self.cfg.grid_levels, total_alloc,
            )
        return True

    def teardown(self):
        """Принудительное закрытие сетки"""
        if self.state.active:
            pnl = self._close_all()
            logger.info(f"[GRID] Teardown. Realized PnL: {pnl:.2f} USDT")
            self.state = GridState()
            return pnl
        return 0.0

    # ──────────────────────────────────────────
    #  Внутренняя логика
    # ──────────────────────────────────────────

    def _place_grid_orders(
        self,
        center: float,
        step: float,
        amount: float,
        range_low: float,
        range_high: float,
    ):
        """Расставляет лимитные ордера по сетке"""
        self.exchange.cancel_all_orders()
        self.state.levels = []

        # Уровни ниже центра — BUY (покупаем дешевле)
        for i in range(1, self.cfg.grid_levels // 2 + 1):
            buy_price = center - step * i
            if buy_price < range_low:
                break
            order = self.exchange.place_limit_order("buy", amount, buy_price)
            if order:
                self.state.levels.append(GridLevel(
                    price=buy_price,
                    order_id=order.get("id"),
                    side="buy",
                    amount=amount,
                ))

        # Уровни выше центра — SELL (продаём дороже)
        for i in range(1, self.cfg.grid_levels // 2 + 1):
            sell_price = center + step * i
            if sell_price > range_high:
                break
            order = self.exchange.place_limit_order("sell", amount, sell_price)
            if order:
                self.state.levels.append(GridLevel(
                    price=sell_price,
                    order_id=order.get("id"),
                    side="sell",
                    amount=amount,
                ))

        logger.info(f"[GRID] Placed {len(self.state.levels)} orders")

    def _check_breakout(self, price: float, atr: float) -> bool:
        """Проверяет выход цены за границы + буфер"""
        buffer = atr * self.cfg.breakout_multiplier
        return (
            price > self.state.range_high + buffer or
            price < self.state.range_low  - buffer
        )

    def _process_filled_orders(self, current_price: float):
        """
        Проверяет исполненные ордера.
        После исполнения BUY — ставит SELL на шаг выше (и наоборот).
        """
        open_orders = {o["id"]: o for o in self.exchange.fetch_open_orders()}

        for level in self.state.levels:
            if level.filled or level.order_id is None:
                continue
            if level.order_id not in open_orders:
                # Ордер исполнен
                level.filled = True
                step = (self.state.range_high - self.state.range_low) / self.cfg.grid_levels

                if level.side == "buy":
                    # Ставим SELL на шаг выше
                    sell_price = level.price + step
                    if sell_price <= self.state.range_high:
                        pnl_per_trade = (sell_price - level.price) * level.amount
                        self.state.realized_pnl += pnl_per_trade
                        order = self.exchange.place_limit_order("sell", level.amount, sell_price)
                        if order:
                            self.state.levels.append(GridLevel(
                                price=sell_price,
                                order_id=order.get("id"),
                                side="sell",
                                amount=level.amount,
                            ))
                        logger.info(
                            f"[GRID] BUY filled @ {level.price:.4f} → "
                            f"SELL placed @ {sell_price:.4f} | Est PnL: {pnl_per_trade:.4f}"
                        )
                        if self.notifier:
                            self.notifier.notify_grid_fill(
                                self.user_id, "buy", level.price, sell_price,
                            )

                elif level.side == "sell":
                    # Ставим BUY на шаг ниже
                    buy_price = level.price - step
                    if buy_price >= self.state.range_low:
                        order = self.exchange.place_limit_order("buy", level.amount, buy_price)
                        if order:
                            self.state.levels.append(GridLevel(
                                price=buy_price,
                                order_id=order.get("id"),
                                side="buy",
                                amount=level.amount,
                            ))
                        logger.info(
                            f"[GRID] SELL filled @ {level.price:.4f} → "
                            f"BUY placed @ {buy_price:.4f}"
                        )
                        if self.notifier:
                            self.notifier.notify_grid_fill(
                                self.user_id, "sell", level.price, buy_price,
                            )

    def _close_all(self) -> float:
        """Закрывает все ордера и позиции, возвращает PnL"""
        cancelled = self.exchange.cancel_all_orders()
        self.exchange.close_all_positions()
        pnl = self.state.realized_pnl
        logger.info(f"[GRID] Closed {cancelled} orders | Total realized PnL: {pnl:.2f}")
        return pnl

    @property
    def is_active(self) -> bool:
        return self.state.active

    def get_stats(self) -> Dict:
        return {
            "active": self.state.active,
            "range_high": self.state.range_high,
            "range_low": self.state.range_low,
            "levels_count": len(self.state.levels),
            "realized_pnl": self.state.realized_pnl,
        }
