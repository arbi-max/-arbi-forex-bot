#!/usr/bin/env python3
"""
ARBI FOREX BOT PRO v5 — Niveau Institutionnel
Smart Money Concepts + Analyse Technique + News Filter
Multi-Timeframe : H4 + H1 + M15
"""

import requests
import time
from datetime import datetime, timezone

TOKEN = "8636672541:AAElNEq4IKwrRzTLuqoaqttadmkGKAVEVlM"
IDS   = ["525011337", "7276558677"]

PAIRS = [
    {"name": "EUR/USD", "kraken": "EURUSD"},
    {"name": "GBP/USD", "kraken": "GBPUSD"},
    {"name": "USD/JPY", "kraken": "USDJPY"},
    {"name": "XAU/USD", "kraken": "XAUUSD"},
]

CAPITAL    = 10000
RISK_PCT   = 1.0
MAX_TRADES = 3

last_signals  = {}
open_pos      = {}
daily         = {"date": "", "count": 0, "losses": 0}

# ═══════════════════════════════════════════════════
# TELEGRAM
# ═══════════════════════════════════════════════════
def send(msg):
    for cid in IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                json={"chat_id": cid, "text": msg},
                timeout=10)
        except:
            pass
        time.sleep(0.5)

# ═══════════════════════════════════════════════════
# DONNEES KRAKEN
# ═══════════════════════════════════════════════════
def ohlc(pair, interval=60, count=200):
    try:
        r = requests.get("https://api.kraken.com/0/public/OHLC",
            params={"pair": pair, "interval": interval}, timeout=10)
        d = r.json()["result"]
        k = [x for x in d if x != "last"][0]
        rows = d[k][-count:]
        return {
            "o": [float(x[1]) for x in rows],
            "h": [float(x[2]) for x in rows],
            "l": [float(x[3]) for x in rows],
            "c": [float(x[4]) for x in rows],
            "v": [float(x[6]) for x in rows],
        }
    except:
        return None

# ═══════════════════════════════════════════════════
# INDICATEURS
# ═══════════════════════════════════════════════════
def ema(c, n):
    if len(c) < n: return c[-1]
    k = 2/(n+1)
    e = sum(c[:n])/n
    for p in c[n:]: e = p*k + e*(1-k)
    return e

def rsi(c, n=14):
    g = l = 0.0
    for i in range(len(c)-n, len(c)):
        d = c[i]-c[i-1]
        if d > 0: g += d
        else: l -= d
    return 100 - 100/(1+g/(l or 0.001))

def rsi_divergence(c):
    if len(c) < 30: return "NONE"
    r1 = rsi(c[-30:-15])
    r2 = rsi(c[-15:])
    p1 = c[-15]
    p2 = c[-1]
    if p2 < p1 and r2 > r1: return "BULL_DIV"
    if p2 > p1 and r2 < r1: return "BEAR_DIV"
    return "NONE"

def macd(c):
    return ema(c, 12) - ema(c, 26)

def bollinger(c, n=20):
    s = c[-n:]
    m = sum(s)/len(s)
    std = (sum((x-m)**2 for x in s)/len(s))**0.5
    return m+2*std, m-2*std, m

def atr(h, l, c, n=14):
    trs = [max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
           for i in range(1, len(c))]
    return sum(trs[-n:])/n

def stoch(h, l, c, n=14):
    hi = max(h[-n:]); lo = min(l[-n:])
    return 100*(c[-1]-lo)/(hi-lo) if hi != lo else 50

# ═══════════════════════════════════════════════════
# SMART MONEY CONCEPTS
# ═══════════════════════════════════════════════════
def swing_points(h, l, lb=5):
    sh, sl = [], []
    for i in range(lb, len(h)-lb):
        if all(h[i] >= h[i-j] for j in range(1,lb+1)) and \
           all(h[i] >= h[i+j] for j in range(1,lb+1)):
            sh.append((i, h[i]))
        if all(l[i] <= l[i-j] for j in range(1,lb+1)) and \
           all(l[i] <= l[i+j] for j in range(1,lb+1)):
            sl.append((i, l[i]))
    return sh, sl

def market_structure(h, l, c):
    sh, sl = swing_points(h, l)
    if len(sh) < 2 or len(sl) < 2:
        return "NEUTRAL", "NONE", "NEUTRAL"

    # Structure
    hh = sh[-1][1] > sh[-2][1]
    hl = sl[-1][1] > sl[-2][1]
    lh = sh[-1][1] < sh[-2][1]
    ll = sl[-1][1] < sl[-2][1]

    if hh and hl:   struct = "BULLISH"
    elif lh and ll: struct = "BEARISH"
    else:           struct = "NEUTRAL"

    # Break of Structure
    price = c[-1]
    bos = "NONE"
    if struct == "BULLISH" and price > sh[-1][1]: bos = "BOS_BULL"
    if struct == "BEARISH" and price < sl[-1][1]: bos = "BOS_BEAR"

    # Change of Character
    choch = "NONE"
    if struct == "BULLISH" and price < sl[-1][1]: choch = "CHOCH_BEAR"
    if struct == "BEARISH" and price > sh[-1][1]: choch = "CHOCH_BULL"

    return struct, bos, choch

def order_blocks(o, h, l, c, lb=30):
    bull_obs, bear_obs = [], []
    start = max(1, len(c)-lb)
    for i in range(start, len(c)-1):
        # Bullish OB: derniere bougie baissiere avant forte montee
        if c[i] < o[i] and c[i+1] > h[i]:
            bull_obs.append({"h": h[i], "l": l[i], "mid": (h[i]+l[i])/2})
        # Bearish OB: derniere bougie haussiere avant forte baisse
        if c[i] > o[i] and c[i+1] < l[i]:
            bear_obs.append({"h": h[i], "l": l[i], "mid": (h[i]+l[i])/2})
    return bull_obs[-3:], bear_obs[-3:]

def fair_value_gaps(h, l, lb=40):
    bull_fvg, bear_fvg = [], []
    start = max(0, len(h)-lb)
    for i in range(start, len(h)-2):
        if l[i+2] > h[i]:
            bull_fvg.append({"top": l[i+2], "bot": h[i], "mid": (l[i+2]+h[i])/2})
        if h[i+2] < l[i]:
            bear_fvg.append({"top": l[i], "bot": h[i+2], "mid": (l[i]+h[i+2])/2})
    return bull_fvg[-3:], bear_fvg[-3:]

def liquidity_sweep(h, l, c):
    sh, sl = swing_points(h, l)
    if not sh or not sl: return False, False
    prev = c[-2]; price = c[-1]
    swept_high = prev > sh[-1][1] and price < sh[-1][1]
    swept_low  = prev < sl[-1][1] and price > sl[-1][1]
    return swept_high, swept_low

def candle_pattern(o, h, l, c):
    if len(c) < 3: return "NONE"
    body = abs(c[-1]-o[-1])
    rng  = h[-1]-l[-1]
    if rng == 0: return "NONE"
    low_wick = min(o[-1],c[-1]) - l[-1]
    up_wick  = h[-1] - max(o[-1],c[-1])
    if low_wick > body*2 and up_wick < body*0.5: return "BULL_PIN"
    if up_wick  > body*2 and low_wick < body*0.5: return "BEAR_PIN"
    if c[-1] > o[-2] and o[-1] < c[-2] and body/rng > 0.6: return "BULL_ENGULF"
    if c[-1] < o[-2] and o[-1] > c[-2] and body/rng > 0.6: return "BEAR_ENGULF"
    return "NONE"

def price_in_ob(price, obs):
    for ob in obs:
        if ob["l"] <= price <= ob["h"]:
            return True
    return False

def price_near_fvg(price, fvgs, thr=0.002):
    for fvg in fvgs:
        if abs(price - fvg["mid"]) / price < thr:
            return True
    return False

# ═══════════════════════════════════════════════════
# CALENDRIER ECONOMIQUE
# ═══════════════════════════════════════════════════
def get_news():
    try:
        r = requests.get(
            "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
            timeout=10)
        events = r.json()
        now = datetime.now(timezone.utc)
        result = []
        for e in events:
            if e.get("impact") in ["High", "Medium"]:
                try:
                    et = datetime.strptime(e["date"], "%Y-%m-%dT%H:%M:%S%z")
                    diff = (et - now).total_seconds() / 60
                    if -30 <= diff <= 60:
                        result.append({
                            "title":    e.get("title", ""),
                            "currency": e.get("country", ""),
                            "impact":   e.get("impact", ""),
                            "mins":     int(diff),
                        })
                except:
                    pass
        return result
    except:
        return []

def news_block(pair):
    events = get_news()
    if not events: return False, []
    curs = []
    if "EUR" in pair: curs.append("EUR")
    if "GBP" in pair: curs.append("GBP")
    if "JPY" in pair: curs.append("JPY")
    if "XAU" in pair: curs.append("USD")
    curs.append("USD")
    blocking = [e for e in events if any(c in e["currency"].upper() for c in curs)]
    return len(blocking) > 0, blocking

# ═══════════════════════════════════════════════════
# SESSION
# ═══════════════════════════════════════════════════
def session():
    h = datetime.now(timezone.utc).hour
    if 7  <= h < 12: return "Londres", True
    if 12 <= h < 16: return "Londres+NY", True
    if 16 <= h < 21: return "New York", True
    return "Hors session", False

# ═══════════════════════════════════════════════════
# GESTION DU RISQUE
# ═══════════════════════════════════════════════════
def lot_size(sl_pips, pip_val=10):
    risk = CAPITAL * RISK_PCT / 100
    lot  = risk / (sl_pips * pip_val) if sl_pips > 0 else 0.01
    return round(max(0.01, min(lot, 2.0)), 2)

def daily_ok():
    today = datetime.now().strftime("%Y-%m-%d")
    if daily["date"] != today:
        daily.update({"date": today, "count": 0, "losses": 0})
    if daily["count"] >= MAX_TRADES:
        return False, f"Max {MAX_TRADES} trades/jour atteint"
    if daily["losses"] >= 2:
        return False, "2 pertes consecutives — pause trading"
    return True, "OK"

# ═══════════════════════════════════════════════════
# ANALYSE PRINCIPALE
# ═══════════════════════════════════════════════════
def analyze(pair_name, kraken_pair):
    # Multi-timeframe
    D1  = ohlc(kraken_pair, 1440, 50)
    H4  = ohlc(kraken_pair, 240,  100)
    H1  = ohlc(kraken_pair, 60,   200)
    M15 = ohlc(kraken_pair, 15,   100)

    if not H4 or not H1 or not M15:
        return None

    price = H1["c"][-1]
    dec   = 3 if "JPY" in pair_name else 5

    # ── INDICATEURS H1 ──
    e50    = ema(H1["c"], 50)
    e200   = ema(H1["c"], 100)
    r      = rsi(H1["c"])
    rdiv   = rsi_divergence(H1["c"])
    m      = macd(H1["c"])
    bb_u, bb_l, bb_m = bollinger(H1["c"])
    atr_v  = atr(H1["h"], H1["l"], H1["c"])
    sto    = stoch(H1["h"], H1["l"], H1["c"])
    candle = candle_pattern(H1["o"], H1["h"], H1["l"], H1["c"])

    # ── SMC H1 ──
    struct_h1, bos_h1, choch_h1 = market_structure(H1["h"], H1["l"], H1["c"])
    bull_ob, bear_ob = order_blocks(H1["o"], H1["h"], H1["l"], H1["c"])
    bull_fvg, bear_fvg = fair_value_gaps(H1["h"], H1["l"])
    swept_high, swept_low = liquidity_sweep(H1["h"], H1["l"], H1["c"])
    in_bull_ob = price_in_ob(price, bull_ob)
    in_bear_ob = price_in_ob(price, bear_ob)
    near_bull_fvg = price_near_fvg(price, bull_fvg)
    near_bear_fvg = price_near_fvg(price, bear_fvg)

    # ── STRUCTURE H4 (tendance longue) ──
    struct_h4, _, _ = market_structure(H4["h"], H4["l"], H4["c"])

    # ── STRUCTURE M15 (confirmation entree) ──
    struct_m15, bos_m15, choch_m15 = market_structure(M15["h"], M15["l"], M15["c"])

    # ═══════════════════
    # SCORING SMC ACHAT
    # ═══════════════════
    bull_score = 0
    bull_reasons = []

    # Structure
    if struct_h4 == "BULLISH":
        bull_score += 2
        bull_reasons.append("H4 structure haussiere (HH+HL)")
    if struct_h1 == "BULLISH":
        bull_score += 2
        bull_reasons.append("H1 structure haussiere")
    if bos_h1 == "BOS_BULL":
        bull_score += 2
        bull_reasons.append("Break of Structure haussier")
    if choch_m15 == "CHOCH_BULL":
        bull_score += 2
        bull_reasons.append("Change of Character M15 bullish")

    # SMC zones
    if swept_low:
        bull_score += 3
        bull_reasons.append("Sweep liquidite bas detecte")
    if in_bull_ob:
        bull_score += 3
        bull_reasons.append("Prix dans Order Block haussier")
    if near_bull_fvg:
        bull_score += 2
        bull_reasons.append("Prix pres FVG haussier")

    # Indicateurs techniques
    if r < 35:
        bull_score += 2
        bull_reasons.append(f"RSI survendu ({r:.1f})")
    if rdiv == "BULL_DIV":
        bull_score += 2
        bull_reasons.append("Divergence RSI haussiere")
    if m > 0:
        bull_score += 1
        bull_reasons.append("MACD positif")
    if price < bb_l:
        bull_score += 2
        bull_reasons.append("Prix sous BB basse")
    if sto < 20:
        bull_score += 2
        bull_reasons.append(f"Stochastique survendu ({sto:.1f})")
    if price > e50:
        bull_score += 1
        bull_reasons.append("Prix au-dessus EMA50")
    if price > e200:
        bull_score += 1
        bull_reasons.append("Prix au-dessus EMA200")
    if candle in ["BULL_PIN", "BULL_ENGULF"]:
        bull_score += 2
        bull_reasons.append(f"Pattern : {candle}")

    # ═══════════════════
    # SCORING SMC VENTE
    # ═══════════════════
    bear_score = 0
    bear_reasons = []

    if struct_h4 == "BEARISH":
        bear_score += 2
        bear_reasons.append("H4 structure baissiere (LH+LL)")
    if struct_h1 == "BEARISH":
        bear_score += 2
        bear_reasons.append("H1 structure baissiere")
    if bos_h1 == "BOS_BEAR":
        bear_score += 2
        bear_reasons.append("Break of Structure baissier")
    if choch_m15 == "CHOCH_BEAR":
        bear_score += 2
        bear_reasons.append("Change of Character M15 bearish")

    if swept_high:
        bear_score += 3
        bear_reasons.append("Sweep liquidite haut detecte")
    if in_bear_ob:
        bear_score += 3
        bear_reasons.append("Prix dans Order Block baissier")
    if near_bear_fvg:
        bear_score += 2
        bear_reasons.append("Prix pres FVG baissier")

    if r > 65:
        bear_score += 2
        bear_reasons.append(f"RSI surachete ({r:.1f})")
    if rdiv == "BEAR_DIV":
        bear_score += 2
        bear_reasons.append("Divergence RSI baissiere")
    if m < 0:
        bear_score += 1
        bear_reasons.append("MACD negatif")
    if price > bb_u:
        bear_score += 2
        bear_reasons.append("Prix au-dessus BB haute")
    if sto > 80:
        bear_score += 2
        bear_reasons.append(f"Stochastique surachete ({sto:.1f})")
    if price < e50:
        bear_score += 1
        bear_reasons.append("Prix en-dessous EMA50")
    if price < e200:
        bear_score += 1
        bear_reasons.append("Prix en-dessous EMA200")
    if candle in ["BEAR_PIN", "BEAR_ENGULF"]:
        bear_score += 2
        bear_reasons.append(f"Pattern : {candle}")

    # ═══════════════════
    # SIGNAL FINAL
    # Seuil strict : 14/26 minimum
    # ═══════════════════
    MAX_SCORE = 26

    if bull_score >= 14 and bull_score > bear_score:
        signal    = "ACHAT"
        score     = bull_score
        reasons   = bull_reasons
    elif bear_score >= 14 and bear_score > bull_score:
        signal    = "VENTE"
        score     = bear_score
        reasons   = bear_reasons
    else:
        return None  # Pas de signal

    confidence = min(95, int(score / MAX_SCORE * 100))

    # SL structurel + ATR
    sh_pts, sl_pts = swing_points(H1["h"], H1["l"])
    if signal == "ACHAT":
        sl_struct = sl_pts[-1][1] - atr_v * 0.5 if sl_pts else price - atr_v * 1.5
        sl = min(sl_struct, price - atr_v * 1.5)
        tp1 = price + (price - sl) * 2
        tp2 = price + (price - sl) * 3
    else:
        sl_struct = sh_pts[-1][1] + atr_v * 0.5 if sh_pts else price + atr_v * 1.5
        sl = max(sl_struct, price + atr_v * 1.5)
        tp1 = price - (sl - price) * 2
        tp2 = price - (sl - price) * 3

    sl_pips = abs(price - sl) / (0.01 if "JPY" in pair_name else 0.0001)
    lot     = lot_size(sl_pips)

    return {
        "signal":     signal,
        "score":      score,
        "max_score":  MAX_SCORE,
        "confidence": confidence,
        "price":      price,
        "sl":         sl,
        "tp1":        tp1,
        "tp2":        tp2,
        "sl_pips":    sl_pips,
        "lot":        lot,
        "rsi":        r,
        "stoch":      sto,
        "macd":       m,
        "struct_h4":  struct_h4,
        "struct_h1":  struct_h1,
        "atr":        atr_v,
        "candle":     candle,
        "reasons":    reasons[:6],
        "dec":        dec,
    }

# ═══════════════════════════════════════════════════
# VERIFICATION PAR PAIRE
# ═══════════════════════════════════════════════════
def check(pair):
    name = pair["name"]

    # 1. Session active ?
    sess, active = session()
    if not active:
        return

    # 2. Limites quotidiennes
    ok, reason = daily_ok()
    if not ok:
        return

    # 3. Filtre news
    blocked, news = news_block(name)
    if blocked:
        alert_key = name + str([n["title"] for n in news])
        if last_signals.get("news_" + name) != alert_key:
            last_signals["news_" + name] = alert_key
            msg = f"ALERTE NEWS — {name}\n"
            msg += "Pas de trade recommande !\n"
            for n in news:
                icon = "ROUGE" if n["impact"] == "High" else "ORANGE"
                msg += f"• [{icon}] {n['title']} ({n['currency']}) dans {n['mins']}min\n"
            send(msg)
        return

    # 4. Analyse
    result = analyze(name, pair["kraken"])
    if not result:
        return

    sig = result["signal"]
    dec = result["dec"]

    # 5. Anti-contradiction
    current = open_pos.get(name)
    if current and current != sig:
        send(f"FERME TA POSITION {current} sur {name}\nNouveau signal : {sig}")

    # 6. Eviter doublons
    if last_signals.get(name) == sig:
        return

    last_signals[name] = sig
    open_pos[name]     = sig
    daily["count"]    += 1

    icon = "BUY" if sig == "ACHAT" else "SELL"
    conf = result["confidence"]

    msg  = f"{icon} SIGNAL {sig} — {name}\n"
    msg += "═══════════════════════\n"
    msg += f"Prix    : {result['price']:.{dec}f}\n"
    msg += f"SL      : {result['sl']:.{dec}f}\n"
    msg += f"TP1     : {result['tp1']:.{dec}f} (R:R 1:2)\n"
    msg += f"TP2     : {result['tp2']:.{dec}f} (R:R 1:3)\n"
    msg += f"Lot     : {result['lot']}\n"
    msg += f"SL pips : {result['sl_pips']:.1f}\n"
    msg += "═══════════════════════\n"
    msg += f"Confiance : {conf}%\n"
    msg += f"Score     : {result['score']}/{result['max_score']}\n"
    msg += f"Session   : {sess}\n"
    msg += f"H4 struct : {result['struct_h4']}\n"
    msg += f"H1 struct : {result['struct_h1']}\n"
    msg += f"RSI       : {result['rsi']:.1f}\n"
    msg += f"Stoch     : {result['stoch']:.1f}\n"
    msg += f"Bougie    : {result['candle']}\n"
    msg += "═══════════════════════\n"
    msg += "Confluences SMC :\n"
    for r in result["reasons"]:
        msg += f"• {r}\n"
    msg += "═══════════════════════\n"
    msg += "Risque : 1% du capital\n"
    msg += "Signal indicatif — tradez prudemment"

    send(msg)
    print(f"[{datetime.now().strftime('%H:%M')}] Signal {name} {sig} conf={conf}%")

# ═══════════════════════════════════════════════════
# DEMARRAGE
# ═══════════════════════════════════════════════════
now = datetime.now().strftime("%d/%m/%Y %H:%M")
send(
    f"ARBI BOT PRO v5 — {now}\n"
    f"Niveau : Institutionnel SMC\n"
    f"Paires : EUR/USD GBP/USD USD/JPY XAU/USD\n"
    f"Analyse : D1 + H4 + H1 + M15\n"
    f"Seuil signal : 14/26 confluences\n"
    f"News filter : actif\n"
    f"Capital : {CAPITAL}$ | Risque : {RISK_PCT}%\n"
    f"En attente de signaux de qualite..."
)
print("Bot Pro v5 demarre")

while True:
    for p in PAIRS:
        try:
            check(p)
        except Exception as e:
            print(f"Erreur {p['name']}: {e}")
        time.sleep(3)
    print(f"[{datetime.now().strftime('%H:%M')}] Cycle termine")
    time.sleep(300)
