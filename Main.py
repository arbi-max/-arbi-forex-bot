import requests
import time
from datetime import datetime, timezone, timedelta

TOKEN = "8636672541:AAElNEq4IKwrRzTLuqoaqttadmkGKAVEVlM"
IDS = ["525011337", "7276558677"]

PAIRS = [
    {"name": "EUR/USD", "kraken": "EURUSD"},
    {"name": "GBP/USD", "kraken": "GBPUSD"},
    {"name": "USD/JPY", "kraken": "USDJPY"},
]

# Anti-contradiction : garde le dernier signal par paire
last_signals = {}
open_positions = {}

def send(msg):
    for cid in IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                json={"chat_id": cid, "text": msg}, timeout=10)
        except:
            pass
        time.sleep(1)

# ═══════════════════════════════════
# CALENDRIER ÉCONOMIQUE
# ═══════════════════════════════════
def get_news_events():
    try:
        # ForexFactory RSS feed
        r = requests.get(
            "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
            timeout=10)
        events = r.json()
        high_impact = []
        now = datetime.now(timezone.utc)
        for e in events:
            if e.get("impact") in ["High", "Medium"]:
                try:
                    event_time = datetime.strptime(
                        e["date"], "%Y-%m-%dT%H:%M:%S%z")
                    diff = abs((event_time - now).total_seconds() / 60)
                    if diff <= 45:  # Dans les 45 minutes
                        high_impact.append({
                            "title": e.get("title", ""),
                            "currency": e.get("country", ""),
                            "time": event_time,
                            "impact": e.get("impact", ""),
                            "diff_mins": int(diff)
                        })
                except:
                    pass
        return high_impact
    except:
        return []

def is_news_blocked(pair_name):
    events = get_news_events()
    if not events:
        return False, []

    currencies = []
    if "EUR" in pair_name: currencies += ["EUR", "USD"]
    if "GBP" in pair_name: currencies += ["GBP", "USD"]
    if "JPY" in pair_name: currencies += ["JPY", "USD"]

    blocking = []
    for e in events:
        for cur in currencies:
            if cur.upper() in e["currency"].upper():
                blocking.append(e)
                break

    return len(blocking) > 0, blocking

# ═══════════════════════════════════
# SESSION DE TRADING
# ═══════════════════════════════════
def get_session():
    hour = datetime.now(timezone.utc).hour
    if 7 <= hour < 12:   return "Londres", True
    if 12 <= hour < 16:  return "Londres+NewYork", True
    if 16 <= hour < 21:  return "New York", True
    return "Hors session", False

# ═══════════════════════════════════
# DONNÉES KRAKEN
# ═══════════════════════════════════
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

# ═══════════════════════════════════
# INDICATEURS
# ═══════════════════════════════════
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
    return 100 - 100/(1+g/(l or 0.001))

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

# ═══════════════════════════════════
# ANALYSE PRINCIPALE
# ═══════════════════════════════════
def analyze(pair_name, kraken_pair):
    d1 = candles(kraken_pair, 60, 150)
    d4 = candles(kraken_pair, 240, 100)
    if not d1 or not d4:
        return None

    c1 = d1["close"]
    price = c1[-1]

    e9   = ema(c1, 9)
    e21  = ema(c1, 21)
    e50  = ema(c1, 50)
    e200 = ema(c1, 100)
    r    = rsi(c1)
    m    = macd(c1)
    bb_u, bb_l, bb_m = bollinger(c1)
    sto  = stochastic(d1["high"], d1["low"], c1)
    atr_v = atr(d1["high"], d1["low"], c1)

    c4    = d4["close"]
    e9_4  = ema(c4, 9)
    e21_4 = ema(c4, 21)
    trend_h4 = "BULL" if e9_4 > e21_4 else "BEAR"

    c1_prev = c1[:-1]
    cross_up   = ema(c1_prev, 9) <= ema(c1_prev, 21) and e9 > e21
    cross_down = ema(c1_prev, 9) >= ema(c1_prev, 21) and e9 < e21

    score = 0
    reasons = []

    # RSI
    if r < 30:   score += 3; reasons.append("RSI survendu (<30)")
    elif r < 40: score += 1; reasons.append("RSI bas (<40)")
    elif r > 70: score -= 3; reasons.append("RSI surachete (>70)")
    elif r > 60: score -= 1; reasons.append("RSI eleve (>60)")

    # EMA H1
    if e9 > e21 > e50:   score += 2; reasons.append("EMA alignees hausse")
    elif e9 < e21 < e50: score -= 2; reasons.append("EMA alignees baisse")

    # H4
    if trend_h4 == "BULL": score += 2; reasons.append("H4 haussier")
    else:                  score -= 2; reasons.append("H4 baissier")

    # MACD
    if m > 0: score += 1; reasons.append("MACD positif")
    else:     score -= 1; reasons.append("MACD negatif")

    # Bollinger
    if price < bb_l:   score += 2; reasons.append("Sous BB basse")
    elif price > bb_u: score -= 2; reasons.append("Sur BB haute")

    # Stochastique
    if sto < 20:   score += 2; reasons.append("Stoch survendu")
    elif sto > 80: score -= 2; reasons.append("Stoch surachete")

    # Croisement
    if cross_up:   score += 2; reasons.append("Croisement EMA BULL")
    elif cross_down: score -= 2; reasons.append("Croisement EMA BEAR")

    # EMA200
    if price > e200: score += 1; reasons.append("Au-dessus EMA200")
    else:            score -= 1; reasons.append("En-dessous EMA200")

    # Signal — seuil strict
    if score >= 7:    signal = "ACHAT"
    elif score <= -6: signal = "VENTE"
    else:             signal = "ATTENDRE"

    confidence = min(92, abs(score) * 7 + 30)

    sl = price - atr_v * 1.5 if signal == "ACHAT" else price + atr_v * 1.5
    tp = price + atr_v * 3.0 if signal == "ACHAT" else price - atr_v * 3.0

    return {
        "signal": signal, "score": score,
        "confidence": confidence, "price": price,
        "rsi": r, "stoch": sto, "macd": m,
        "trend_h4": trend_h4, "atr": atr_v,
        "sl": sl, "tp": tp, "reasons": reasons[:5],
    }

# ═══════════════════════════════════
# VÉRIFICATION PAR PAIRE
# ═══════════════════════════════════
def check(pair):
    name = pair["name"]
    dec = 3 if "JPY" in name else 5

    # 1. Vérifier session
    session, active = get_session()
    if not active:
        return

    # 2. Vérifier actualités
    blocked, news = is_news_blocked(name)
    if blocked:
        msg = f"⚠️ ALERTE NEWS — {name}\n"
        for n in news:
            msg += f"• {n['title']} ({n['currency']}) dans {n['diff_mins']}min\n"
        msg += "Pas de trade recommandé !"
        if last_signals.get(name + "_news") != msg:
            last_signals[name + "_news"] = msg
            send(msg)
        return

    # 3. Analyser
    result = analyze(name, pair["kraken"])
    if not result:
        return

    sig = result["signal"]

    # 4. Anti-contradiction
    if sig != "ATTENDRE":
        current_pos = open_positions.get(name)

        # Si signal contraire à position ouverte
        if current_pos and current_pos != sig:
            send(f"🔄 FERME TA POSITION {current_pos} sur {name} !\nNouveau signal : {sig}")

        # Envoyer seulement si signal différent du dernier
        if last_signals.get(name) != sig:
            last_signals[name] = sig
            open_positions[name] = sig

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
            msg += f"Session : {session}\n"
            msg += f"Score   : {result['score']}/13\n"
            msg += f"Confiance: {result['confidence']}%\n"
            msg += "─────────────────────\n"
            for r in result["reasons"]:
                msg += f"• {r}\n"
            msg += "\nSignal indicatif — risque 2% max"
            send(msg)
            print(f"Signal: {name} {sig} {result['confidence']}%")

# ═══════════════════════════════════
# DÉMARRAGE
# ═══════════════════════════════════
now = datetime.now().strftime("%d/%m %H:%M")
send(f"ARBI BOT PRO v3 — {now}\n9 indicateurs + Calendrier news\nSessions: Londres + New York\nAnti-contradiction actif")
print("Bot Pro v3 demarre")

while True:
    for p in PAIRS:
        try:
            check(p)
        except Exception as e:
            print(f"Erreur {p['name']}: {e}")
        time.sleep(3)
    time.sleep(300)
