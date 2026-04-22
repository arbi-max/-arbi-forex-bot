import requests
import time
from datetime import datetime, timezone

TOKEN = "8636672541:AAElNEq4IKwrRzTLuqoaqttadmkGKAVEVlM"
IDS = ["525011337", "7276558677"]

PAIRS = [
    {"name": "EUR/USD", "kraken": "EURUSD"},
    {"name": "GBP/USD", "kraken": "GBPUSD"},
    {"name": "USD/JPY", "kraken": "USDJPY"},
]

def send(msg):
    for cid in IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                json={"chat_id": cid, "text": msg}, timeout=10)
        except:
            pass
        time.sleep(1)

def candles(pair, interval=60, count=150):
    try:
        r = requests.get("https://api.kraken.com/0/public/OHLC",
            params={"pair": pair, "interval": interval}, timeout=10)
        d = r.json()["result"]
        k = [x for x in d if x != "last"][0]
        data = d[k][-count:]
        return {
            "open":  [float(c[1]) for c in data],
            "high":  [float(c[2]) for c in data],
            "low":   [float(c[3]) for c in data],
            "close": [float(c[4]) for c in data],
            "vol":   [float(c[6]) for c in data],
        }
    except:
        return None

def ema(closes, n):
    if len(closes) < n:
        return closes[-1]
    k = 2/(n+1)
    e = sum(closes[:n])/n
    for p in closes[n:]:
        e = p*k + e*(1-k)
    return e

def rsi(closes, n=14):
    g = l = 0
    for i in range(len(closes)-n, len(closes)):
        d = closes[i]-closes[i-1]
        if d > 0: g += d
        else: l -= d
    rs = g/(l or 0.001)
    return 100 - 100/(1+rs)

def macd(closes):
    return ema(closes, 12) - ema(closes, 26)

def bollinger(closes, n=20):
    s = closes[-n:]
    mid = sum(s)/len(s)
    std = (sum((x-mid)**2 for x in s)/len(s))**0.5
    return mid+2*std, mid-2*std, mid

def stochastic(highs, lows, closes, n=14):
    h = max(highs[-n:])
    l = min(lows[-n:])
    if h == l: return 50
    return 100*(closes[-1]-l)/(h-l)

def atr(highs, lows, closes, n=14):
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i]-lows[i],
                 abs(highs[i]-closes[i-1]),
                 abs(lows[i]-closes[i-1]))
        trs.append(tr)
    return sum(trs[-n:])/n

def is_trading_session():
    hour = datetime.now(timezone.utc).hour
    # Session Londres (07h-16h UTC) + New York (12h-21h UTC)
    london = 7 <= hour < 16
    newyork = 12 <= hour < 21
    return london or newyork

def session_name():
    hour = datetime.now(timezone.utc).hour
    if 7 <= hour < 12: return "Londres"
    if 12 <= hour < 16: return "Londres+NewYork"
    if 16 <= hour < 21: return "New York"
    return "Hors session"

def volume_surge(vols):
    avg = sum(vols[-20:])/20
    return vols[-1] > avg * 1.5

def analyze(pair_name, kraken_pair):
    # H1 data
    d1 = candles(kraken_pair, 60, 150)
    if not d1: return None

    # H4 data (tendance longue)
    d4 = candles(kraken_pair, 240, 100)
    if not d4: return None

    c1 = d1["close"]
    price = c1[-1]

    # Indicateurs H1
    e9   = ema(c1, 9)
    e21  = ema(c1, 21)
    e50  = ema(c1, 50)
    e200 = ema(c1, 100)
    r    = rsi(c1)
    m    = macd(c1)
    bb_u, bb_l, bb_m = bollinger(c1)
    sto  = stochastic(d1["high"], d1["low"], c1)
    atr_val = atr(d1["high"], d1["low"], c1)
    vol_up  = volume_surge(d1["vol"])

    # Tendance H4
    c4   = d4["close"]
    e9_4 = ema(c4, 9)
    e21_4= ema(c4, 21)
    trend_h4 = "BULL" if e9_4 > e21_4 else "BEAR"

    # Croisement EMA H1
    c1_prev = c1[:-1]
    cross_up   = ema(c1_prev, 9) <= ema(c1_prev, 21) and e9 > e21
    cross_down = ema(c1_prev, 9) >= ema(c1_prev, 21) and e9 < e21

    score = 0
    reasons = []

    # 1. RSI
    if r < 30:
        score += 3
        reasons.append("RSI survendu (<30)")
    elif r < 40:
        score += 1
        reasons.append("RSI bas (40)")
    elif r > 70:
        score -= 3
        reasons.append("RSI surachete (>70)")
    elif r > 60:
        score -= 1
        reasons.append("RSI eleve (>60)")

    # 2. EMA alignment H1
    if e9 > e21 > e50:
        score += 2
        reasons.append("EMA alignees hausse")
    elif e9 < e21 < e50:
        score -= 2
        reasons.append("EMA alignees baisse")

    # 3. Tendance H4
    if trend_h4 == "BULL":
        score += 2
        reasons.append("H4 haussier")
    else:
        score -= 2
        reasons.append("H4 baissier")

    # 4. MACD
    if m > 0:
        score += 1
        reasons.append("MACD positif")
    else:
        score -= 1
        reasons.append("MACD negatif")

    # 5. Bollinger
    if price < bb_l:
        score += 2
        reasons.append("Prix sous BB basse")
    elif price > bb_u:
        score -= 2
        reasons.append("Prix sur BB haute")

    # 6. Stochastique
    if sto < 20:
        score += 2
        reasons.append("Stoch survendu (<20)")
    elif sto > 80:
        score -= 2
        reasons.append("Stoch surachete (>80)")

    # 7. Croisement EMA
    if cross_up:
        score += 2
        reasons.append("Croisement EMA BULL")
    elif cross_down:
        score -= 2
        reasons.append("Croisement EMA BEAR")

    # 8. Volume
    if vol_up:
        score += (1 if score > 0 else -1)
        reasons.append("Volume fort")

    # 9. Prix au-dessus EMA200
    if price > e200:
        score += 1
        reasons.append("Au-dessus EMA200")
    else:
        score -= 1
        reasons.append("En-dessous EMA200")

    # Signal
    if score >= 6:
        signal = "ACHAT"
    elif score <= -5:
        signal = "VENTE"
    else:
        signal = "ATTENDRE"

    confidence = min(92, abs(score) * 7 + 30)

    sl = price - atr_val * 1.5 if signal == "ACHAT" else price + atr_val * 1.5
    tp = price + atr_val * 3.0 if signal == "ACHAT" else price - atr_val * 3.0

    return {
        "signal": signal,
        "score": score,
        "confidence": confidence,
        "price": price,
        "rsi": r,
        "stoch": sto,
        "macd": m,
        "trend_h4": trend_h4,
        "session": session_name(),
        "atr": atr_val,
        "sl": sl,
        "tp": tp,
        "reasons": reasons[:5],
    }

last_signals = {}

def check(pair):
    result = analyze(pair["name"], pair["kraken"])
    if not result:
        return

    sig = result["signal"]
    name = pair["name"]
    dec = 3 if "JPY" in name else 5

    if sig != "ATTENDRE" and last_signals.get(name) != sig:
        last_signals[name] = sig
        icon = "BUY" if sig == "ACHAT" else "SELL"

        msg = f"{icon} SIGNAL {sig} — {name}\n"
        msg += "─────────────────────\n"
        msg += f"Prix    : {result['price']:.{dec}f}\n"
        msg += f"SL      : {result['sl']:.{dec}f}\n"
        msg += f"TP      : {result['tp']:.{dec}f}\n"
        msg += f"Ratio   : 1:2\n"
        msg += "─────────────────────\n"
        msg += f"RSI     : {result['rsi']:.1f}\n"
        msg += f"Stoch   : {result['stoch']:.1f}\n"
        msg += f"H4      : {result['trend_h4']}\n"
        msg += f"Session : {result['session']}\n"
        msg += f"Score   : {result['score']}/13\n"
        msg += f"Confiance: {result['confidence']}%\n"
        msg += "─────────────────────\n"
        for r in result["reasons"]:
            msg += f"• {r}\n"
        msg += "\nSignal indicatif — risque 2% max"

        send(msg)
        print(f"Signal: {name} {sig} conf={result['confidence']}%")

# Démarrage
now = datetime.now().strftime("%d/%m %H:%M")
send(f"ARBI BOT PRO DEMARRE — {now}\nSessions: Londres + New York\nPaires: EUR/USD GBP/USD USD/JPY\nAnalyse: H1 + H4 + 9 indicateurs")
print("Bot Pro demarre")

while True:
    if is_trading_session():
        for p in PAIRS:
            try:
                check(p)
            except Exception as e:
                print(f"Erreur {p['name']}: {e}")
            time.sleep(3)
        print(f"Cycle termine - {datetime.now().strftime('%H:%M')}")
    else:
        print(f"Hors session - {datetime.now().strftime('%H:%M')}")
    time.sleep(300)
