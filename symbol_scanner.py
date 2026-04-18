# ============================================================
#  Smart Adaptive Trading System — symbol_scanner.py
#  Автоматический выбор топ-N пар по объёму с биржи
# ============================================================

import logging
import time
from typing import List, Optional

logger = logging.getLogger(__name__)


class SymbolScanner:
    """
    Сканирует рынок и возвращает топ-N USDT-фьючерсных пар
    по 24-часовому объёму торгов.

    Список обновляется не чаще одного раза в 24 часа.
    При ошибке — возвращает предыдущий кэш (или пустой список).
    """

    REFRESH_INTERVAL = 86400  # 24 часа в секундах

    # Пары, которые исключаем из скана (стейблкоины, деривативы и т.п.)
    BLACKLIST = {
        "USDC/USDT", "BUSD/USDT", "TUSD/USDT", "DAI/USDT",
        "USDP/USDT", "FDUSD/USDT", "USDD/USDT",
    }

    def __init__(
        self,
        exchange_name: str,
        api_key: str,
        api_secret: str,
        is_testnet: bool = False,
        top_n: int = 5,
    ):
        self.exchange_name = exchange_name.lower()
        self.api_key = api_key
        self.api_secret = api_secret
        self.is_testnet = is_testnet
        self.top_n = top_n

        self._cached_symbols: List[str] = []
        self._last_refresh: float = 0.0  # UNIX timestamp последнего обновления
        self._exchange = None

    # ──────────────────────────────────────────
    #  Публичный API
    # ──────────────────────────────────────────

    def get_top_symbols(self) -> List[str]:
        """
        Возвращает топ-N пар по объёму.
        Обновляет список, если прошло больше 24 часов.
        """
        if self._should_refresh():
            self._refresh()
        return list(self._cached_symbols)

    def should_refresh(self) -> bool:
        """Проверяет, нужно ли обновить список пар."""
        return self._should_refresh()

    def force_refresh(self) -> List[str]:
        """Принудительное обновление без учёта таймера."""
        self._refresh()
        return list(self._cached_symbols)

    @property
    def last_refresh_age_hours(self) -> float:
        """Сколько часов прошло с последнего обновления."""
        if self._last_refresh == 0:
            return float("inf")
        return (time.time() - self._last_refresh) / 3600

    # ──────────────────────────────────────────
    #  Внутренние методы
    # ──────────────────────────────────────────

    def _should_refresh(self) -> bool:
        return (time.time() - self._last_refresh) >= self.REFRESH_INTERVAL

    def _get_exchange(self):
        """Ленивая инициализация CCXT-коннектора."""
        if self._exchange is not None:
            return self._exchange

        try:
            import ccxt
        except ImportError:
            raise RuntimeError("ccxt не установлен: pip install ccxt")

        params = {
            "apiKey": self.api_key,
            "secret": self.api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        }

        if self.exchange_name == "binance":
            ex = ccxt.binance(params)
            if self.is_testnet:
                ex.set_sandbox_mode(True)
        elif self.exchange_name == "bybit":
            ex = ccxt.bybit(params)
            if self.is_testnet:
                ex.set_sandbox_mode(True)
        else:
            raise ValueError(f"Неподдерживаемая биржа: {self.exchange_name}")

        self._exchange = ex
        return ex

    def _refresh(self):
        """
        Получает список тикеров с биржи и выбирает топ-N по объёму.
        """
        logger.info(
            f"[SymbolScanner] Обновление топ-{self.top_n} пар "
            f"({self.exchange_name}, testnet={self.is_testnet})..."
        )
        try:
            ex = self._get_exchange()
            tickers = ex.fetch_tickers()

            # Фильтрация: только USDT-фьючи, не в чёрном списке
            candidates = []
            for symbol, ticker in tickers.items():
                if not symbol.endswith("/USDT"):
                    continue
                if symbol in self.BLACKLIST:
                    continue
                vol = ticker.get("quoteVolume") or ticker.get("baseVolume") or 0
                if vol and vol > 0:
                    candidates.append((symbol, float(vol)))

            # Сортировка по объёму убыванию
            candidates.sort(key=lambda x: x[1], reverse=True)
            top = [sym for sym, _ in candidates[: self.top_n]]

            if not top:
                logger.warning("[SymbolScanner] Не удалось получить ни одной пары!")
                return  # Оставляем старый кэш

            self._cached_symbols = top
            self._last_refresh = time.time()

            logger.info(
                f"[SymbolScanner] Топ-{self.top_n} пар: {', '.join(top)} "
                f"(обновлено {time.strftime('%H:%M:%S')})"
            )

        except Exception as e:
            logger.error(f"[SymbolScanner] Ошибка при обновлении пар: {e}")
            if not self._cached_symbols:
                # Если кэш пустой — возвращаем дефолтный список
                self._cached_symbols = ["BTC/USDT", "ETH/USDT", "BNB/USDT"]
                logger.warning(
                    f"[SymbolScanner] Используем резервный список: {self._cached_symbols}"
                )
