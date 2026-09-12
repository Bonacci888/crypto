#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
crypto_check.py – Live-Daten-Modul für die Chart-Analyse
=========================================================
Ruft OHNE API-Key ab:
  - Kurs + 24h-Änderung      (Coinbase Exchange, öffentlich)
  - Funding Rate + Open Interest (Bybit v5, öffentlich; Fallback Binance)
  - Long/Short-Ratio         (Binance Futures, öffentlich)
  - Fear & Greed Index       (alternative.me, öffentlich)
  - BTC-Kontext (Kurs, Funding, Dominanz falls erreichbar)

NUTZUNG:
  python3 crypto_check.py AERO
  python3 crypto_check.py XRP
  python3 crypto_check.py BTC

Dann den Ausgabe-Block in den Chat kopieren (zusammen mit den Screenshots).
Nur Python-Standardbibliothek -> keine Installation noetig.
"""

import sys
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

UA = {"User-Agent": "crypto-check/1.0"}


def get(url, params=None, timeout=12):
    if params:
        from urllib.parse import urlencode
        url += "?" + urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
        return None


def pct(x):
    try:
        return f"{float(x):+.2f}%"
    except (TypeError, ValueError):
        return "n/a"


def coinbase_stats(product):
    d = get(f"https://api.exchange.coinbase.com/products/{product}/stats")
    if not d or "last" not in d:
        return None
    last, open_ = float(d["last"]), float(d["open"])
    return {"last": last, "open": open_, "change": (last - open_) / open_ * 100,
            "high": d.get("high"), "low": d.get("low"), "volume": d.get("volume")}


def bybit_linear(sym):
    d = get("https://api.bybit.com/v5/market/tickers",
            {"category": "linear", "symbol": sym})
    try:
        t = d["result"]["list"][0]
        return {"funding": float(t["fundingRate"]) * 100,
                "oi": t.get("openInterest"),
                "oi_value": t.get("openInterestValue"),
                "price24h": float(t["price24hPcnt"])}
    except (TypeError, KeyError, IndexError):
        return None


def binance_funding(sym):
    d = get("https://fapi.binance.com/fapi/v1/premiumIndex", {"symbol": sym})
    try:
        return {"funding": float(d["lastFundingRate"]) * 100}
    except (TypeError, KeyError):
        return None


def binance_longshort(sym):
    d = get("https://fapi.binance.com/futures/data/globalLongShortAccountRatio",
            {"symbol": sym, "period": "1d", "limit": 1})
    try:
        return float(d[0]["longShortRatio"])
    except (TypeError, KeyError, IndexError):
        return None


def fear_greed():
    d = get("https://api.alternative.me/fng/")
    try:
        x = d["data"][0]
        return {"value": int(x["value"]), "class": x["value_classification"]}
    except (TypeError, KeyError, IndexError):
        return None


def btc_dominance():
    d = get("https://api.coingecko.com/api/v3/global")
    try:
        return float(d["data"]["market_cap_percentage"]["btc"])
    except (TypeError, KeyError):
        return None


def interpret_funding(f):
    if f is None:
        return "keine Derivatsdaten gefunden (Coin ggf. nur Spot)"
    if f > 0.05:
        return "ueberoptimistisch -> Kontra-Signal, Vorsicht Longs"
    if f < -0.05:
        return "Panik/Shorts zahlen -> moegliche Bodenbildung"
    return "neutral"


def interpret_fg(v):
    if v >= 75:
        return "Greed -> Korrekturrisiko"
    if v <= 25:
        return "Fear -> Chancenzone (kontraer)"
    return "neutraler Bereich"


def run(symbol):
    sym = symbol.upper().strip()
    print("=" * 58)
    print(f"  LIVE-DATEN: {sym}  |  {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}")
    print("=" * 58)

    # 1) Spot-Kurs (Coinbase)
    spot = coinbase_stats(f"{sym}-USD")
    if spot:
        print(f"\n[1] KURS (Coinbase Spot)")
        print(f"    Aktuell:    {spot['last']:.5g} USD")
        print(f"    24h:        {pct(spot['change'])}   (24h-High {spot['high']} / Low {spot['low']})")
    else:
        print("\n[1] KURS: Coinbase-Daten nicht erreichbar")

    # 2) Funding + OI
    der = bybit_linear(f"{sym}USDT")
    src = "Bybit"
    if not der:
        der = binance_funding(f"{sym}USDT")
        src = "Binance"
    if der:
        print(f"\n[2] FUNDING + OPEN INTEREST ({src})")
        print(f"    Funding:    {der['funding']:+.4f}%   -> {interpret_funding(der['funding'])}")
        if der.get("oi"):
            print(f"    Open Int.:  {der['oi']}  (Wert: {der.get('oi_value', 'n/a')} USD)")
        if der.get("price24h") is not None:
            print(f"    24h (Deriv.): {pct(der['price24h'])}")
    else:
        print(f"\n[2] FUNDING/OI: kein {sym}-Perp auf Bybit/Binance gefunden")

    # 3) Long/Short-Ratio
    ls = binance_longshort(f"{sym}USDT")
    if ls:
        tag = "mehr Longs" if ls > 1 else ("mehr Shorts" if ls < 1 else "ausgewogen")
        print(f"\n[3] LONG/SHORT-RATIO (Binance, 1d): {ls:.3f}  ({tag})")
    else:
        print("\n[3] LONG/SHORT-RATIO: n/a")

    # 4) Fear & Greed
    fg = fear_greed()
    if fg:
        print(f"\n[4] FEAR & GREED INDEX: {fg['value']} ({fg['class']})  -> {interpret_fg(fg['value'])}")
    else:
        print("\n[4] FEAR & GREED: n/a")

    # 5) BTC-Kontext
    print("\n[5] BTC-KONTEXT")
    btc = coinbase_stats("BTC-USD")
    if btc:
        print(f"    BTC 24h:    {pct(btc['change'])}  (Kurs {btc['last']:,.0f} USD)")
    bder = bybit_linear("BTCUSDT")
    if bder:
        print(f"    BTC Funding: {bder['funding']:+.4f}%  -> {interpret_funding(bder['funding'])}")
    dom = btc_dominance()
    if dom:
        print(f"    BTC-Dominanz: {dom:.1f}%  ({'steigend = Alts unter Druck' if dom > 50 else 'Alts haben Raum'})")
    else:
        print("    BTC-Dominanz: n/a (CoinGecko nicht erreichbar)")

    print("\n" + "=" * 58)
    print("  ENDE - Block kopieren + mit Screenshots in den Chat")
    print("=" * 58)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    for s in sys.argv[1:]:
        run(s)
        print()
        time.sleep(1)
