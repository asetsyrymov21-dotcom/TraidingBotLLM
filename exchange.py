# ============================================================
#  Smart Adaptive Trading System — exchange.py
#  Подключение к биржам через CCXT (Binance + Bybit)
# ============================================================

import ccxt
import logging
import time
from typing import Optional, List, Dict
from config import UserProfile

logger = logging.getLogger(__name__)


class ExchangeConnector:
    """
    Универсальный коннектор к бирже.
    Поддерживает Binance Futures и Bybit через CCXT.
    """

    def __init__(self, profile: UserProfile):
        self.profile = profile
        self._last_positions_fetch_ok = False
        self.exchange, self.public_exchange = self._init_exchange()
        self._set_leverage()

    # ──────────────────────────────────────────
    #  Инициализация
    # ──────────────────────────────────────────

    def _init_exchange(self):
        name = self.profile.exchange.lower()

        if name == "binance":
            private_exchange = ccxt.binance(
                {
                    "apiKey": self.profile.api_key,
                    "secret": self.profile.api_secret,
                    "enableRateLimit": True,
                    "options": {
                        "defaultType": "future",
                        "adjustForTimeDifference": True,
                        "fetchCurrencies": False,
                    },
                }
            )

            public_exchange = ccxt.binance(
                {
                    "enableRateLimit": True,
                    "options": {
                        "defaultType": "future",
                        "adjustForTimeDifference": True,
                        "fetchCurrencies": False,
                    },
                }
            )

            if self.profile.is_testnet:
                for ex in (private_exchange, public_exchange):
                    ex.urls["api"][
                        "fapiPublic"
                    ] = "https://demo-fapi.binance.com/fapi/v1"
                    ex.urls["api"][
                        "fapiPrivate"
                    ] = "https://demo-fapi.binance.com/fapi/v1"
                    ex.urls["api"][
                        "fapiPublicV2"
                    ] = "https://demo-fapi.binance.com/fapi/v2"
                    ex.urls["api"][
                        "fapiPrivateV2"
                    ] = "https://demo-fapi.binance.com/fapi/v2"
                    ex.urls["api"][
                        "fapiPublicV3"
                    ] = "https://demo-fapi.binance.com/fapi/v3"
                    ex.urls["api"][
                        "fapiPrivateV3"
                    ] = "https://demo-fapi.binance.com/fapi/v3"

                logger.info(
                    f"[{self.profile.user_id}] Binance Futures DEMO mode enabled"
                )

            public_exchange.load_markets()
            logger.info(f"[{self.profile.user_id}] Public markets loaded")
            logger.info(f"[{self.profile.user_id}] Connected to {name.upper()}")
            self._bybit_hedge_mode = False  # Не Bybit
            return private_exchange, public_exchange

        elif name == "bybit":
            exchange = ccxt.bybit(
                {
                    "apiKey": self.profile.api_key,
                    "secret": self.profile.api_secret,
                    "enableRateLimit": True,
                    "options": {
                        "defaultType": "linear",
                        "adjustForTimeDifference": True,
                    },
                }
            )

            if self.profile.is_testnet:
                # Bybit Demo Trading использует отдельный endpoint.
                # options['demo'] = True не работает в ccxt 4.5.x — шаблон {hostname} не раскрывается.
                # Также fetch_currencies() не поддерживается в demo → отключаем.
                exchange.urls["api"]["public"] = "https://api-demo.bybit.com"
                exchange.urls["api"]["private"] = "https://api-demo.bybit.com"
                exchange.has["fetchCurrencies"] = False
                logger.info(f"[{self.profile.user_id}] Bybit Demo Trading mode enabled (api-demo.bybit.com)")

            exchange.load_markets()
            logger.info(f"[{self.profile.user_id}] Connected to {name.upper()}")

            # Определяем и переключаем position mode на One-Way (0).
            # В Hedge Mode (3) SELL без positionIdx возвращает retCode:170131.
            # Если позиции уже открыты — переключение не сработает, но
            # place_market_order всё равно добавит нужный positionIdx.
            self._bybit_hedge_mode = False
            try:
                resp = exchange.privateGetV5PositionSwitchPositionMode({
                    "category": "linear", "coin": "USDT"
                })
                mode = int((resp.get("result") or {}).get("mode", 0))
                if mode == 3:  # BothSide (Hedge)
                    # Пытаемся переключить в One-Way
                    try:
                        exchange.privatePostV5PositionSwitchPositionMode({
                            "category": "linear", "coin": "USDT", "mode": 0
                        })
                        logger.info(f"[{self.profile.user_id}] Bybit: switched to One-Way mode")
                        self._bybit_hedge_mode = False
                    except Exception as sw_err:
                        # Переключение не удалось (открытые позиции?) — остаёмся в Hedge
                        logger.warning(
                            f"[{self.profile.user_id}] Bybit: cannot switch to One-Way "
                            f"(staying in Hedge mode, will use positionIdx): {sw_err}"
                        )
                        self._bybit_hedge_mode = True
                else:
                    logger.info(f"[{self.profile.user_id}] Bybit: One-Way mode confirmed")
            except Exception as e:
                logger.warning(f"[{self.profile.user_id}] Bybit: could not detect position mode: {e}")
                # На всякий случай используем positionIdx (безопасный дефолт)
                self._bybit_hedge_mode = True

            return exchange, exchange

        else:
            raise ValueError(f"Unsupported exchange: {name}. Use 'binance' or 'bybit'.")

    def _set_leverage(self):
        logger.info(f"[{self.profile.user_id}] Skip leverage setup temporarily")
        return

    def set_leverage(self, leverage: int) -> bool:
        """Устанавливает плечо для текущего символа на бирже."""
        try:
            leverage = max(1, min(125, int(leverage)))
            symbol = self.profile.symbol
            if self.profile.exchange.lower() == "binance":
                binance_symbol = symbol.replace("/", "")
                self.exchange.fapiPrivatePostLeverage({
                    "symbol": binance_symbol,
                    "leverage": leverage,
                })
            else:
                # Bybit требует category=linear для фьючерсов
                self.exchange.set_leverage(leverage, symbol, params={"category": "linear"})
            self.profile.leverage = leverage
            logger.info(f"[{self.profile.user_id}] Leverage → x{leverage} ({symbol})")
            return True
        except Exception as e:
            logger.error(f"[{self.profile.user_id}] set_leverage error: {e}")
            return False

    # ──────────────────────────────────────────
    #  Получение данных
    # ──────────────────────────────────────────

    def fetch_ohlcv(self, timeframe: str = "1h", limit: int = 300) -> List:
        """Загружает исторические свечи OHLCV"""
        for attempt in range(3):
            try:
                ohlcv = self.public_exchange.fetch_ohlcv(
                    self.profile.symbol,
                    timeframe=timeframe,
                    limit=limit,
                )
                return ohlcv
            except ccxt.NetworkError as e:
                logger.warning(f"Network error (attempt {attempt+1}): {e}")
                time.sleep(2**attempt)
            except Exception as e:
                logger.error(f"fetch_ohlcv error: {e}")
                raise
        return []

    def fetch_ticker(self) -> Dict:
        """Текущая цена и объём"""
        return self.public_exchange.fetch_ticker(self.profile.symbol)

    def fetch_balance(self) -> Dict:
        """Баланс аккаунта"""
        if self.profile.exchange.lower() == "binance":
            balances = self.exchange.fapiPrivateV2GetBalance()
            usdt_row = next((x for x in balances if x.get("asset") == "USDT"), None)

            if not usdt_row:
                return {"total": 0.0, "free": 0.0, "used": 0.0}

            total = float(usdt_row.get("balance", 0))
            free = float(usdt_row.get("availableBalance", 0))
            used = total - free

            return {
                "total": total,
                "free": free,
                "used": used,
            }

        balance = self.exchange.fetch_balance()
        usdt = balance.get("USDT", {})

        # Bybit Unified Account возвращает total = equity (walletBalance + unrealizedPnL).
        # Это вызывает скачки баланса при открытых позициях.
        # Вытаскиваем стабильный walletBalance из raw-ответа.
        wallet_balance: float = 0.0
        try:
            info = balance.get("info", {})
            for account in (info.get("result") or {}).get("list", []):
                for coin_data in account.get("coin", []):
                    if coin_data.get("coin") == "USDT":
                        wb = coin_data.get("walletBalance")
                        if wb:
                            wallet_balance = float(wb)
                        break
                if wallet_balance:
                    break
        except Exception:
            pass

        total = wallet_balance if wallet_balance > 0 else float(usdt.get("total", 0))
        free_val = float(usdt.get("free", 0))

        return {
            "total": total,       # walletBalance — стабильный (без нереализованного PnL)
            "free": free_val,     # availableBalance — для расчёта размера позиции
            "used": max(0.0, total - free_val),
        }

    def fetch_positions(self) -> List[Dict]:
        """Открытые позиции"""
        try:
            if self.profile.exchange.lower() == "bybit":
                symbol_id = self.profile.symbol.replace("/", "")
                resp = self.exchange.privateGetV5PositionList({
                    "category": "linear",
                    "symbol": symbol_id,
                })
                raw_positions = (resp.get("result") or {}).get("list") or []
                positions = []
                for item in raw_positions:
                    contracts = float(item.get("size") or 0)
                    if contracts == 0:
                        continue
                    side_raw = (item.get("side") or "").lower()
                    side = "long" if side_raw == "buy" else "short" if side_raw == "sell" else side_raw
                    positions.append({
                        "symbol": self.profile.symbol,
                        "side": side,
                        "contracts": contracts,
                        "entryPrice": float(item.get("avgPrice") or 0),
                        "unrealizedPnl": float(item.get("unrealisedPnl") or 0),
                        "info": item,
                    })
                self._last_positions_fetch_ok = True
                return positions

            positions = self.exchange.fetch_positions([self.profile.symbol])
            self._last_positions_fetch_ok = True
            return [p for p in positions if float(p.get("contracts", 0)) != 0]
        except Exception as e:
            self._last_positions_fetch_ok = False
            logger.error(f"fetch_positions error: {e}")
            return []

    def fetch_open_orders(self) -> List[Dict]:
        """Открытые ордера"""
        try:
            return self.exchange.fetch_open_orders(self.profile.symbol)
        except Exception as e:
            logger.error(f"fetch_open_orders error: {e}")
            return []

    # ──────────────────────────────────────────
    #  Размещение ордеров
    # ──────────────────────────────────────────

    def place_market_order(
        self,
        side: str,
        amount: float,
        reduce_only: bool = False,
    ) -> Optional[Dict]:
        """Маркет-ордер"""
        try:
            side = side.lower()

            # Нормализация направлений стратегий -> CCXT/Binance
            if side == "long":
                side = "buy"
            elif side == "short":
                side = "sell"

            logger.info(
                f"[{self.profile.user_id}] place_market_order start | "
                f"exchange={self.profile.exchange} testnet={self.profile.is_testnet} "
                f"symbol={self.profile.symbol} side={side} amount={amount} reduce_only={reduce_only}"
            )

            if self.profile.exchange.lower() == "binance":
                logger.info(
                    f"[{self.profile.user_id}] Binance order urls | "
                    f"fapiPrivate={self.exchange.urls['api'].get('fapiPrivate')} "
                    f"fapiPrivateV2={self.exchange.urls['api'].get('fapiPrivateV2')} "
                    f"fapiPrivateV3={self.exchange.urls['api'].get('fapiPrivateV3')}"
                )

                binance_symbol = self.profile.symbol.replace("/", "")
                # Используем amount_to_precision чтобы соблюсти step size символа
                try:
                    quantity = self.public_exchange.amount_to_precision(
                        self.profile.symbol, amount
                    )
                except Exception:
                    quantity = f"{amount:.3f}"

                params = {
                    "symbol": binance_symbol,
                    "side": side.upper(),
                    "type": "MARKET",
                    "quantity": quantity,
                }

                if reduce_only:
                    params["reduceOnly"] = "true"

                logger.info(
                    f"[{self.profile.user_id}] Binance raw order params={params}"
                )

                order = self.exchange.fapiPrivatePostOrder(params)

                logger.info(
                    f"[{self.profile.user_id}] raw market order accepted | "
                    f"orderId={order.get('orderId')} status={order.get('status')} "
                    f"executedQty={order.get('executedQty')} avgPrice={order.get('avgPrice')}"
                )

                logger.info(
                    f"[{self.profile.user_id}] MARKET {side.upper()} {amount} "
                    f"{self.profile.symbol} | raw_response={order}"
                )
                return order

            params = {}
            if reduce_only:
                params["reduceOnly"] = True

            if self.profile.exchange.lower() == "bybit":
                hedge = getattr(self, "_bybit_hedge_mode", False)
                if hedge:
                    # Hedge Mode: нужно явно указывать positionIdx
                    # open long (buy)  → 1, open short (sell) → 2
                    # close long (sell reduce) → 1, close short (buy reduce) → 2
                    if not reduce_only:
                        params["positionIdx"] = 1 if side == "buy" else 2
                    else:
                        params["positionIdx"] = 1 if side == "sell" else 2
                else:
                    # One-Way Mode: positionIdx=0 (или не передаём — работает без него)
                    params["positionIdx"] = 0

            order = self.exchange.create_order(
                symbol=self.profile.symbol,
                type="market",
                side=side,
                amount=amount,
                params=params,
            )
            order = self._enrich_order_fill(order)
            logger.info(
                f"[{self.profile.user_id}] MARKET {side.upper()} {amount} "
                f"{self.profile.symbol} | id={order.get('id')} "
                f"avg={order.get('average')} filled={order.get('filled')} fee={order.get('fee')}"
            )
            return order

        except Exception as e:
            err_str = str(e)
            # Binance -2022: ReduceOnly Order is rejected
            # Позиция уже закрыта на бирже (TP/SL/ликвидация сработали раньше бота)
            # Считаем это успехом — бот обновит своё внутреннее состояние корректно
            if reduce_only and ("-2022" in err_str or "ReduceOnly Order is rejected" in err_str):
                logger.warning(
                    f"[{self.profile.user_id}] ReduceOnly rejected (-2022) — "
                    f"позиция уже закрыта на бирже ({side} {amount} {self.profile.symbol}). "
                    f"Считаем закрытой."
                )
                return {"orderId": "already_closed", "status": "FILLED", "executedQty": str(amount)}
            logger.error(f"place_market_order error ({side} {amount}): {e}")
            return None

    def _enrich_order_fill(self, order: Dict) -> Dict:
        """Дочитывает fill/fee для market-order, если биржа не отдала их сразу."""
        order_id = order.get("id") or order.get("orderId")
        if not order_id:
            return order

        enriched = dict(order)

        try:
            time.sleep(0.3)
            fetched = self.exchange.fetch_order(order_id, self.profile.symbol)
            for key in ("average", "filled", "fee", "fees", "cost", "price"):
                if fetched.get(key) not in (None, "", 0):
                    enriched[key] = fetched.get(key)
            if fetched.get("info"):
                info = dict(enriched.get("info") or {})
                info.update(fetched.get("info") or {})
                enriched["info"] = info
        except Exception as e:
            logger.debug(f"fetch_order enrich failed for {order_id}: {e}")

        try:
            trades = self.exchange.fetch_my_trades(self.profile.symbol, None, 20, {"orderId": order_id})
            if trades:
                filled = sum(float(t.get("amount") or 0) for t in trades)
                cost = sum(float(t.get("cost") or 0) for t in trades)
                if filled > 0:
                    enriched["filled"] = filled
                    enriched["average"] = cost / filled if cost > 0 else enriched.get("average")

                fees = []
                fee_total = 0.0
                for trade in trades:
                    fee = trade.get("fee")
                    if isinstance(fee, dict):
                        fees.append(fee)
                        try:
                            fee_total += float(fee.get("cost") or 0)
                        except (TypeError, ValueError):
                            pass
                if fees:
                    enriched["fees"] = fees
                    enriched["fee"] = {"cost": fee_total, "currency": fees[0].get("currency")}
        except Exception as e:
            logger.debug(f"fetch_my_trades enrich failed for {order_id}: {e}")

        return enriched

    def place_limit_order(
        self,
        side: str,
        amount: float,
        price: float,
        reduce_only: bool = False,
    ) -> Optional[Dict]:
        """Лимитный ордер"""
        try:
            side = side.lower()

            # Нормализация направлений стратегий -> CCXT/Binance
            if side == "long":
                side = "buy"
            elif side == "short":
                side = "sell"

            params = {}
            if reduce_only:
                params["reduceOnly"] = True

            order = self.exchange.create_order(
                symbol=self.profile.symbol,
                type="limit",
                side=side,
                amount=amount,
                price=price,
                params=params,
            )
            logger.info(
                f"[{self.profile.user_id}] LIMIT {side.upper()} {amount} @ {price} "
                f"{self.profile.symbol} | id={order.get('id')}"
            )
            return order
        except Exception as e:
            logger.error(f"place_limit_order error ({side} {amount} @ {price}): {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        """Отмена ордера"""
        try:
            self.exchange.cancel_order(order_id, self.profile.symbol)
            logger.info(f"[{self.profile.user_id}] Cancelled order {order_id}")
            return True
        except Exception as e:
            logger.error(f"cancel_order error ({order_id}): {e}")
            return False

    def cancel_all_orders(self) -> int:
        """Отмена всех открытых ордеров. Возвращает кол-во отменённых."""
        orders = self.fetch_open_orders()
        cancelled = 0
        for o in orders:
            if self.cancel_order(o["id"]):
                cancelled += 1
        return cancelled

    def close_all_positions(self) -> bool:
        """Принудительно закрыть все открытые позиции маркет-ордером"""
        positions = self.fetch_positions()
        if not positions:
            return True

        success = True
        for pos in positions:
            side = pos.get("side", "")
            contracts = abs(float(pos.get("contracts", 0)))
            if contracts == 0:
                continue

            close_side = "sell" if side == "long" else "buy"
            order = self.place_market_order(close_side, contracts, reduce_only=True)
            if not order:
                success = False

        return success

    # ──────────────────────────────────────────
    #  Вычисление размера позиции
    # ──────────────────────────────────────────

    def calc_position_size(self, pct_of_balance: float, price: float) -> float:
        """
        Расчёт размера позиции с учётом precision конкретного символа.
        Использует amount_to_precision чтобы не получить -1111 от Binance.
        """
        balance = self.fetch_balance()
        usdt_free = balance["free"]
        balance_base = usdt_free

        custom_config = self.profile.custom_config or {}
        virtual_balance = custom_config.get("virtual_balance_usdt")
        if virtual_balance is not None:
            try:
                virtual_balance = float(virtual_balance)
                if virtual_balance > 0:
                    balance_base = min(usdt_free, virtual_balance)
            except (TypeError, ValueError):
                logger.warning(
                    f"[{self.profile.user_id}] invalid virtual_balance_usdt={virtual_balance}"
                )

        logger.info(
            f"[{self.profile.user_id}] calc_position_size | "
            f"free={usdt_free} balance_base={balance_base} pct={pct_of_balance} "
            f"leverage={self.profile.leverage} price={price}"
        )

        if balance_base <= 0 or price <= 0:
            logger.warning(
                f"[{self.profile.user_id}] calc_position_size -> 0 "
                f"(balance_base={balance_base}, price={price})"
            )
            return 0.0

        usdt_amount = balance_base * pct_of_balance * self.profile.leverage
        contracts_raw = usdt_amount / price

        # Округляем по правилам биржи для данного символа (step size)
        # Это предотвращает ошибку -1111 "Precision is over the maximum defined"
        try:
            contracts_str = self.public_exchange.amount_to_precision(
                self.profile.symbol, contracts_raw
            )
            contracts = float(contracts_str)
        except Exception:
            # Fallback: 3 знака (подходит для BTC/ETH, может не подойти для других)
            contracts = round(contracts_raw, 3)

        if contracts <= 0:
            logger.warning(
                f"[{self.profile.user_id}] calc_position_size -> 0 "
                f"(usdt_amount={usdt_amount}, contracts={contracts})"
            )
            return 0.0

        logger.info(
            f"[{self.profile.user_id}] calc_position_size -> {contracts} "
            f"(raw={contracts_raw:.6f}, symbol={self.profile.symbol})"
        )
        return contracts
