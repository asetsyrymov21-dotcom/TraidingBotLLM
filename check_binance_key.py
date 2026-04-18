import ccxt

exchange = ccxt.binance(
    {
        "apiKey": "REMOVED_APIKEY",
        "secret": "REMOVED_SECRET",
        "options": {
            "defaultType": "future",
        },
    }
)

exchange.urls["api"] = {
    "fapiPublic": "https://demo-fapi.binance.com/fapi/v1",
    "fapiPrivate": "https://demo-fapi.binance.com/fapi/v1",
    "fapiPrivateV2": "https://demo-fapi.binance.com/fapi/v2",
}

exchange.verbose = True

print(exchange.fapiPrivateV2GetBalance())
