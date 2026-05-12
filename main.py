#!/usr/bin/env python3
"""
ARBI BOT CERVEAU v3.0
Corrections majeures :
1. Score minimum 7, jamais sous 6 même avec ML
2. RANGE complètement bloqué
3. Signal sur bougie fermée uniquement
4. Filtre ATR volatilité (2x normale = stop)
5. H4 et H1 doivent être alignés obligatoirement
6. Blocage 4h après signal pour éviter signaux contradictoires
"""

import requests
import time
import json
import os
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify
from threading import Thread

# =========================================
# CONFIG
# =========================================

TOKEN = "8636672541:AAElNEq4IKwrRzTLuqoaqttadmkGKAVEVlM"
IDS   = ["525011337", "7276558677"]

PAIRS = [
    {"name": "EURUSD", "kraken": "EURUSD", "pip": 0.0001},
    {"name": "GBPUSD", "kraken": "GBPUSD", "pip": 0.0001},
    {"name": "USDJPY", "kraken": "USDJPY", "pip": 0.01},
    {"name": "XAUUSD", "kraken": "XAUUSD", "pip": 0.01},
]

CAPITAL        = 10000.0
RISK_PCT       = 1.0
DATA_FILE      = "brain_data.json"

# CORRECTION 1 — Score plancher absolu
SCORE_MIN_HARD = 7    # Score de base
SCORE_MIN_FLOOR = 6   # Jamais en dessous, même avec ML

# CORRECTION 6 — Blocage après signal (en secondes)
SIGNAL_COOLDOWN = 4 * 3600  # 4 heures

# =========================================
# FLASK
# =========================================

app = Flask(__name__)

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

# Dictionnaire pour tracker le dernier signal envoyé par paire
# Format : {"EURUSD": {"signal": "BUY", "time": datetime}}
last_signals     = {}

# Dictionnaire pour tracker le blocage par paire
# Format : {"EURUSD": datetime_fin_blocage}
pair_cooldowns   = {}

# Dictionnaire pour éviter les doublons de news alert
last_news_alert  = {}

# =========================================
# FLASK ROUTES
# =========================================

@app.route("/signal", methods=["GET"])
def get_signal():
    global current_signal
    pair = request.args.get("pair", "")
    signal_to_send = current_signal.copy()
    if current_signal["signal"] != "NONE" and pair == current_signal.get("pair", ""):
        current_signal["signal"] = "NONE"
        print(f"[SIGNAL] Reset apres lecture par {pair}")
    return jsonify(signal_to_send)

@app.route("/result", methods=["POST"])
def receive_result():
    data = request.json
    if not data:
        return jsonify({"status": "error"}), 400
    pair   = data.get("pair", "")
    result = data.get("result", "")
    pnl    = data.get("pnl", 0)
    score  = data.get("score", 0)
    regime = data.get("regime", "")
    print(f"[RESULTAT] {pair} {result} PnL={pnl}")
    record_and_learn(pair, result, pnl, score, regime)

    # Libérer le cooldown si trade clôturé
    if pair in pair_cooldowns:
        del pair_cooldowns[pair]
        print(f"[COOLDOWN] {pair} libéré après clôture trade")

    icon = "✅ GAGNE" if result == "WIN" else "❌ PERDU"
    msg  = f"{icon} — {pair}\nResultat : {result}\nP&L : {pnl:+.2f}$\nBot apprend et s'ameliore !"
    send_telegram(msg)
    return jsonify({"status": "ok"})

@app.route("/status", methods=["GET"])
def status():
    brain  = load_data()
    wins   = sum(1 for t in brain["trades"] if t["result"] == "WIN")
    losses = sum(1 for t in brain["trades"] if t["result"] == "LOSS")
    total  = wins + losses
    wr     = round(wins / total * 100, 1) if total > 0 else 0
    cooldowns_info = {p: str(t) for p, t in pair_cooldowns.items()}
    return jsonify({
        "status": "running",
        "wins": wins,
        "losses": losses,
        "winrate": wr,
        "current_signal": current_signal,
        "cooldowns": cooldowns_info,
        "min_score": brain["params"]["min_score"]
    })

# =========================================
# UTILS — WEEKEND / SESSION
# =========================================

def is_weekend():
    now = datetime.now(timezone.utc)
    wd  = now.weekday()
    h   = now.hour
    if wd == 4 and h >= 22: return True
    if wd == 5:             return True
    if wd == 6 and h < 22: return True
    return False

def get_session():
    h = datetime.now(timezone.utc).hour
    if 7  <= h < 12: return "Londres", True
    if 12 <= h < 16: return "Overlap", True
    if 16 <= h < 21: return "NewYork", True
    return "Hors session", False

# =========================================
# DATA — LOAD / SAVE / LEARN
# =========================================

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
            "min_score": SCORE_MIN_HARD,
            "risk_pct": RISK_PCT,
            "regime_weights": {
                "TREND":    1.0,
                "BREAKOUT": 0.8,
                "PULLBACK": 0.9,
                "RANGE":    0.0   # CORRECTION 2 — RANGE = poids 0 = jamais tradé
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
    brain = load_data()
    brain["trades"].append({
        "date":   datetime.now().strftime("%Y-%m-%d %H:%M"),
        "pair":   pair,
        "result": result,
        "pnl":    pnl,
        "score":  score,
        "regime": regime
    })
    brain["trades"] = brain["trades"][-200:]
    trades = brain["trades"]

    if len(trades) >= 10:
        recent = trades[-20:] if len(trades) >= 20 else trades
        wins   = sum(1 for t in recent if t["result"] == "WIN")
        wr     = wins / len(recent)
        cs     = brain["params"]["min_score"]

        # CORRECTION 1 — ML ajuste le score mais jamais sous SCORE_MIN_FLOOR
        if wr < 0.40:
            brain["params"]["min_score"] = min(9, cs + 1)
        elif wr > 0.65:
            # Jamais descendre sous le plancher absolu
            brain["params"]["min_score"] = max(SCORE_MIN_FLOOR, cs - 1)

        if wr < 0.40:
            brain["params"]["risk_pct"] = max(0.5, brain["params"]["risk_pct"] - 0.1)
        elif wr > 0.65:
            brain["params"]["risk_pct"] = min(1.5, brain["params"]["risk_pct"] + 0.1)

    # CORRECTION 2 — S'assurer que RANGE reste toujours à 0
    brain["params"]["regime_weights"]["RANGE"] = 0.0

    save_data(brain)

# =========================================
# TELEGRAM
# =========================================

def send_telegram(msg):
    for cid in IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                json={"chat_id": cid, "text": msg},
                timeout=10
            )
        except:
            pass
        time.sleep(0.5)

# =========================================
# INDICATEURS
# =========================================

def get_candles(pair, interval=60, count=250):
    try:
        r = requests.get(
            "https://api.kraken.com/0/public/OHLC",
            params={"pair": pair, "interval": interval},
            timeout=10
        )
        d = r.json()["result"]
        k = [x for x in d if x != "last"][0]
        rows = d[k][-count:]
        return {
            "o": [float(x[1]) for x in rows],
            "h": [float(x[2]) for x in rows],
            "l": [float(x[3]) for x in rows],
            "c": [float(x[4]) for x in rows],
            "v": [float(x[6]) for x in rows],
            "t": [int(x[0])   for x in rows]   # timestamps
        }
    except:
        return None

def ema(c, n):
    if len(c) < n: return c[-1]
    k = 2 / (n + 1)
    e = sum(c[:n]) / n
    for p in c[n:]: e = p * k + e * (1 - k)
    return e

def rsi(c, n=14):
    g = l = 0.0
    for i in range(len(c) - n, len(c)):
        d = c[i] - c[i - 1]
        if d > 0: g += d
        else:     l -= d
    return 100 - 100 / (1 + g / (l or 0.001))

def macd(c): return ema(c, 12) - ema(c, 26)

def atr(h, l, c, n=14):
    trs = [
        max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
        for i in range(1, len(c))
    ]
    return sum(trs[-n:]) / n

def atr_avg(h, l, c, n=14, periods=5):
    """ATR moyen sur plusieurs périodes pour détecter volatilité anormale"""
    results = []
    for i in range(periods):
        offset = i * n
        if offset + n >= len(c): break
        trs = [
            max(h[j] - l[j], abs(h[j] - c[j-1]), abs(l[j] - c[j-1]))
            for j in range(max(1, len(c)-offset-n), len(c)-offset)
        ]
        if trs:
            results.append(sum(trs) / len(trs))
    return sum(results) / len(results) if results else atr(h, l, c, n)

def rsi_divergence(c):
    if len(c) < 30: return "NONE"
    r1 = rsi(c[-30:-15])
    r2 = rsi(c[-15:])
    if c[-1] < c[-15] and r2 > r1: return "BULL"
    if c[-1] > c[-15] and r2 < r1: return "BEAR"
    return "NONE"

def detect_regime(h, l, c, h4_c):
    atr_v    = atr(h, l, c)
    atr_mean = atr_avg(h, l, c)
    e50      = ema(c, 50)
    e200     = ema(c, 100)
    price    = c[-1]
    atr_ratio = atr_v / atr_mean if atr_mean > 0 else 1
    e50_h4   = ema(h4_c, 50)
    e200_h4  = ema(h4_c, 100)
    trend_h4 = "BULL" if e50_h4 > e200_h4 else "BEAR"
    range_size = (max(h[-20:]) - min(l[-20:])) / price

    if atr_ratio > 2.0:    return "INSTABLE", trend_h4   # CORRECTION 4 — seuil abaissé à 2x
    if range_size < 0.005: return "RANGE", trend_h4      # CORRECTION 2 — RANGE détecté
    if e50 > e200:         return "TREND_BULL", trend_h4
    if e50 < e200:         return "TREND_BEAR", trend_h4
    return "NEUTRAL", trend_h4

def swing_points(h, l, lb=5):
    sh, sl = [], []
    for i in range(lb, len(h) - lb):
        if all(h[i] >= h[i-j] for j in range(1, lb+1)) and all(h[i] >= h[i+j] for j in range(1, lb+1)):
            sh.append((i, h[i]))
        if all(l[i] <= l[i-j] for j in range(1, lb+1)) and all(l[i] <= l[i+j] for j in range(1, lb+1)):
            sl.append((i, l[i]))
    return sh, sl

def detect_order_blocks(o, h, l, c, lb=30):
    bull, bear = [], []
    for i in range(max(1, len(c) - lb), len(c) - 1):
        if c[i] < o[i] and c[i+1] > h[i]:
            bull.append({"h": h[i], "l": l[i], "mid": (h[i]+l[i])/2})
        if c[i] > o[i] and c[i+1] < l[i]:
            bear.append({"h": h[i], "l": l[i], "mid": (h[i]+l[i])/2})
    return bull[-3:], bear[-3:]

def detect_fvg(h, l, lb=30):
    bull, bear = [], []
    for i in range(max(0, len(h) - lb), len(h) - 2):
        if l[i+2] > h[i]:
            bull.append({"top": l[i+2], "bot": h[i], "mid": (l[i+2]+h[i])/2})
        if h[i+2] < l[i]:
            bear.append({"top": l[i], "bot": h[i+2], "mid": (l[i]+h[i+2])/2})
    return bull[-3:], bear[-3:]

def sweep_low(h, l, c):
    sh, sl = swing_points(h, l)
    return sl and l[-1] < sl[-1][1] and c[-1] > sl[-1][1]

def sweep_high(h, l, c):
    sh, sl = swing_points(h, l)
    return sh and h[-1] > sh[-1][1] and c[-1] < sh[-1][1]

def in_ob(price, obs):
    return any(ob["l"] <= price <= ob["h"] for ob in obs)

def near_fvg(price, fvgs, thr=0.002):
    return any(abs(price - f["mid"]) / price < thr for f in fvgs)

# =========================================
# NEWS FILTER
# =========================================

def get_news():
    try:
        r = requests.get(
            "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
            timeout=10
        )
        events = r.json()
        now    = datetime.now(timezone.utc)
        result = []
        for e in events:
            if e.get("impact") in ["High", "Medium"]:
                try:
                    from datetime import datetime as dt
                    et   = dt.strptime(e["date"], "%Y-%m-%dT%H:%M:%S%z")
                    diff = (et - now).total_seconds() / 60
                    if -30 <= diff <= 60:
                        result.append({
                            "title":  e.get("title", ""),
                            "cur":    e.get("country", ""),
                            "impact": e.get("impact", ""),
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
    blocking = [e for e in events if any(c in e["cur"].upper() for c in curs) and e["impact"] == "High"]
    return len(blocking) > 0, blocking

# =========================================
# CORRECTION 6 — COOLDOWN PAR PAIRE
# =========================================

def is_pair_in_cooldown(pair_name):
    """Vérifie si la paire est bloquée après un signal récent"""
    if pair_name not in pair_cooldowns:
        return False
    now = datetime.now(timezone.utc)
    if now < pair_cooldowns[pair_name]:
        remaining = int((pair_cooldowns[pair_name] - now).total_seconds() / 60)
        print(f"[COOLDOWN] {pair_name} bloqué encore {remaining} min")
        return True
    else:
        del pair_cooldowns[pair_name]
        return False

def set_pair_cooldown(pair_name):
    """Bloque une paire pendant SIGNAL_COOLDOWN secondes"""
    pair_cooldowns[pair_name] = datetime.now(timezone.utc) + timedelta(seconds=SIGNAL_COOLDOWN)
    print(f"[COOLDOWN] {pair_name} bloqué pour 4h")

# =========================================
# ANALYSE PRINCIPALE
# =========================================

def analyze(pair):
    brain     = load_data()
    min_score = brain["params"]["min_score"]
    risk_pct  = brain["params"]["risk_pct"]

    H4  = get_candles(pair["kraken"], 240, 150)
    H1  = get_candles(pair["kraken"], 60,  250)
    M15 = get_candles(pair["kraken"], 15,  100)

    if not H4 or not H1 or not M15:
        return None

    # CORRECTION 3 — Utiliser la bougie FERMÉE (avant-dernière, index -2)
    # La dernière bougie (index -1) est en cours de formation
    c = H1["c"][:-1]   # On retire la dernière bougie ouverte
    h = H1["h"][:-1]
    l = H1["l"][:-1]
    o = H1["o"][:-1]

    if len(c) < 50:
        return None

    price  = c[-1]   # Prix de clôture de la dernière bougie fermée
    is_jpy = "JPY" in pair["name"]
    dec    = 3 if is_jpy else 5

    # REGIME
    regime, trend_h4 = detect_regime(h, l, c, H4["c"])

    # CORRECTION 2 — Bloquer RANGE et INSTABLE
    if regime in ["INSTABLE", "RANGE", "NEUTRAL"]:
        print(f"[SKIP] {pair['name']} regime={regime}")
        return None

    # CORRECTION 5 — H4 et H1 doivent être alignés
    # TREND_BULL sur H1 → H4 doit être BULL
    # TREND_BEAR sur H1 → H4 doit être BEAR
    if regime == "TREND_BULL" and trend_h4 != "BULL":
        print(f"[SKIP] {pair['name']} H1=BULL mais H4={trend_h4} — pas aligné")
        return None
    if regime == "TREND_BEAR" and trend_h4 != "BEAR":
        print(f"[SKIP] {pair['name']} H1=BEAR mais H4={trend_h4} — pas aligné")
        return None

    # CORRECTION 4 — Filtre volatilité ATR
    atr_v    = atr(h, l, c)
    atr_mean = atr_avg(h, l, c)
    atr_ratio = atr_v / atr_mean if atr_mean > 0 else 1
    if atr_ratio > 2.0:
        print(f"[SKIP] {pair['name']} ATR trop élevé ({atr_ratio:.1f}x normale)")
        return None

    regime_key    = regime.replace("TREND_BULL", "TREND").replace("TREND_BEAR", "TREND")
    regime_weight = brain["params"]["regime_weights"].get(regime_key, 1.0)

    # INDICATEURS
    e9   = ema(c, 9);  e21  = ema(c, 21)
    e50  = ema(c, 50); e200 = ema(c, 100)
    e9p  = ema(c[:-1], 9); e21p = ema(c[:-1], 21)
    r    = rsi(c)
    m    = macd(c)
    rdiv = rsi_divergence(c)

    e9_m15  = ema(M15["c"][:-1], 9)
    e21_m15 = ema(M15["c"][:-1], 21)
    e9_m15p = ema(M15["c"][:-2], 9)
    e21_m15p = ema(M15["c"][:-2], 21)
    r_m15   = rsi(M15["c"][:-1])

    bull_ob, bear_ob   = detect_order_blocks(o, h, l, c)
    bull_fvg, bear_fvg = detect_fvg(h, l)
    sw_low_  = sweep_low(h, l, c)
    sw_high_ = sweep_high(h, l, c)
    in_bull  = in_ob(price, bull_ob)
    in_bear  = in_ob(price, bear_ob)
    nr_bull  = near_fvg(price, bull_fvg)
    nr_bear  = near_fvg(price, bear_fvg)
    cross_up = e9p <= e21p and e9 > e21
    cross_dn = e9p >= e21p and e9 < e21
    m15_up   = e9_m15p <= e21_m15p and e9_m15 > e21_m15
    m15_dn   = e9_m15p >= e21_m15p and e9_m15 < e21_m15

    # SCORE BUY
    bs = 0; br = []
    if trend_h4 == "BULL":    bs += 2; br.append("H4 haussier")
    if e9 > e21 and e21 > e50: bs += 2; br.append("EMA alignees hausse")
    if cross_up:               bs += 1; br.append("Croisement EMA bull")
    if m15_up:                 bs += 1; br.append("M15 confirmation")
    if sw_low_:                bs += 2; br.append("Sweep liquidite bas")
    if in_bull:                bs += 2; br.append("Order Block haussier")
    if nr_bull:                bs += 1; br.append("FVG haussier")
    if r < 35:                 bs += 1; br.append(f"RSI survendu ({r:.1f})")
    if rdiv == "BULL":         bs += 1; br.append("Divergence RSI bull")
    if m > 0:                  bs += 1; br.append("MACD positif")
    if price > e200:           bs += 1; br.append("Au-dessus EMA200")
    if r_m15 > 50:             bs += 1; br.append("RSI M15 > 50")

    # SCORE SELL
    ss = 0; sr = []
    if trend_h4 == "BEAR":    ss += 2; sr.append("H4 baissier")
    if e9 < e21 and e21 < e50: ss += 2; sr.append("EMA alignees baisse")
    if cross_dn:               ss += 1; sr.append("Croisement EMA bear")
    if m15_dn:                 ss += 1; sr.append("M15 confirmation")
    if sw_high_:               ss += 2; sr.append("Sweep liquidite haut")
    if in_bear:                ss += 2; sr.append("Order Block baissier")
    if nr_bear:                ss += 1; sr.append("FVG baissier")
    if r > 65:                 ss += 1; sr.append(f"RSI surachete ({r:.1f})")
    if rdiv == "BEAR":         ss += 1; sr.append("Divergence RSI bear")
    if m < 0:                  ss += 1; sr.append("MACD negatif")
    if price < e200:           ss += 1; sr.append("En-dessous EMA200")
    if r_m15 < 50:             ss += 1; sr.append("RSI M15 < 50")

    # Application du poids de régime
    bs_w = int(bs * regime_weight)
    ss_w = int(ss * regime_weight)

    # Détermination signal
    if bs_w >= min_score and bs_w > ss_w:
        signal = "BUY";  score = bs_w; reasons = br
    elif ss_w >= min_score and ss_w > bs_w:
        signal = "SELL"; score = ss_w; reasons = sr
    else:
        return None

    # CALCUL SL / TP
    sh_pts, sl_pts = swing_points(h, l)
    if signal == "BUY":
        sl  = min(sl_pts[-1][1] - atr_v * 0.5 if sl_pts else price - atr_v * 1.5, price - atr_v * 1.5)
        tp1 = price + (price - sl) * 2
        tp2 = price + (price - sl) * 3
    else:
        sl  = max(sh_pts[-1][1] + atr_v * 0.5 if sh_pts else price + atr_v * 1.5, price + atr_v * 1.5)
        tp1 = price - (sl - price) * 2
        tp2 = price - (sl - price) * 3

    sl_pips = abs(price - sl) / (0.01 if is_jpy else 0.0001)
    lot     = round(max(0.01, min(CAPITAL * risk_pct / 100 / (sl_pips * 10), 2.0)), 2)

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

# =========================================
# BOUCLE PRINCIPALE
# =========================================

def trading_loop():
    global current_signal

    send_telegram(
        "🤖 ARBI BOT CERVEAU v3.0 DEMARRE\n"
        "============================\n"
        "✅ Score min: 7 (plancher: 6)\n"
        "✅ RANGE bloqué\n"
        "✅ Bougie fermée uniquement\n"
        "✅ Filtre ATR volatilité\n"
        "✅ H4 + H1 alignés obligatoire\n"
        "✅ Cooldown 4h anti-contradiction\n"
        "============================\n"
        "En attente de setups de qualité..."
    )

    while True:
        # FILTRE WEEK-END
        if is_weekend():
            current_signal = {"signal": "NONE", "pair": "", "timestamp": str(datetime.now())}
            time.sleep(1800)
            continue

        # FILTRE SESSION
        sess_name, sess_active = get_session()
        if not sess_active:
            current_signal = {"signal": "NONE", "pair": "", "timestamp": str(datetime.now())}
            time.sleep(600)
            continue

        brain = load_data()

        for pair in PAIRS:
            try:
                # CORRECTION 6 — Vérifier cooldown avant tout
                if is_pair_in_cooldown(pair["name"]):
                    continue

                # FILTRE NEWS
                blocked, news = is_news_blocked(pair["name"])
                if blocked:
                    key = pair["name"] + str([n["title"] for n in news])
                    if last_news_alert.get(pair["name"]) != key:
                        last_news_alert[pair["name"]] = key
                        msg = f"⛔ NEWS ROUGE — {pair['name']}\n"
                        for n in news:
                            msg += f"• {n['title']} dans {n['mins']}min\n"
                        msg += "Trade bloqué !"
                        send_telegram(msg)
                    continue

                # ANALYSE
                result = analyze(pair)
                if not result:
                    continue

                sig = result["signal"]

                # Éviter le même signal en doublon
                last = last_signals.get(pair["name"], {})
                if last.get("signal") == sig:
                    continue

                # Mettre à jour le dernier signal
                last_signals[pair["name"]] = {"signal": sig, "time": datetime.now()}

                # CORRECTION 6 — Activer le cooldown sur cette paire
                set_pair_cooldown(pair["name"])

                # Mettre à jour le signal courant pour le copieur
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

                # FORMAT MESSAGE TELEGRAM
                dec = result["dec"]
                msg  = f"{'BUY' if sig == 'BUY' else 'SELL'} {result['pair']}\n"
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
                msg += "Signal envoye a Bot 2 (Copieur)"

                send_telegram(msg)
                print(f"[SIGNAL] {result['pair']} {sig} score={result['score']} regime={result['regime']}")

            except Exception as e:
                print(f"[ERREUR] {pair['name']}: {e}")

            time.sleep(3)

        time.sleep(300)  # Attendre 5 min avant prochain scan

# =========================================
# MAIN
# =========================================

if __name__ == "__main__":
    bot_thread = Thread(target=trading_loop, daemon=True)
    bot_thread.start()
    port = int(os.environ.get("PORT", 5000))
    print(f"[START] Serveur Flask sur port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
