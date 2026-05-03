#!/usr/bin/env python3
"""
ARBI BOT CERVEAU v1.0
Bot 1 — Cerveau (Railway/Python)
- Analyse SMC avancee
- Detection de regime
- Multi-strategies
- Score de qualite
- Filtre news
- ML adaptatif
- Serveur web Flask
- Recoit resultats de Bot 2
- Apprend de chaque trade
"""

import requests
import time
import json
import os
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from threading import Thread

# ═══════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════
TOKEN    = "8636672541:AAElNEq4IKwrRzTLuqoaqttadmkGKAVEVlM"
IDS      = ["525011337", "7276558677"]

PAIRS = [
    {"name": "EURUSD", "kraken": "EURUSD", "pip": 0.0001},
    {"name": "GBPUSD", "kraken": "GBPUSD", "pip": 0.0001},
    {"name": "USDJPY", "kraken": "USDJPY", "pip": 0.01},
    {"name": "XAUUSD", "kraken": "XAUUSD", "pip": 0.01},
]

CAPITAL    = 10000.0
RISK_PCT   = 1.0
MAX_TRADES = 3
DATA_FILE  = "brain_data.json"

# ═══════════════════════════════════════════════════
# FLASK SERVER
# ═══════════════════════════════════════════════════
app = Flask(__name__)

# Signal actuel pour Bot 2
current_signal = {
    "signal": "NONE",
    "pair": "",
    "entry": 0,
    "sl": 0,
    "tp1": 0,
    "tp2": 0,
    "lot": 0,
    "score": 0,
    "regime": "",
    "timestamp": ""
}

@app.route("/signal", methods=["GET"])
def get_signal():
    """Bot 2 interroge ce endpoint pour obtenir le signal"""
    return jsonify(current_signal)

@app.route("/result", methods=["POST"])
def receive_result():
    """Bot 2 envoie le resultat du trade ici"""
    data = request.json
    if not data:
        return jsonify({"status": "error"}), 400

    pair     = data.get("pair", "")
    result   = data.get("result", "")  # WIN ou LOSS
    pnl      = data.get("pnl", 0)
    score    = data.get("score", 0)
    regime   = data.get("regime", "")

    print(f"[RESULTAT] {pair} {result} PnL={pnl} Score={score}")

    # Enregistrer et apprendre
    record_and_learn(pair, result, pnl, score, regime)

    # Notifier Telegram
    icon = "GAGNE" if result == "WIN" else "PERDU"
    msg  = f"{icon} — {pair}\n"
    msg += f"Resultat : {result}\n"
    msg += f"P&L      : {pnl:+.2f}$\n"
    msg += f"Score    : {score}/10\n"
    msg += f"Regime   : {regime}\n"
    msg += f"Bot apprend et s'ameliore !"
    send_telegram(msg)

    return jsonify({"status": "ok"})

@app.route("/status", methods=["GET"])
def status():
    """Status du bot"""
    brain = load_data()
    wins   = sum(1 for t in brain["trades"] if t["result"] == "WIN")
    losses = sum(1 for t in brain["trades"] if t["result"] == "LOSS")
    total  = wins + losses
    wr     = round(wins/total*100, 1) if total > 0 else 0
    return jsonify({
        "status": "running",
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "winrate": wr,
        "min_score": brain["params"]["min_score"],
        "risk_pct": brain["params"]["risk_pct"],
        "current_signal": current_signal
    })

# ═══════════════════════════════════════════════════
# PERSISTANCE ET APPRENTISSAGE
# ═══════════════════════════════════════════════════
def load_data():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                return json.load(f)
    except:
        pass
    return {
        "trades": [],
        "params": {
            "min_score": 6,
            "risk_pct": 1.0,
            "regime_weights": {
                "TREND": 1.0,
                "BREAKOUT": 0.8,
                "PULLBACK": 0.9,
                "RANGE": 0.6
            }
        }
    }

def save_data(data):
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f)
    except:
        pass

def record_and_learn(pair, result, pnl, score, regime):
    """Enregistre le trade et adapte les parametres"""
    brain = load_data()

    # Enregistrer le trade
    brain["trades"].append({
        "date":   datetime.now().strftime("%Y-%m-%d %H:%M"),
        "pair":   pair,
        "result": result,
        "pnl":    pnl,
        "score":  score,
        "regime": regime
    })
    brain["trades"] = brain["trades"][-200:]

    # APPRENTISSAGE ADAPTATIF
    trades = brain["trades"]
    if len(trades) >= 10:
        recent = trades[-20:] if len(trades) >= 20 else trades
        wins   = sum(1 for t in recent if t["result"] == "WIN")
        total  = len(recent)
        wr     = wins / total

        # Ajuster score minimum
        current_score = brain["params"]["min_score"]
        if wr < 0.40:
            brain["params"]["min_score"] = min(9, current_score + 1)
            print(f"[ML] Winrate faible {wr:.0%} -> Score min augmente a {brain['params']['min_score']}")
        elif wr > 0.65:
            brain["params"]["min_score"] = max(4, current_score - 1)
            print(f"[ML] Winrate fort {wr:.0%} -> Score min baisse a {brain['params']['min_score']}")

        # Ajuster risque
        if wr < 0.40:
            brain["params"]["risk_pct"] = max(0.5, brain["params"]["risk_pct"] - 0.1)
        elif wr > 0.65:
            brain["params"]["risk_pct"] = min(1.5, brain["params"]["risk_pct"] + 0.1)

        # Ajuster poids des regimes
        if regime and len(trades) >= 10:
            regime_trades = [t for t in recent if t["regime"] == regime]
            if len(regime_trades) >= 3:
                regime_wins = sum(1 for t in regime_trades if t["result"] == "WIN")
                regime_wr   = regime_wins / len(regime_trades)
                weight = brain["params"]["regime_weights"].get(regime, 1.0)
                if regime_wr < 0.40:
                    brain["params"]["regime_weights"][regime] = max(0.3, weight - 0.1)
                elif regime_wr > 0.65:
                    brain["params"]["regime_weights"][regime] = min(1.5, weight + 0.1)

    save_data(brain)
    print(f"[ML] Params: score_min={brain['params']['min_score']} risk={brain['params']['risk_pct']:.1f}%")

# ═══════════════════════════════════════════════════
# TELEGRAM
# ═══════════════════════════════════════════════════
def send_telegram(msg):
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
def get_candles(pair, interval=60, count=200):
    try:
        r = requests.get(
            "https://api.kraken.com/0/public/OHLC",
            params={"pair": pair, "interval": interval},
            timeout=10)
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
    k = 2/(n+1); e = sum(c[:n])/n
    for p in c[n:]: e = p*k + e*(1-k)
    return e

def rsi(c, n=14):
    g = l = 0.0
    for i in range(len(c)-n, len(c)):
        d = c[i]-c[i-1]
        if d > 0: g += d
        else: l -= d
    return 100 - 100/(1+g/(l or 0.001))

def macd(c):
    return ema(c, 12) - ema(c, 26)

def atr(h, l, c, n=14):
    trs = [max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
           for i in range(1, len(c))]
    return sum(trs[-n:])/n

def rsi_divergence(c):
    if len(c) < 30: return "NONE"
    r1 = rsi(c[-30:-15]); r2 = rsi(c[-15:])
    if c[-1] < c[-15] and r2 > r1: return "BULL"
    if c[-1] > c[-15] and r2 < r1: return "BEAR"
    return "NONE"

# ═══════════════════════════════════════════════════
# DETECTION DE REGIME
# ═══════════════════════════════════════════════════
def detect_regime(h, l, c, h4_c):
    """Detecte le regime de marche"""
    atr_v    = atr(h, l, c)
    atr_avg  = sum([atr(h[:-i*5] if i*5 < len(h) else h,
                        l[:-i*5] if i*5 < len(l) else l,
                        c[:-i*5] if i*5 < len(c) else c)
                    for i in range(1, 5)]) / 4

    e50  = ema(c, 50)
    e200 = ema(c, 100)
    price = c[-1]

    # Volatilite
    atr_ratio = atr_v / atr_avg if atr_avg > 0 else 1

    # Tendance H4
    e50_h4  = ema(h4_c, 50)
    e200_h4 = ema(h4_c, 100)
    trend_h4 = "BULL" if e50_h4 > e200_h4 else "BEAR"

    # Range detection
    highs = h[-20:]
    lows  = l[-20:]
    range_size = (max(highs) - min(lows)) / price
    is_range = range_size < 0.005  # Range < 0.5%

    if atr_ratio > 2.5:
        return "INSTABLE", trend_h4
    if is_range:
        return "RANGE", trend_h4
    if e50 > e200:
        return "TREND_BULL", trend_h4
    if e50 < e200:
        return "TREND_BEAR", trend_h4
    return "NEUTRAL", trend_h4

# ═══════════════════════════════════════════════════
# SMC
# ═══════════════════════════════════════════════════
def swing_points(h, l, lb=5):
    sh, sl = [], []
    for i in range(lb, len(h)-lb):
        if all(h[i]>=h[i-j] for j in range(1,lb+1)) and all(h[i]>=h[i+j] for j in range(1,lb+1)):
            sh.append((i, h[i]))
        if all(l[i]<=l[i-j] for j in range(1,lb+1)) and all(l[i]<=l[i+j] for j in range(1,lb+1)):
            sl.append((i, l[i]))
    return sh, sl

def detect_order_blocks(o, h, l, c, lb=30):
    bull, bear = [], []
    for i in range(max(1,len(c)-lb), len(c)-1):
        if c[i]<o[i] and c[i+1]>h[i]:
            bull.append({"h":h[i],"l":l[i],"mid":(h[i]+l[i])/2})
        if c[i]>o[i] and c[i+1]<l[i]:
            bear.append({"h":h[i],"l":l[i],"mid":(h[i]+l[i])/2})
    return bull[-3:], bear[-3:]

def detect_fvg(h, l, lb=30):
    bull, bear = [], []
    for i in range(max(0,len(h)-lb), len(h)-2):
        if l[i+2]>h[i]:
            bull.append({"top":l[i+2],"bot":h[i],"mid":(l[i+2]+h[i])/2})
        if h[i+2]<l[i]:
            bear.append({"top":l[i],"bot":h[i+2],"mid":(l[i]+h[i+2])/2})
    return bull[-3:], bear[-3:]

def sweep_low(h, l, c):
    sh, sl = swing_points(h, l)
    if not sl: return False
    return l[-1] < sl[-1][1] and c[-1] > sl[-1][1]

def sweep_high(h, l, c):
    sh, sl = swing_points(h, l)
    if not sh: return False
    return h[-1] > sh[-1][1] and c[-1] < sh[-1][1]

def in_ob(price, obs):
    return any(ob["l"]<=price<=ob["h"] for ob in obs)

def near_fvg(price, fvgs, thr=0.002):
    return any(abs(price-f["mid"])/price < thr for f in fvgs)

# ═══════════════════════════════════════════════════
# NEWS FILTER
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
                    from datetime import datetime as dt
                    et = dt.strptime(e["date"], "%Y-%m-%dT%H:%M:%S%z")
                    diff = (et - now).total_seconds() / 60
                    if -30 <= diff <= 60:
                        result.append({
                            "title":  e.get("title",""),
                            "cur":    e.get("country",""),
                            "impact": e.get("impact",""),
                            "mins":   int(diff)
                        })
                except:
                    pass
        return result
    except:
        return []

def is_news_blocked(pair):
    events = get_news()
    if not events: return False, []
    curs = []
    if "EUR" in pair: curs.append("EUR")
    if "GBP" in pair: curs.append("GBP")
    if "JPY" in pair: curs.append("JPY")
    if "XAU" in pair: curs.append("USD")
    curs.append("USD")
    blocking = [e for e in events if any(c in e["cur"].upper() for c in curs) and e["impact"]=="High"]
    return len(blocking) > 0, blocking

# ═══════════════════════════════════════════════════
# SESSION
# ═══════════════════════════════════════════════════
def get_session():
    h = datetime.now(timezone.utc).hour
    if 7  <= h < 12: return "Londres", True
    if 12 <= h < 16: return "Overlap", True
    if 16 <= h < 21: return "NewYork", True
    return "Hors session", False

# ═══════════════════════════════════════════════════
# ANALYSE PRINCIPALE
# ═══════════════════════════════════════════════════
def analyze(pair):
    brain = load_data()
    min_score = brain["params"]["min_score"]
    risk_pct  = brain["params"]["risk_pct"]

    H4  = get_candles(pair["kraken"], 240, 100)
    H1  = get_candles(pair["kraken"], 60,  200)
    M15 = get_candles(pair["kraken"], 15,  100)
    if not H4 or not H1 or not M15: return None

    c = H1["c"]; h = H1["h"]; l = H1["l"]; o = H1["o"]
    price = c[-1]
    is_jpy = "JPY" in pair["name"]
    dec = 3 if is_jpy else 5

    # Detection regime
    regime, trend_h4 = detect_regime(h, l, c, H4["c"])

    # Bloquer si instable
    if regime == "INSTABLE": return None

    # Poids du regime
    regime_key = regime.replace("TREND_BULL","TREND").replace("TREND_BEAR","TREND")
    regime_weight = brain["params"]["regime_weights"].get(regime_key, 1.0)

    # Indicateurs H1
    e9   = ema(c, 9);   e21  = ema(c, 21)
    e50  = ema(c, 50);  e200 = ema(c, 100)
    e9p  = ema(c[:-1], 9); e21p = ema(c[:-1], 21)
    r    = rsi(c)
    m    = macd(c)
    atr_v = atr(h, l, c)
    rdiv = rsi_divergence(c)

    # Indicateurs M15
    e9_m15  = ema(M15["c"], 9)
    e21_m15 = ema(M15["c"], 21)
    e9_m15p = ema(M15["c"][:-1], 9)
    e21_m15p= ema(M15["c"][:-1], 21)
    r_m15   = rsi(M15["c"])

    # SMC
    bull_ob, bear_ob = detect_order_blocks(o, h, l, c)
    bull_fvg, bear_fvg = detect_fvg(h, l)
    sw_low  = sweep_low(h, l, c)
    sw_high = sweep_high(h, l, c)
    in_bull = in_ob(price, bull_ob)
    in_bear = in_ob(price, bear_ob)
    nr_bull = near_fvg(price, bull_fvg)
    nr_bear = near_fvg(price, bear_fvg)

    cross_up = e9p <= e21p and e9 > e21
    cross_dn = e9p >= e21p and e9 < e21
    m15_up   = e9_m15p <= e21_m15p and e9_m15 > e21_m15
    m15_dn   = e9_m15p >= e21_m15p and e9_m15 < e21_m15

    # ── SCORE BUY ──
    bs = 0; br = []
    if trend_h4 == "BULL":    bs+=2; br.append("H4 haussier")
    if e9>e21 and e21>e50:    bs+=2; br.append("EMA alignees hausse")
    if cross_up:              bs+=1; br.append("Croisement EMA bull")
    if m15_up:                bs+=1; br.append("M15 confirmation")
    if sw_low:                bs+=2; br.append("Sweep liquidite bas")
    if in_bull:               bs+=2; br.append("Order Block haussier")
    if nr_bull:               bs+=1; br.append("FVG haussier")
    if r < 35:                bs+=1; br.append(f"RSI survendu ({r:.1f})")
    if rdiv == "BULL":        bs+=1; br.append("Divergence RSI bull")
    if m > 0:                 bs+=1; br.append("MACD positif")
    if price > e200:          bs+=1; br.append("Au-dessus EMA200")
    if r_m15 > 50:            bs+=1; br.append(f"RSI M15 > 50")

    # ── SCORE SELL ──
    ss = 0; sr = []
    if trend_h4 == "BEAR":    ss+=2; sr.append("H4 baissier")
    if e9<e21 and e21<e50:    ss+=2; sr.append("EMA alignees baisse")
    if cross_dn:              ss+=1; sr.append("Croisement EMA bear")
    if m15_dn:                ss+=1; sr.append("M15 confirmation")
    if sw_high:               ss+=2; sr.append("Sweep liquidite haut")
    if in_bear:               ss+=2; sr.append("Order Block baissier")
    if nr_bear:               ss+=1; sr.append("FVG baissier")
    if r > 65:                ss+=1; sr.append(f"RSI surachete ({r:.1f})")
    if rdiv == "BEAR":        ss+=1; sr.append("Divergence RSI bear")
    if m < 0:                 ss+=1; sr.append("MACD negatif")
    if price < e200:          ss+=1; sr.append("En-dessous EMA200")
    if r_m15 < 50:            ss+=1; sr.append(f"RSI M15 < 50")

    # Appliquer poids du regime
    bs_weighted = int(bs * regime_weight)
    ss_weighted = int(ss * regime_weight)

    # Signal final
    if bs_weighted >= min_score and bs_weighted > ss_weighted:
        signal = "BUY"; score = bs_weighted; reasons = br
    elif ss_weighted >= min_score and ss_weighted > bs_weighted:
        signal = "SELL"; score = ss_weighted; reasons = sr
    else:
        return None

    # SL/TP
    sh_pts, sl_pts = swing_points(h, l)
    if signal == "BUY":
        sl = min(sl_pts[-1][1]-atr_v*0.5 if sl_pts else price-atr_v*1.5, price-atr_v*1.5)
        tp1 = price + (price-sl)*2
        tp2 = price + (price-sl)*3
    else:
        sl = max(sh_pts[-1][1]+atr_v*0.5 if sh_pts else price+atr_v*1.5, price+atr_v*1.5)
        tp1 = price - (sl-price)*2
        tp2 = price - (sl-price)*3

    # Lot
    sl_pips = abs(price-sl) / (0.01 if is_jpy else 0.0001)
    risk_amt = CAPITAL * risk_pct / 100
    lot = round(max(0.01, min(risk_amt / (sl_pips * 10), 2.0)), 2)

    return {
        "signal":  signal,
        "pair":    pair["name"],
        "entry":   round(price, dec),
        "sl":      round(sl, dec),
        "tp1":     round(tp1, dec),
        "tp2":     round(tp2, dec),
        "lot":     lot,
        "score":   score,
        "regime":  regime,
        "reasons": reasons[:6],
        "dec":     dec
    }

# ═══════════════════════════════════════════════════
# BOUCLE PRINCIPALE
# ═══════════════════════════════════════════════════
last_signals = {}
last_news_alert = {}

def trading_loop():
    global current_signal

    send_telegram(
        f"ARBI BOT CERVEAU v1.0 DEMARRE\n"
        f"Analyse: SMC + EMA + RSI + MACD + ATR\n"
        f"Regime: Tendance/Range/Instable\n"
        f"ML: Apprentissage actif\n"
        f"Serveur: actif sur /signal\n"
        f"En attente de setups..."
    )

    while True:
        sess_name, sess_active = get_session()

        if not sess_active:
            current_signal = {"signal": "NONE", "pair": "", "timestamp": str(datetime.now())}
            time.sleep(600)
            continue

        brain = load_data()

        for pair in PAIRS:
            try:
                # News filter
                blocked, news = is_news_blocked(pair["name"])
                if blocked:
                    key = pair["name"] + str([n["title"] for n in news])
                    if last_news_alert.get(pair["name"]) != key:
                        last_news_alert[pair["name"]] = key
                        msg = f"NEWS ROUGE — {pair['name']}\n"
                        for n in news:
                            msg += f"• {n['title']} dans {n['mins']}min\n"
                        msg += "Trade bloque !"
                        send_telegram(msg)
                    continue

                # Analyse
                result = analyze(pair)
                if not result: continue

                sig = result["signal"]
                if last_signals.get(pair["name"]) == sig: continue
                last_signals[pair["name"]] = sig

                # Mettre a jour signal pour Bot 2
                current_signal = {
                    "signal":    sig,
                    "pair":      result["pair"],
                    "entry":     result["entry"],
                    "sl":        result["sl"],
                    "tp1":       result["tp1"],
                    "tp2":       result["tp2"],
                    "lot":       result["lot"],
                    "score":     result["score"],
                    "regime":    result["regime"],
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }

                # Telegram
                dec = result["dec"]
                icon = "BUY" if sig == "BUY" else "SELL"
                msg  = f"{icon} {result['pair']}\n"
                msg += "============================\n"
                msg += f"Entree : {result['entry']:.{dec}f}\n"
                msg += f"SL     : {result['sl']:.{dec}f}\n"
                msg += f"TP1    : {result['tp1']:.{dec}f} (1:2)\n"
                msg += f"TP2    : {result['tp2']:.{dec}f} (1:3)\n"
                msg += f"Lot    : {result['lot']}\n"
                msg += "============================\n"
                msg += f"Score  : {result['score']}/{brain['params']['min_score']} min\n"
                msg += f"Regime : {result['regime']}\n"
                msg += f"Session: {sess_name}\n"
                msg += "============================\n"
                msg += "Confluences :\n"
                for r in result["reasons"]:
                    msg += f"• {r}\n"
                msg += f"Signal envoye a Bot 2 (Copieur)"
                send_telegram(msg)
                print(f"[SIGNAL] {result['pair']} {sig} score={result['score']} regime={result['regime']}")

            except Exception as e:
                print(f"Erreur {pair['name']}: {e}")
            time.sleep(3)

        time.sleep(300)

# ═══════════════════════════════════════════════════
# DEMARRAGE
# ═══════════════════════════════════════════════════
if __name__ == "__main__":
    # Lancer le bot dans un thread separe
    bot_thread = Thread(target=trading_loop, daemon=True)
    bot_thread.start()

    # Lancer le serveur Flask
    port = int(os.environ.get("PORT", 5000))
    print(f"Serveur Flask demarre sur port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
