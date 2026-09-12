#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
crypto_check.py – Live-Daten-Modul für die Chart-Analyse
=========================================================
Ruft OHNE API-Key ab:
  - Kurs + 24h-Änderung      (Coinbase Exchange, öffentlich)
  - Funding Rate + Open Interest
      Reihenfolge: Kraken Futures -> Hyperliquid -> Bybit -> Binance
      (Kraken/Hyperliquid funktionieren auch von GitHub-US-Runnern;
       Bybit/Binance sperren US-IPs -> Fallback, lokal nutzbar)
  - Long/Short-Ratio         (Binance Futures, öffentlich; US-geblockt -> n/a auf GH)
  - Fear & Greed Index       (alternative.me, öffentlich)
  - BTC-Kontext (Kurs, Funding, Dominanz falls erreichbar)

NUTZUNG:
  python3 crypto_check.py AERO
  python3 crypto_check.py XRP
  python3 crypto_check.py BTC

Nur Python-Standardbibliothek -> keine Installation noetig.
"""

import sys
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

UA = {"User-Agent": "crypto-check/1.0",
      "Content-Type": "application/json"}


def get(url, params=None, timeout=12):
    if params:
        from urllib.parse import urlencode
        url += "?" + urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def post(url, payload, timeout=12):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers=UA, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
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


# ---------- Derivatsdaten: mehrere Quellen der Reihe nach ----------

def kraken_futures(sym):
    """Kraken Futures v3 Tickers - US-kompatibel, kein Key."""
    d = get("https://futures.kraken.com/derivatives/api/v3/tickers")
    if not d or d.get("result") != "success":
        return None
    target = f"PF_{sym}USD"
    for t in d.get("tickers", []):
        if t.get("symbol") == target:
            return {"funding": float(t["fundingRate"]) * 100,
                    "oi": t.get("openInterest"),
                    "src": "Kraken Futures"}
    return None


def hyperliquid(sym):
    """Hyperliquid metaAndAssetCtxs - permissionless, kein Key.
    Achtung: Funding ist STUENDLICH -> hier auf 8h hochgerechnet."""
    d = post("https://api.hyperliquid.xyz/info", {"type": "metaAndAssetCtxs"})
    if not d or len(d) < 2:
        return None
    universe, ctxs = d[0]["universe"], d[1]
    for i, asset in enumerate(universe):
        if asset.get("name", "").upper() == sym:
            c = ctxs[i]
            return {"funding": float(c["funding"]) * 8 * 100,  # 8h-aequivalent
                    "oi": c.get("openInterest"),
                    "src": "Hyperliquid (8h-aequiv.)"}
    return None


def bybit_linear(sym):
    d = get("https://api.bybit.com/v5/market/tickers",
            {"category": "linear", "symbol": sym})
    try:
        t = d["result"]["list"][0]
        return {"funding": float(t["fundingRate"]) * 100,
                "oi": t.get("openInterest"),
                "src": "Bybit"}
    except Exception:
        return None


def binance_funding(sym):
    d = get("https://fapi.binance.com/fapi/v1/premiumIndex", {"symbol": sym})
    try:
        return {"funding": float(d["lastFundingRate"]) * 100,
                "oi": None, "src": "Binance"}
    except Exception:
        return None


def deriv_data(sym):
    for src in (kraken_futures, hyperliquid, bybit_linear, binance_funding):
        r = src(sym)
        if r:
            return r
    return None


def binance_longshort(sym):
    d = get("https://fapi.binance.com/futures/data/globalLongShortAccountRatio",
            {"symbol": sym, "period": "1d", "limit": 1})
    try:
        return float(d[0]["longShortRatio"])
    except Exception:
        return None


def fear_greed():
    d = get("https://api.alternative.me/fng/")
    try:
        x = d["data"][0]
        return {"value": int(x["value"]), "class": x["value_classification"]}
    except Exception:
        return None


def btc_dominance():
    d = get("https://api.coingecko.com/api/v3/global")
    try:
        return float(d["data"]["market_cap_percentage"]["btc"])
    except Exception:
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


def run(symbol, fg_cache):
    sym = symbol.upper().strip()
    print("=" * 58)
    print(f"  LIVE-DATEN: {sym}  |  {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}")
    print("=" * 58)

    spot = coinbase_stats(f"{sym}-USD")
    if spot:
        print(f"\n[1] KURS (Coinbase Spot)")
        print(f"    Aktuell:    {spot['last']:.5g} USD")
        print(f"    24h:        {pct(spot['change'])}   (24h-High {spot['high']} / Low {spot['low']})")
    else:
        print("\n[1] KURS: Coinbase-Daten nicht erreichbar")

    der = deriv_data(sym)
    if der:
        print(f"\n[2] FUNDING + OPEN INTEREST ({der['src']})")
        print(f"    Funding:    {der['funding']:+.4f}%   -> {interpret_funding(der['funding'])}")
        if der.get("oi"):
            print(f"    Open Int.:  {der['oi']}")
    else:
        print(f"\n[2] FUNDING/OI: kein {sym}-Perp auf Kraken/Hyperliquid/Bybit/Binance")

    ls = binance_longshort(f"{sym}USDT")
    if ls:
        tag = "mehr Longs" if ls > 1 else ("mehr Shorts" if ls < 1 else "ausgewogen")
        print(f"\n[3] LONG/SHORT-RATIO (Binance, 1d): {ls:.3f}  ({tag})")
    else:
        print("\n[3] LONG/SHORT-RATIO: n/a (Quelle US-geblockt oder kein Perp)")

    if fg_cache:
        print(f"\n[4] FEAR & GREED INDEX: {fg_cache['value']} ({fg_cache['class']})  -> {interpret_fg(fg_cache['value'])}")
    else:
        print("\n[4] FEAR & GREED: n/a")

    if sym != "BTC":
        print("\n[5] BTC-KONTEXT")
        btc = coinbase_stats("BTC-USD")
        if btc:
            print(f"    BTC 24h:    {pct(btc['change'])}  (Kurs {btc['last']:,.0f} USD)")
        bder = deriv_data("BTC")
        if bder:
            print(f"    BTC Funding: {bder['funding']:+.4f}% ({bder['src']})  -> {interpret_funding(bder['funding'])}")
        dom = btc_dominance()
        if dom:
            print(f"    BTC-Dominanz: {dom:.1f}%  ({'steigend = Alts unter Druck' if dom > 50 else 'Alts haben Raum'})")
        else:
            print("    BTC-Dominanz: n/a (CoinGecko nicht erreichbar)")

    print("\n" + "=" * 58)
    print("  ENDE")
    print("=" * 58)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    fg_cache = fear_greed()  # 1x pro Lauf, gilt fuer alle Coins
    dom_cache = btc_dominance()
    for s in sys.argv[1:]:
        run(s, fg_cache)
        print()
        time.sleep(1)
