# ============================================================
#  Smart Adaptive Trading System — risk_manager.py
#  Глобальный риск-менеджер и управление капиталом
# ============================================================

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from config import RiskConfig

logger = logging.getLogger(__name__)


@dataclass
class DailyStats:
    date: str = ""
    starting_balance: float = 0.0
    current_balance: float = 0.0
    pnl: float = 0.0
    trade_count: int = 0
    win_count: int = 0
    commission_paid: float = 0.0
    blocked: bool = False   # Торговля заблокирована на сегодня


@dataclass
class RiskReport:
    """Отчёт о текущем состоянии рисков"""
    can_trade: bool
    reason: str
    daily_pnl_pct: float
    drawdown_pct: float
    daily_stats: DailyStats


class RiskManager:
    """
    Глобальный риск-менеджер.

    Контролирует:
    - Дневной убыток (лимит 5%)
    - Максимальную просадку (лимит 15%)
    - Комиссию системы с прибыли пользователя
    - Общую статистику сессии
    """

    def __init__(self, cfg: RiskConfig, commission_pct: float = 0.20):
        self.cfg = cfg
        self.commission_pct = commission_pct  # Комиссия системы с прибыли
        self.peak_balance: float = 0.0
        self.session_start: float = time.time()
        self.daily_stats = DailyStats(date=self._today())
        self.trade_history: List[Dict] = []

    # ──────────────────────────────────────────
    #  Основные проверки
    # ──────────────────────────────────────────

    def initialize(self, balance: float):
        """Инициализация при старте"""
        self.peak_balance = balance
        if self.daily_stats.starting_balance == 0:
            self.daily_stats.starting_balance = balance
            self.daily_stats.current_balance  = balance

    def check_can_trade(self, current_balance: float, session_pnl: float = 0.0) -> RiskReport:
        """
        Проверяет, можно ли открывать новые позиции.
        Возвращает RiskReport с флагом can_trade.

        session_pnl — реализованный PnL из стратегий (entry_bot + trend_bot).
        Используется вместо balance delta, чтобы залог маржи под открытые
        позиции не воспринимался как торговый убыток.
        """
        self._refresh_daily(current_balance)

        # ── Расчёт метрик на основе реализованного PnL ──
        # (не зависит от того, сколько маржи заморожено в открытых позициях)
        daily_pnl = session_pnl
        daily_pnl_pct = daily_pnl / max(self.daily_stats.starting_balance, 1)

        # Drawdown считаем от пика реализованного баланса
        realized_balance = self.daily_stats.starting_balance + session_pnl
        if realized_balance > self.peak_balance:
            self.peak_balance = realized_balance

        drawdown = self.peak_balance - realized_balance
        drawdown_pct = drawdown / max(self.peak_balance, 1)

        # ── Проверка лимитов ──
        if self.daily_stats.blocked:
            return RiskReport(
                can_trade=False,
                reason=f"Daily loss limit reached. Resume tomorrow.",
                daily_pnl_pct=daily_pnl_pct,
                drawdown_pct=drawdown_pct,
                daily_stats=self.daily_stats,
            )

        if daily_pnl_pct < -self.cfg.max_daily_loss_pct:
            self.daily_stats.blocked = True
            logger.warning(
                f"[RISK] Daily loss limit hit: {daily_pnl_pct*100:.2f}% "
                f"(limit: {self.cfg.max_daily_loss_pct*100:.0f}%)"
            )
            return RiskReport(
                can_trade=False,
                reason=f"Daily loss {daily_pnl_pct*100:.2f}% exceeded limit",
                daily_pnl_pct=daily_pnl_pct,
                drawdown_pct=drawdown_pct,
                daily_stats=self.daily_stats,
            )

        if drawdown_pct > self.cfg.max_drawdown_pct:
            logger.warning(
                f"[RISK] Max drawdown hit: {drawdown_pct*100:.2f}% "
                f"(limit: {self.cfg.max_drawdown_pct*100:.0f}%)"
            )
            return RiskReport(
                can_trade=False,
                reason=f"Drawdown {drawdown_pct*100:.2f}% exceeded limit",
                daily_pnl_pct=daily_pnl_pct,
                drawdown_pct=drawdown_pct,
                daily_stats=self.daily_stats,
            )

        return RiskReport(
            can_trade=True,
            reason="OK",
            daily_pnl_pct=daily_pnl_pct,
            drawdown_pct=drawdown_pct,
            daily_stats=self.daily_stats,
        )

    def register_trade(
        self,
        side: str,
        entry_price: float,
        exit_price: float,
        amount: float,
        strategy: str,
    ) -> Dict:
        """
        Регистрирует завершённую сделку.
        Рассчитывает комиссию системы.
        Возвращает итоговый результат.
        """
        if side == "long":
            gross_pnl = (exit_price - entry_price) * amount
        else:
            gross_pnl = (entry_price - exit_price) * amount

        # Комиссия биржи
        exchange_commission = abs(gross_pnl) * self.cfg.commission_rate

        # Комиссия системы (только с прибыли)
        system_commission = 0.0
        if gross_pnl > 0:
            system_commission = gross_pnl * self.commission_pct

        net_pnl = gross_pnl - exchange_commission - system_commission

        trade = {
            "timestamp": time.time(),
            "strategy": strategy,
            "side": side,
            "entry": entry_price,
            "exit": exit_price,
            "amount": amount,
            "gross_pnl": round(gross_pnl, 4),
            "exchange_commission": round(exchange_commission, 4),
            "system_commission": round(system_commission, 4),
            "net_pnl": round(net_pnl, 4),
        }
        self.trade_history.append(trade)

        self.daily_stats.trade_count += 1
        self.daily_stats.pnl += net_pnl
        self.daily_stats.commission_paid += system_commission
        if net_pnl > 0:
            self.daily_stats.win_count += 1

        logger.info(
            f"[RISK] Trade registered | {strategy} {side.upper()} | "
            f"Gross={gross_pnl:.4f} | Commission={exchange_commission:.4f} | "
            f"System fee={system_commission:.4f} | Net={net_pnl:.4f}"
        )
        return trade

    # ──────────────────────────────────────────
    #  Статистика
    # ──────────────────────────────────────────

    def get_session_stats(self) -> Dict:
        """Итоговая статистика сессии"""
        trades = self.trade_history
        if not trades:
            return {"message": "No trades yet"}

        gross_pnl = sum(t["gross_pnl"] for t in trades)
        net_pnl   = sum(t["net_pnl"]   for t in trades)
        sys_fees  = sum(t["system_commission"] for t in trades)
        wins      = sum(1 for t in trades if t["net_pnl"] > 0)
        winrate   = wins / len(trades) * 100

        runtime_h = (time.time() - self.session_start) / 3600

        return {
            "total_trades": len(trades),
            "win_rate": f"{winrate:.1f}%",
            "gross_pnl": round(gross_pnl, 4),
            "net_pnl": round(net_pnl, 4),
            "system_fees_collected": round(sys_fees, 4),
            "runtime_hours": round(runtime_h, 2),
            "daily_stats": {
                "pnl": round(self.daily_stats.pnl, 4),
                "trades": self.daily_stats.trade_count,
                "wins": self.daily_stats.win_count,
                "commission_collected": round(self.daily_stats.commission_paid, 4),
            },
        }

    def get_commission_report(self) -> Dict:
        """Отчёт по комиссии системы (монетизация)"""
        profitable = [t for t in self.trade_history if t["gross_pnl"] > 0]
        total_sys  = sum(t["system_commission"] for t in profitable)
        total_user = sum(t["net_pnl"] for t in self.trade_history)

        return {
            "system_commission_rate": f"{self.commission_pct*100:.0f}%",
            "total_system_income": round(total_sys, 4),
            "total_user_net_pnl": round(total_user, 4),
            "profitable_trades": len(profitable),
        }

    # ──────────────────────────────────────────
    #  Внутренние методы
    # ──────────────────────────────────────────

    def _today(self) -> str:
        from datetime import date
        return str(date.today())

    def _refresh_daily(self, balance: float):
        """Сбрасывает дневную статистику при смене дня"""
        today = self._today()
        if self.daily_stats.date != today:
            logger.info(f"[RISK] New day: {today}. Resetting daily stats.")
            self.daily_stats = DailyStats(
                date=today,
                starting_balance=balance,
                current_balance=balance,
            )
        self.daily_stats.current_balance = balance
