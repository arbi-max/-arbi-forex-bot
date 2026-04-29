import requests
import time
import os
import json
from datetime import datetime, timezone, timedelta

TOKEN = os.environ.get("TOKEN", "")
IDS = ["525011337", "7276558677"]

PAIRS = [
    dict(name="EUR/USD", kraken="EURUSD", pip=0.0001, pip_val=10, usd_side="quote"),
    dict(name="GBP/USD", kraken="GBPUSD", pip=0.0001, pip_val=10, usd_side="quote"),
    dict(name="USD/JPY", kraken="USDJPY", pip=0.01,   pip_val=9,  usd_side="base"),
    dict(name="XAU/USD", kraken="PAXGUSD", pip=0.1,   pip_val=1,  usd_side="quote"),
]

CORRELATED = [("EUR/USD", "GBP/USD")]

CAPITAL    = 10000
RISK_PCT   = 1.0
MAX_TRADES = 3
SCAN_INTERVAL = 300
STATS_FILE = "stats.json"

last_signals    = {}
open_positions  = {}
daily           = dict(date="", count=0, losses=0)
last_news_alert = {}
last_reset      = datetime.now()
last_daily_recap = ""
last_weekly_recap = ""

def load_stats():
    try:
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    except:
        return dict(trades=[])

def save_stats(s):
    try:
        with open(STATS_FILE, "w") as f:
            json.dump(s, f)
    except Exception as e:
        print("Stats save error: " + str(e))

def add_trade(pair, side, entry, exit_price, result_pips, status):
    s = load_stats()
    s["trades"].append(dict(
        date=datetime.now().strftime("%Y-%m-%d"),
        time=datetime.now().strftime("%H:%M"),
        pair=pair, side=side, entry=entry, exit=exit_price,
        pips=result_pips, status=status))
    save_stats(s)

def send(msg):
    for cid in IDS:
        try:
            url = "https://api.telegram.org/bot" + TOKEN + "/sendMessage"
            requests.post(url, json=dict(chat_id=cid, text=msg), timeout=10)
        except Exception as e:
            print("Telegram error: " + str(e))
        time.sleep(0.3)

def candles(pair, interval=60, count=200):
    try:
        url = "https://api.kraken.com/0/public/OHLC"
        r = requests.get(url, params=dict(pair=pair, interval=interval), timeout=10)
        d = r.json()["result"]
        k = [x for x in d if x != "last"][0]
        data = d[k][-count:]
        return dict(
            o=[float(c[1]) for c in data],
            h=[float(c[2]) for c in data],
            l=[float(c[3]) for c in data],
            c=[float(c[4]) for c in data],
            v=[float(c[6]) for c in data],
        )
    except Exception as e:
        print("OHLC error " + pair + ": " + str(e))
        return None

def dxy_bias():
    try:
        eurusd = candles("EURUSD", 60, 50)
        gbpusd = candles("GBPUSD", 60, 50)
        usdjpy = candles("USDJPY", 60, 50)
        if not eurusd or not gbpusd or not usdjpy:
            return 0
        e_chg = (eurusd["c"][-1] - eurusd["c"][-24]) / eurusd["c"][-24]
        g_chg = (gbpusd["c"][-1] - gbpusd["c"][-24]) / gbpusd["c"][-24]
        j_chg = (usdjpy["c"][-1] - usdjpy["c"][-24]) / usdjpy["c"][-24]
        usd_strength = (-e_chg) + (-g_chg) + j_chg
        if usd_strength > 0.005:
            return 1
        if usd_strength < -0.005:
            return -1
        return 0
    except Exception as e:
        print("DXY error: " + str(e))
        return 0

def ema(closes, n):
    if len(closes) < n:
        return closes[-1]
    k = 2.0 / (n + 1)
    e = sum(closes[:n]) / n
    for p in closes[n:]:
        e = p * k + e * (1 - k)
    return e

def rsi(closes, n=14):
    if len(closes) < n + 1:
        return 50
    g = 0.0
    lo = 0.0
    for i in range(len(closes) - n, len(closes)):
        d = closes[i] - closes[i - 1]
        if d > 0:
            g += d
        else:
            lo -= d
    return 100 - 100 / (1 + g / (lo or 0.001))

def rsi_div(closes):
    if len(closes) < 40:
        return 0
    r1 = rsi(closes[-40:-20])
    r2 = rsi(closes[-20:])
    if min(closes[-20:]) < min(closes[-40:-20]) and r2 > r1:
        return 1
    if max(closes[-20:]) > max(closes[-40:-20]) and r2 < r1:
        return -1
    return 0

def macd(closes):
    if len(closes) < 26:
        return 0
    return ema(closes, 12) - ema(closes, 26)

def bollinger(closes, n=20):
    if len(closes) < n:
        return closes[-1], closes[-1], closes[-1]
    s = closes[-n:]
    mid = sum(s) / len(s)
    std = (sum((x - mid) ** 2 for x in s) / len(s)) ** 0.5
    return mid + 2 * std, mid - 2 * std, mid

def stoch(highs, lows, closes, n=14):
    if len(closes) < n:
        return 50
    h = max(highs[-n:])
    l = min(lows[-n:])
    if h == l:
        return 50
    return 100 * (closes[-1] - l) / (h - l)

def atr(highs, lows, closes, n=14):
    if len(closes) < n + 1:
        return highs[-1] - lows[-1]
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
    return sum(trs[-n:]) / n

def vol_spike(v, n=20):
    if len(v) < n + 1:
        return False
    avg = sum(v[-n-1:-1]) / n
    return v[-1] > avg * 1.5

def swings(highs, lows, lb=5):
    sh = []
    sl = []
    for i in range(lb, len(highs) - lb):
        if all(highs[i] >= highs[i-j] for j in range(1, lb+1)) and all(highs[i] >= highs[i+j] for j in range(1, lb+1)):
            sh.append((i, highs[i]))
        if all(lows[i] <= lows[i-j] for j in range(1, lb+1)) and all(lows[i] <= lows[i+j] for j in range(1, lb+1)):
            sl.append((i, lows[i]))
    return sh, sl

def structure(highs, lows, closes):
    sh, sl = swings(highs, lows)
    if len(sh) < 2 or len(sl) < 2:
        return 0, 0, 0
    hh = sh[-1][1] > sh[-2][1]
    hl = sl[-1][1] > sl[-2][1]
    lh = sh[-1][1] < sh[-2][1]
    ll = sl[-1][1] < sl[-2][1]
    if hh and hl:
        st = 1
    elif lh and ll:
        st = -1
    else:
        st = 0
    price = closes[-1]
    bos = 0
    choch = 0
    if st == 1 and price > sh[-1][1]:
        bos = 1
    if st == -1 and price < sl[-1][1]:
        bos = -1
    if st == 1 and price < sl[-1][1]:
        choch = -1
    if st == -1 and price > sh[-1][1]:
        choch = 1
    return st, bos, choch

def order_blocks(opens, highs, lows, closes, lb=50):
    bull = []
    bear = []
    start = max(1, len(closes) - lb)
    for i in range(start, len(closes) - 1):
        if closes[i] < opens[i] and closes[i+1] > highs[i]:
            bull.append(dict(h=highs[i], l=lows[i], mid=(highs[i]+lows[i])/2))
        if closes[i] > opens[i] and closes[i+1] < lows[i]:
            bear.append(dict(h=highs[i], l=lows[i], mid=(highs[i]+lows[i])/2))
    return bull[-3:], bear[-3:]

def fair_value_gaps(highs, lows, lb=50):
    bull = []
    bear = []
    start = max(0, len(highs) - lb)
    for i in range(start, len(highs) - 2):
        if lows[i+2] > highs[i]:
            bull.append(dict(mid=(lows[i+2]+highs[i])/2))
        if highs[i+2] < lows[i]:
            bear.append(dict(mid=(lows[i]+highs[i+2])/2))
    return bull[-3:], bear[-3:]

def sweep(highs, lows, closes):
    sh, sl = swings(highs, lows)
    if not sh or not sl:
        return 0, 0
    prev = closes[-2]
    price = closes[-1]
    sh_val = 1 if (prev > sh[-1][1] and price < sh[-1][1]) else 0
    sl_val = 1 if (prev < sl[-1][1] and price > sl[-1][1]) else 0
    return sh_val, sl_val

def in_ob(price, obs):
    for x in obs:
        if x["l"] <= price <= x["h"]:
            return True
    return False

def near_fvg(price, fvgs, thr=0.0025):
    for x in fvgs:
        if abs(price - x["mid"]) / price < thr:
            return True
    return False

def candle_pat(opens, highs, lows, closes):
    if len(closes) < 2:
        return "NONE"
    body = abs(closes[-1] - opens[-1])
    rng = highs[-1] - lows[-1]
    if rng == 0:
        return "NONE"
    lw = min(opens[-1], closes[-1]) - lows[-1]
    uw = highs[-1] - max(opens[-1], closes[-1])
    if lw > body * 2 and uw < body * 0.5:
        return "BULL_PIN"
    if uw > body * 2 and lw < body * 0.5:
        return "BEAR_PIN"
    if closes[-1] > opens[-1] and closes[-2] < opens[-2] and closes[-1] > opens[-2] and opens[-1] < closes[-2] and body/rng > 0.6:
        return "BULL_ENG"
    if closes[-1] < opens[-1] and closes[-2] > opens[-2] and closes[-1] < opens[-2] and opens[-1] > closes[-2] and body/rng > 0.6:
        return "BEAR_ENG"
    return "NONE"

def kill_zone():
    h = datetime.now(timezone.utc).hour
    m = datetime.now(timezone.utc).minute
    t = h * 60 + m
    if 420 <= t <= 600:
        return "London Kill Zone", 1.3
    if 780 <= t <= 960:
        return "NY Kill Zone", 1.3
    if 600 <= t <= 780:
        return "London+NY Overlap", 1.2
    if 120 <= t <= 300:
        return "Tokyo Session", 0.8
    return "Hors session", 0.6

def get_news():
    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        r = requests.get(url, timeout=10)
        return r.json()
    except:
        return []

def classify_news(pair_name, events):
    now = datetime.now(timezone.utc)
    curs = ["USD"]
    if "EUR" in pair_name: curs.append("EUR")
    if "GBP" in pair_name: curs.append("GBP")
    if "JPY" in pair_name: curs.append("JPY")
    uh = []; jr = []; rh = []; um = []
    for e in events:
        impact = e.get("impact", "")
        cur = e.get("country", "").upper()
        if not any(c in cur for c in curs): continue
        if impact not in ["High", "Medium"]: continue
        try:
            et = datetime.strptime(e["date"], "%Y-%m-%dT%H:%M:%S%z")
            diff = (et - now).total_seconds() / 60
            title = e.get("title", "")
            country = e.get("country", "")
            actual   = e.get("actual", "")
            forecast = e.get("forecast", "")
            if impact == "High":
                if 0 < diff <= 45: uh.append(dict(title=title, country=country, mins=int(diff)))
                elif -15 <= diff <= 0: jr.append(dict(title=title, country=country, mins=int(diff), actual=actual, forecast=forecast))
                elif -60 <= diff < -15: rh.append(dict(title=title, country=country, mins=int(diff)))
            elif impact == "Medium":
                if 0 < diff <= 20: um.append(dict(title=title, country=country, mins=int(diff)))
        except: pass
    if uh:
        n = uh[0]
        return dict(status=1, reason="News ROUGE dans " + str(n["mins"]) + "min : " + n["title"], action="Attendre puis trader la reaction", bias=0)
    if jr:
        n = jr[0]
        bias = 0
        try:
            a = float(n["actual"].replace("K","000").replace("%","").strip())
            f = float(n["forecast"].replace("K","000").replace("%","").strip())
            if a > f: bias = 1
            elif a < f: bias = -1
        except: pass
        return dict(status=2, reason="News sortie il y a " + str(abs(n["mins"])) + "min : " + n["title"], action="Trader la reaction - confirmer M15", bias=bias)
    if rh:
        n = rh[0]
        return dict(status=2, reason="Post-news " + str(abs(n["mins"])) + "min : " + n["title"], action="Marche en digestion", bias=0)
    if um:
        n = um[0]
        return dict(status=3, reason="News ORANGE dans " + str(n["mins"]) + "min : " + n["title"], action="Lot reduit 50%", bias=0)
    return dict(status=0, reason="", action="", bias=0)

def lot_size(sl_pips, pip_val=10, mult=1.0):
    risk = CAPITAL * RISK_PCT / 100 * mult
    lot = risk / (sl_pips * pip_val) if sl_pips > 0 else 0.01
    return round(max(0.01, min(lot, 2.0)), 2)

def daily_ok():
    today = datetime.now().strftime("%Y-%m-%d")
    if daily["date"] != today:
        daily.update(dict(date=today, count=0, losses=0))
    if daily["count"] >= MAX_TRADES: return False
    if daily["losses"] >= 2: return False
    return True

def correlated_blocked(pair_name, sig):
    for a, b in CORRELATED:
        other = b if pair_name == a else (a if pair_name == b else None)
        if not other: continue
        op = open_positions.get(other)
        if op is not None:
            other_sig = op["sig"] if isinstance(op, dict) else op
            if other_sig == sig:
                return True
    return False

def analyze(pair_name, kraken_pair, nc, kz_mult, dxy, usd_side):
    D1  = candles(kraken_pair, 1440, 60)
    H4  = candles(kraken_pair, 240, 100)
    H1  = candles(kraken_pair, 60, 200)
    M15 = candles(kraken_pair, 15, 150)
    if not H4 or not H1 or not M15: return None
    price = H1["c"][-1]
    dec = 3 if "JPY" in pair_name else (1 if "XAU" in pair_name else 5)
    sd1 = 0
    if D1: sd1, _, _ = structure(D1["h"], D1["l"], D1["c"])
    e200h4 = ema(H4["c"], 100)
    sh4, _, _ = structure(H4["h"], H4["l"], H4["c"])
    sh1, bh1, _ = structure(H1["h"], H1["l"], H1["c"])
    sm15, _, ch15 = structure(M15["h"], M15["l"], M15["c"])
    e9  = ema(H1["c"], 9)
    e21 = ema(H1["c"], 21)
    e50 = ema(H1["c"], 50)
    rv  = rsi(H1["c"])
    rd  = rsi_div(H1["c"])
    mv  = macd(H1["c"])
    bbu, bbl, _ = bollinger(H1["c"])
    atrv = atr(H1["h"], H1["l"], H1["c"])
    stv  = stoch(H1["h"], H1["l"], H1["c"])
    vsp  = vol_spike(H1["v"])
    cv   = candle_pat(H1["o"], H1["h"], H1["l"], H1["c"])
    bob, beb = order_blocks(H1["o"], H1["h"], H1["l"], H1["c"])
    bfv, bfb = fair_value_gaps(H1["h"], H1["l"])
    swh, swl = sweep(H1["h"], H1["l"], H1["c"])
    swh15, swl15 = sweep(M15["h"], M15["l"], M15["c"])
    cv15 = candle_pat(M15["o"], M15["h"], M15["l"], M15["c"])
    bs = 0; br = []
    if sd1 == 1:    bs += 3; br.append("D1 haussier")
    if sh4 == 1:    bs += 2; br.append("H4 HH+HL")
    if sh1 == 1:    bs += 2; br.append("H1 haussier")
    if price > e200h4: bs += 1; br.append("Prix > EMA200 H4")
    if swl:         bs += 3; br.append("Sweep liquidite bas H1")
    if swl15:       bs += 2; br.append("Sweep liquidite bas M15")
    if in_ob(price, bob): bs += 3; br.append("Order Block haussier")
    if near_fvg(price, bfv): bs += 2; br.append("FVG haussier")
    if bh1 == 1:    bs += 2; br.append("BOS haussier H1")
    if ch15 == 1:   bs += 2; br.append("CHoCH bullish M15")
    if rv < 35:     bs += 2; br.append("RSI survendu " + str(round(rv,1)))
    if rd == 1:     bs += 2; br.append("Divergence RSI bull")
    if mv > 0:      bs += 1; br.append("MACD positif")
    if price < bbl: bs += 2; br.append("Prix sous BB basse")
    if stv < 20:    bs += 2; br.append("Stoch survendu " + str(round(stv,1)))
    if price > e50: bs += 1; br.append("Prix > EMA50")
    if e9 > e21:    bs += 1; br.append("EMA9 > EMA21")
    if cv in ["BULL_PIN", "BULL_ENG"]: bs += 2; br.append("Bougie : " + cv)
    if cv15 in ["BULL_PIN", "BULL_ENG"]: bs += 1; br.append("Bougie M15 : " + cv15)
    if vsp:         bs += 1; br.append("Volume spike")
    if nc["status"] == 2: bs += 1; br.append("Post-news opportunite")
    # DXY context: if pair has USD as quote (EURUSD, GBPUSD, XAUUSD), USD weak (-1) = bullish
    if usd_side == "quote" and dxy == -1: bs += 2; br.append("USD faible (DXY)")
    if usd_side == "base" and dxy == 1: bs += 2; br.append("USD fort (DXY)")
    if nc["bias"] == 1 and "USD" in pair_name: bs += 1; br.append("Biais news USD fort")
    ss = 0; sr = []
    if sd1 == -1:   ss += 3; sr.append("D1 baissier")
    if sh4 == -1:   ss += 2; sr.append("H4 LH+LL")
    if sh1 == -1:   ss += 2; sr.append("H1 baissier")
    if price < e200h4: ss += 1; sr.append("Prix < EMA200 H4")
    if swh:         ss += 3; sr.append("Sweep liquidite haut H1")
    if swh15:       ss += 2; sr.append("Sweep liquidite haut M15")
    if in_ob(price, beb): ss += 3; sr.append("Order Block baissier")
    if near_fvg(price, bfb): ss += 2; sr.append("FVG baissier")
    if bh1 == -1:   ss += 2; sr.append("BOS baissier H1")
    if ch15 == -1:  ss += 2; sr.append("CHoCH bearish M15")
    if rv > 65:     ss += 2; sr.append("RSI surachete " + str(round(rv,1)))
    if rd == -1:    ss += 2; sr.append("Divergence RSI bear")
    if mv < 0:      ss += 1; sr.append("MACD negatif")
    if price > bbu: ss += 2; sr.append("Prix > BB haute")
    if stv > 80:    ss += 2; sr.append("Stoch surachete " + str(round(stv,1)))
    if price < e50: ss += 1; sr.append("Prix < EMA50")
    if e9 < e21:    ss += 1; sr.append("EMA9 < EMA21")
    if cv in ["BEAR_PIN", "BEAR_ENG"]: ss += 2; sr.append("Bougie : " + cv)
    if cv15 in ["BEAR_PIN", "BEAR_ENG"]: ss += 1; sr.append("Bougie M15 : " + cv15)
    if vsp:         ss += 1; sr.append("Volume spike")
    if nc["status"] == 2: ss += 1; sr.append("Post-news opportunite")
    if usd_side == "quote" and dxy == 1: ss += 2; sr.append("USD fort (DXY)")
    if usd_side == "base" and dxy == -1: ss += 2; sr.append("USD faible (DXY)")
    if nc["bias"] == -1 and "USD" in pair_name: ss += 1; sr.append("Biais news USD faible")
    THRESH = 12
    MAX = 34
    if bs >= THRESH and bs > ss:
        sig = 1; sc = bs; reasons = br
    elif ss >= THRESH and ss > bs:
        sig = -1; sc = ss; reasons = sr
    else:
        return None
    conf = min(95, int(sc / MAX * 100))
    sh_pts, sl_pts = swings(H1["h"], H1["l"])
    if sig == 1:
        sl_s = sl_pts[-1][1] - atrv * 0.3 if sl_pts else price - atrv * 1.5
        sl = min(sl_s, price - atrv * 1.5)
        tp1 = price + (price - sl) * 1.5
    else:
        sl_s = sh_pts[-1][1] + atrv * 0.3 if sh_pts else price + atrv * 1.5
        sl = max(sl_s, price + atrv * 1.5)
        tp1 = price - (sl - price) * 1.5
    pip_size = 0.01 if "JPY" in pair_name else (0.1 if "XAU" in pair_name else 0.0001)
    sl_pips = abs(price - sl) / pip_size
    pv = next((p["pip_val"] for p in PAIRS if p["name"] == pair_name), 10)
    lm = 0.5 if nc["status"] == 3 else 1.0
    lv = lot_size(sl_pips, pv, lm * kz_mult)
    sh4_txt = "BULLISH" if sh4 == 1 else ("BEARISH" if sh4 == -1 else "NEUTRAL")
    return dict(sig=sig, sc=sc, MAX=MAX, conf=conf, price=price, sl=sl,
                tp1=tp1, sl_pips=sl_pips, lot=lv,
                rsi=rv, stoch=stv, sh4=sh4_txt,
                cv=cv, vsp=vsp, reasons=reasons[:8], dec=dec, nc=nc)

def check(pair, events, dxy):
    name = pair["name"]
    if not daily_ok(): return
    nc = classify_news(name, events)
    if nc["status"] == 1:
        key = name + nc["reason"]
        if last_news_alert.get(name) != key:
            last_news_alert[name] = key
            send("PAUSE " + name + chr(10) + nc["reason"] + chr(10) + nc["action"])
        return
    last_news_alert[name] = None
    kz_name, kz_mult = kill_zone()
    if kz_mult < 0.7: return
    res = analyze(name, pair["kraken"], nc, kz_mult, dxy, pair["usd_side"])
    if not res: return
    sig = res["sig"]
    sig_txt = "ACHAT" if sig == 1 else "VENTE"
    if correlated_blocked(name, sig):
        return
    cur = open_positions.get(name)
    cur_sig = cur["sig"] if isinstance(cur, dict) else cur
    if cur_sig and cur_sig != sig:
        cur_txt = "ACHAT" if cur_sig == 1 else "VENTE"
        send("RETOURNEMENT " + name + chr(10) + "Ferme " + cur_txt + chr(10) + "Nouveau : " + sig_txt)
    key = name + str(sig)
    if last_signals.get(key): return
    last_signals[key] = True
    open_positions[name] = dict(sig=sig, entry=res["price"], sl=res["sl"], tp=res["tp1"], opened=datetime.now().isoformat())
    daily["count"] += 1
    dec = res["dec"]
    icon = "BUY" if sig == 1 else "SELL"
    nc_info = res["nc"]
    msg = icon + " SIGNAL " + sig_txt + " - " + name + chr(10)
    msg += "========================" + chr(10)
    msg += "Prix  : " + str(round(res["price"], dec)) + chr(10)
    msg += "SL    : " + str(round(res["sl"], dec)) + " (" + str(round(res["sl_pips"])) + " pips)" + chr(10)
    msg += "TP    : " + str(round(res["tp1"], dec)) + chr(10)
    msg += "Ratio : 1:1.5" + chr(10)
    msg += "========================" + chr(10)
    msg += "RSI     : " + str(round(res["rsi"],1)) + chr(10)
    msg += "Stoch   : " + str(round(res["stoch"],1)) + chr(10)
    msg += "H4      : " + res["sh4"] + chr(10)
    msg += "Session : " + kz_name + chr(10)
    msg += "Score   : " + str(res["sc"]) + "/" + str(res["MAX"]) + chr(10)
    msg += "Confiance: " + str(res["conf"]) + "%" + chr(10)
    if nc_info["status"] != 0:
        msg += "========================" + chr(10)
        msg += "NEWS : " + nc_info["reason"] + chr(10)
        msg += nc_info["action"] + chr(10)
    msg += "========================" + chr(10)
    for r in res["reasons"]:
        msg += "- " + r + chr(10)
    msg += chr(10) + "Signal indicatif - risque 1% max"
    send(msg)
    print("[" + datetime.now().strftime("%H:%M") + "] " + name + " " + sig_txt + " " + str(res["conf"]) + "%")

def check_levels():
    for name in list(open_positions.keys()):
        pos = open_positions[name]
        if not isinstance(pos, dict): continue
        pair = next((p for p in PAIRS if p["name"] == name), None)
        if not pair: continue
        m15 = candles(pair["kraken"], 15, 5)
        if not m15: continue
        last_high = m15["h"][-1]
        last_low = m15["l"][-1]
        sig = pos["sig"]
        entry = pos["entry"]
        sl = pos["sl"]
        tp = pos["tp"]
        pip_size = 0.01 if "JPY" in name else (0.1 if "XAU" in name else 0.0001)
        hit_sl = (sig == 1 and last_low <= sl) or (sig == -1 and last_high >= sl)
        hit_tp = (sig == 1 and last_high >= tp) or (sig == -1 and last_low <= tp)
        if hit_sl:
            pips = -abs(entry - sl) / pip_size
            sig_txt = "ACHAT" if sig == 1 else "VENTE"
            send("SL TOUCHE - " + name + chr(10) + "Position: " + sig_txt + chr(10) + "Entree: " + str(round(entry,5)) + chr(10) + "SL: " + str(round(sl,5)) + chr(10) + "Resultat: " + str(int(pips)) + " pips")
            add_trade(name, sig_txt, entry, sl, int(pips), "SL")
            del open_positions[name]
            daily["losses"] += 1
            for k in list(last_signals.keys()):
                if k.startswith(name): del last_signals[k]
        elif hit_tp:
            pips = abs(tp - entry) / pip_size
            sig_txt = "ACHAT" if sig == 1 else "VENTE"
            send("TP ATTEINT - " + name + chr(10) + "Position: " + sig_txt + chr(10) + "Entree: " + str(round(entry,5)) + chr(10) + "TP: " + str(round(tp,5)) + chr(10) + "Resultat: +" + str(int(pips)) + " pips")
            add_trade(name, sig_txt, entry, tp, int(pips), "TP")
            del open_positions[name]
            for k in list(last_signals.keys()):
                if k.startswith(name): del last_signals[k]

def daily_recap():
    global last_daily_recap
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    if now.hour < 22: return
    if last_daily_recap == today: return
    s = load_stats()
    todays = [t for t in s["trades"] if t["date"] == today]
    if not todays:
        last_daily_recap = today
        return
    by_pair = {}
    for t in todays:
        p = t["pair"]
        if p not in by_pair: by_pair[p] = dict(w=0, l=0, pips=0)
        if t["status"] == "TP": by_pair[p]["w"] += 1
        else: by_pair[p]["l"] += 1
        by_pair[p]["pips"] += t["pips"]
    msg = "RECAP DU JOUR - " + now.strftime("%d/%m/%Y") + chr(10)
    msg += "========================" + chr(10)
    total_pips = 0; total_w = 0; total_l = 0
    for p, d in by_pair.items():
        sign = "+" if d["pips"] >= 0 else ""
        msg += p + " : " + str(d["w"]+d["l"]) + " trades - " + str(d["w"]) + "W " + str(d["l"]) + "L - " + sign + str(d["pips"]) + " pips" + chr(10)
        total_pips += d["pips"]; total_w += d["w"]; total_l += d["l"]
    msg += "========================" + chr(10)
    total = total_w + total_l
    wr = int(100 * total_w / total) if total > 0 else 0
    sign = "+" if total_pips >= 0 else ""
    msg += "Total : " + str(total) + " trades - " + str(wr) + "% win rate" + chr(10)
    msg += "Pips  : " + sign + str(total_pips) + " pips"
    send(msg)
    last_daily_recap = today

def weekly_recap():
    global last_weekly_recap
    now = datetime.now()
    if now.weekday() != 6 or now.hour < 22: return
    week = now.strftime("%Y-W%U")
    if last_weekly_recap == week: return
    s = load_stats()
    week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    week_trades = [t for t in s["trades"] if t["date"] >= week_start]
    if not week_trades:
        last_weekly_recap = week
        return
    by_pair = {}
    for t in week_trades:
        p = t["pair"]
        if p not in by_pair: by_pair[p] = dict(w=0, l=0, pips=0)
        if t["status"] == "TP": by_pair[p]["w"] += 1
        else: by_pair[p]["l"] += 1
        by_pair[p]["pips"] += t["pips"]
    msg = "RECAP HEBDO" + chr(10)
    msg += "========================" + chr(10)
    total_pips = 0; total_w = 0; total_l = 0
    for p, d in by_pair.items():
        sign = "+" if d["pips"] >= 0 else ""
        msg += p + " : " + str(d["w"]+d["l"]) + " trades - " + str(d["w"]) + "W " + str(d["l"]) + "L - " + sign + str(d["pips"]) + " pips" + chr(10)
        total_pips += d["pips"]; total_w += d["w"]; total_l += d["l"]
    msg += "========================" + chr(10)
    total = total_w + total_l
    wr = int(100 * total_w / total) if total > 0 else 0
    sign = "+" if total_pips >= 0 else ""
    msg += "Total : " + str(total) + " trades - " + str(wr) + "% win rate" + chr(10)
    msg += "Pips  : " + sign + str(total_pips) + " pips"
    send(msg)
    last_weekly_recap = week

def reset_check():
    global last_reset
    if (datetime.now() - last_reset).seconds > 14400:
        last_signals.clear()
        last_reset = datetime.now()

now = datetime.now().strftime("%d/%m/%Y %H:%M")
send("ARBI BOT PRO v8 - " + now + chr(10) + "Paires : EUR/USD GBP/USD USD/JPY XAU/USD" + chr(10) + "Kill Zones + SMC + News Pro + DXY" + chr(10) + "Anti-correlation + Recap auto" + chr(10) + "Seuil : 12/34 confluences" + chr(10) + "Mode 100% automatique")
print("ArbiBot Pro v8 demarre")

while True:
    try:
        events = get_news()
        dxy = dxy_bias()
        for p in PAIRS:
            try:
                check(p, events, dxy)
            except Exception as e:
                print("Error " + p["name"] + ": " + str(e))
            time.sleep(2)
        check_levels()
        daily_recap()
        weekly_recap()
        reset_check()
        print("[" + datetime.now().strftime("%H:%M") + "] Cycle ok DXY=" + str(dxy))
        time.sleep(SCAN_INTERVAL)
    except KeyboardInterrupt:
        break
    except Exception as e:
        print("Erreur: " + str(e))
        time.sleep(60)
