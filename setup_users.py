#!/usr/bin/env python3
from user_manager import UserManager


def safe_add_user(mgr, **kwargs):
    user_id = kwargs["user_id"]
    existing = mgr.get_user(user_id)

    if existing:
        print(f"[SKIP] User '{user_id}' already exists")
        return

    mgr.add_user(**kwargs)
    print(f"[OK] User '{user_id}' added")


def setup_example_users():
    mgr = UserManager(data_dir="data")

    safe_add_user(
        mgr,
        user_id="alice",
        exchange="binance",
        api_key="BINANCE_API_KEY_HERE",
        api_secret="BINANCE_SECRET_HERE",
        # Мультипарный режим: одновременно торгуем BTC, ETH и SOL.
        # deposit_pct делится поровну между всеми парами.
        symbols=["BTC/USDT", "ETH/USDT", "SOL/USDT"],
        top_n_symbols=0,  # 0 = ручной список symbols, >0 = авто топ-N
        leverage=2,
        deposit_pct=0.05,
        commission_pct=0.20,
        is_testnet=True,
    )

    safe_add_user(
        mgr,
        user_id="bob",
        exchange="bybit",
        api_key="BYBIT_API_KEY_HERE",
        api_secret="BYBIT_SECRET_HERE",
        symbol="ETH/USDT",
        leverage=5,
        deposit_pct=0.15,
        commission_pct=0.25,
        is_testnet=True,
        custom_config={
            "tp_pct": 0.025,
            "sl_pct": 0.012,
        },
    )

    safe_add_user(
        mgr,
        user_id="charlie",
        exchange="bybit",
        api_key="BYBIT_API_KEY_2_HERE",
        api_secret="BYBIT_SECRET_2_HERE",
        symbol="BTC/USDT",
        leverage=3,
        deposit_pct=0.10,
        commission_pct=0.20,
        is_testnet=False,
    )

    mgr.print_summary()
    print("Users saved to data/users.json")


if __name__ == "__main__":
    setup_example_users()
