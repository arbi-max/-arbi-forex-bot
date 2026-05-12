import yfinance as yf
import pandas as pd
import numpy as np
import json

# =========================================
# CONFIG
# =========================================

SYMBOL = "EURUSD=X"

INITIAL_BALANCE = 10000

RISK_PERCENT = 1.0        # Risque 1% du capital par trade (dynamique)
RR_RATIO = 2.0            # Risk/Reward ratio
SPREAD_PIPS = 1.5         # Spread EUR/USD en pips
PIP_VALUE = 0.0001        # 1 pip = 0.0001 pour EUR/USD
SCORE_MIN = 4             # Score minimum abaissé à 4 (au lieu de 6)

# =========================================
# DOWNLOAD DATA — 15M + 1H (HTF filter)
# =========================================

df_15m = yf.download(
    SYMBOL,
    interval="15m",
    period="60d",
    auto_adjust=True
)

df_1h = yf.download(
    SYMBOL,
    interval="1h",
    period="60d",
    auto_adjust=True
)

# =========================================
# CLEAN DATA
# =========================================

df_15m.dropna(inplace=True)
df_1h.dropna(inplace=True)

if isinstance(df_15m.columns, pd.MultiIndex):
    df_15m.columns = df_15m.columns.get_level_values(0)

if isinstance(df_1h.columns, pd.MultiIndex):
    df_1h.columns = df_1h.columns.get_level_values(0)

# =========================================
# INDICATORS — 15M
# =========================================

df_15m["EMA20"] = df_15m["Close"].ewm(span=20).mean()
df_15m["EMA50"] = df_15m["Close"].ewm(span=50).mean()
df_15m["EMA200"] = df_15m["Close"].ewm(span=200).mean()

delta = df_15m["Close"].diff()
gain = delta.clip(lower=0)
loss = -delta.clip(upper=0)
avg_gain = gain.rolling(14).mean()
avg_loss = loss.rolling(14).mean()
rs = avg_gain / avg_loss
df_15m["RSI"] = 100 - (100 / (1 + rs))

ema12 = df_15m["Close"].ewm(span=12).mean()
ema26 = df_15m["Close"].ewm(span=26).mean()
df_15m["MACD"] = ema12 - ema26

high_low = df_15m["High"] - df_15m["Low"]
high_close = abs(df_15m["High"] - df_15m["Close"].shift())
low_close = abs(df_15m["Low"] - df_15m["Close"].shift())
ranges = pd.concat([high_low, high_close, low_close], axis=1)
true_range = ranges.max(axis=1)
df_15m["ATR"] = true_range.rolling(14).mean()

df_15m["HH"] = df_15m["High"] > df_15m["High"].shift(1)
df_15m["LL"] = df_15m["Low"] < df_15m["Low"].shift(1)

# =========================================
# INDICATORS — 1H (HTF trend filter)
# =========================================

df_1h["EMA50_1h"] = df_1h["Close"].ewm(span=50).mean()
df_1h["EMA200_1h"] = df_1h["Close"].ewm(span=200).mean()

df_15m.dropna(inplace=True)
df_1h.dropna(inplace=True)

# =========================================
# BACKTEST VARIABLES
# =========================================

balance = INITIAL_BALANCE
peak_balance = balance
max_drawdown = 0
equity_curve = [balance]
trades = []
wins = 0
losses = 0
breakevens = 0

spread = SPREAD_PIPS * PIP_VALUE

# =========================================
# HELPER — GET 1H TREND AT TIME T
# =========================================

def get_htf_trend(timestamp):
    """Retourne 'bull', 'bear' ou 'neutral' selon la tendance H1"""
    past_1h = df_1h[df_1h.index <= timestamp]
    if len(past_1h) == 0:
        return "neutral"
    last = past_1h.iloc[-1]
    if last["EMA50_1h"] > last["EMA200_1h"]:
        return "bull"
    elif last["EMA50_1h"] < last["EMA200_1h"]:
        return "bear"
    return "neutral"

# =========================================
# HELPER — RISK DYNAMIQUE
# =========================================

def calc_risk_reward(balance, entry, sl, rr=RR_RATIO):
    risk_amount = balance * (RISK_PERCENT / 100)
    risk_pips = abs(entry - sl)
    reward_pips = risk_pips * rr
    return risk_amount, risk_amount * rr, reward_pips

# =========================================
# BACKTEST LOOP
# =========================================

for i in range(200, len(df_15m) - 20):

    current = df_15m.iloc[i]
    timestamp = df_15m.index[i]

    # =====================================
    # CORRECTION LOOK-AHEAD :
    # Entrée à l'OPEN de la bougie suivante
    # =====================================
    next_candle = df_15m.iloc[i + 1]
    entry_price = float(next_candle["Open"])

    # =====================================
    # SESSION FILTER — London + NY
    # =====================================

    hour = timestamp.hour
    if hour < 7 or hour > 17:
        continue

    # =====================================
    # EMA200 DISTANCE FILTER
    # =====================================

    ema_distance = abs(current["Close"] - current["EMA200"])
    if ema_distance < current["ATR"] * 0.5:
        continue

    # =====================================
    # HTF TREND FILTER (H1)
    # =====================================

    htf_trend = get_htf_trend(timestamp)

    score_buy = 0
    score_sell = 0
    reasons_buy = []
    reasons_sell = []

    # =====================================
    # EMA TREND
    # =====================================

    if current["EMA20"] > current["EMA50"]:
        score_buy += 2
        reasons_buy.append("EMA20 > EMA50")

    if current["EMA20"] < current["EMA50"]:
        score_sell += 2
        reasons_sell.append("EMA20 < EMA50")

    # =====================================
    # EMA200 FILTER
    # =====================================

    if current["Close"] > current["EMA200"]:
        score_buy += 1
        reasons_buy.append("Above EMA200")

    if current["Close"] < current["EMA200"]:
        score_sell += 1
        reasons_sell.append("Below EMA200")

    # =====================================
    # RSI
    # =====================================

    if current["RSI"] > 55:
        score_buy += 1
        reasons_buy.append("RSI bullish")

    if current["RSI"] < 45:
        score_sell += 1
        reasons_sell.append("RSI bearish")

    # =====================================
    # MACD
    # =====================================

    if current["MACD"] > 0:
        score_buy += 1
        reasons_buy.append("MACD bullish")

    if current["MACD"] < 0:
        score_sell += 1
        reasons_sell.append("MACD bearish")

    # =====================================
    # MARKET STRUCTURE
    # =====================================

    if current["HH"]:
        score_buy += 1
        reasons_buy.append("Higher High")

    if current["LL"]:
        score_sell += 1
        reasons_sell.append("Lower Low")

    # =====================================
    # BUY SETUP
    # =====================================

    if (
        score_buy >= SCORE_MIN
        and score_buy > score_sell
        and htf_trend == "bull"          # HTF doit être haussier
    ):
        entry = entry_price + spread     # Spread appliqué à l'achat

        sl = entry - (float(current["ATR"]) * 1.5)
        risk_pips = entry - sl
        tp = entry + (risk_pips * RR_RATIO)

        risk_amount, reward_amount, _ = calc_risk_reward(balance, entry, sl)

        result = None
        profit = 0

        for j in range(i + 2, i + 21):
            future = df_15m.iloc[j]

            if future["Low"] <= sl:
                result = "LOSS"
                profit = -risk_amount
                losses += 1
                break

            if future["High"] >= tp:
                result = "WIN"
                profit = reward_amount
                wins += 1
                break

        if result is None:
            result = "BREAKEVEN"
            profit = 0
            breakevens += 1

        balance += profit
        equity_curve.append(round(balance, 2))

        if balance > peak_balance:
            peak_balance = balance
        drawdown = peak_balance - balance
        if drawdown > max_drawdown:
            max_drawdown = drawdown

        trades.append({
            "date": str(timestamp),
            "symbol": "EURUSD",
            "signal": "BUY",
            "score": score_buy,
            "htf_trend": htf_trend,
            "entry": round(entry, 5),
            "sl": round(sl, 5),
            "tp": round(tp, 5),
            "risk_$": round(risk_amount, 2),
            "reward_$": round(reward_amount, 2),
            "profit": round(profit, 2),
            "result": result,
            "reasons": reasons_buy
        })

    # =====================================
    # SELL SETUP
    # =====================================

    elif (
        score_sell >= SCORE_MIN
        and score_sell > score_buy
        and htf_trend == "bear"          # HTF doit être baissier
    ):
        entry = entry_price - spread     # Spread appliqué à la vente

        sl = entry + (float(current["ATR"]) * 1.5)
        risk_pips = sl - entry
        tp = entry - (risk_pips * RR_RATIO)

        risk_amount, reward_amount, _ = calc_risk_reward(balance, entry, sl)

        result = None
        profit = 0

        for j in range(i + 2, i + 21):
            future = df_15m.iloc[j]

            if future["High"] >= sl:
                result = "LOSS"
                profit = -risk_amount
                losses += 1
                break

            if future["Low"] <= tp:
                result = "WIN"
                profit = reward_amount
                wins += 1
                break

        if result is None:
            result = "BREAKEVEN"
            profit = 0
            breakevens += 1

        balance += profit
        equity_curve.append(round(balance, 2))

        if balance > peak_balance:
            peak_balance = balance
        drawdown = peak_balance - balance
        if drawdown > max_drawdown:
            max_drawdown = drawdown

        trades.append({
            "date": str(timestamp),
            "symbol": "EURUSD",
            "signal": "SELL",
            "score": score_sell,
            "htf_trend": htf_trend,
            "entry": round(entry, 5),
            "sl": round(sl, 5),
            "tp": round(tp, 5),
            "risk_$": round(risk_amount, 2),
            "reward_$": round(reward_amount, 2),
            "profit": round(profit, 2),
            "result": result,
            "reasons": reasons_sell
        })

# =========================================
# RESULTS
# =========================================

total_trades = wins + losses + breakevens
winrate = round((wins / (wins + losses)) * 100, 2) if (wins + losses) > 0 else 0

report = {
    "stats": {
        "winrate": winrate,
        "balance_initial": INITIAL_BALANCE,
        "balance_final": round(balance, 2),
        "pnl_total": round(balance - INITIAL_BALANCE, 2),
        "max_drawdown": round(max_drawdown, 2),
        "wins": wins,
        "losses": losses,
        "breakevens": breakevens,
        "total_trades": total_trades,
        "risk_per_trade_%": RISK_PERCENT,
        "spread_pips": SPREAD_PIPS
    },
    "equity_curve": equity_curve,
    "trades": trades
}

with open("report.json", "w") as f:
    json.dump(report, f, indent=4)

print("====================================")
print("BACKTEST V2 TERMINÉ")
print("====================================")
print(f"Trades       : {total_trades}")
print(f"Wins         : {wins}")
print(f"Losses       : {losses}")
print(f"Breakevens   : {breakevens}")
print(f"Winrate      : {winrate} %")
print(f"Balance init : {INITIAL_BALANCE} $")
print(f"Balance finale: {round(balance, 2)} $")
print(f"PnL total    : {round(balance - INITIAL_BALANCE, 2)} $")
print(f"Max Drawdown : {round(max_drawdown, 2)} $")
print("====================================")
