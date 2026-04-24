#!/usr/bin/env python3

# coding: utf-8

# ARBI FOREX BOT PRO v6 - INSTITUTIONNEL

# Smart Money Concepts + News Trading + Multi-Timeframe

# Logique : D1 > H4 > H1 > M15

import requests
import time
from datetime import datetime, timezone, timedelta

# —————————————————————

# CONFIGURATION

# —————————————————————

TOKEN   = “8636672541:AAElNEq4IKwrRzTLuqoaqttadmkGKAVEVlM”
IDS     = [“525011337”, “7276558677”]

PAIRS = [
{“name”: “EUR/USD”, “kraken”: “EURUSD”,  “pip”: 0.0001, “pip_val”: 10},
{“name”: “GBP/USD”, “kraken”: “GBPUSD”,  “pip”: 0.0001, “pip_val”: 10},
{“name”: “USD/JPY”, “kraken”: “USDJPY”,  “pip”: 0.01,   “pip_val”: 9},
{“name”: “XAU/USD”, “kraken”: “XAUUSD”,  “pip”: 0.1,    “pip_val”: 1},
]

CAPITAL    = 10000
RISK_PCT   = 1.0
MAX_TRADES = 3
SCAN_INTERVAL = 300  # 5 minutes

# Etat global

last_signals = {}
open_pos     = {}
daily        = {“date”: “”, “count”: 0, “losses”: 0}
last_news_alert = {}

# —————————————————————

# TELEGRAM

# —————————————————————

def send(msg):
for cid in IDS:
try:
requests.post(
f”https://api.telegram.org/bot{TOKEN}/sendMessage”,
json={“chat_id”: cid, “text”: msg, “parse_mode”: “HTML”},
timeout=10
)
except Exception as e:
print(f”[TELEGRAM ERROR] {e}”)
time.sleep(0.3)

# —————————————————————

# DONNEES MARCHE - KRAKEN

# —————————————————————

def ohlc(pair, interval=60, count=200):
try:
r = requests.get(
“https://api.kraken.com/0/public/OHLC”,
params={“pair”: pair, “interval”: interval},
timeout=10
)
d = r.json()[“result”]
k = [x for x in d if x != “last”][0]
rows = d[k][-count:]
return {
“o”: [float(x[1]) for x in rows],
“h”: [float(x[2]) for x in rows],
“l”: [float(x[3]) for x in rows],
“c”: [float(x[4]) for x in rows],
“v”: [float(x[6]) for x in rows],
}
except Exception as e:
print(f”[OHLC ERROR] {pair} {interval}m : {e}”)
return None

# —————————————————————

# INDICATEURS TECHNIQUES

# —————————————————————

def ema(c, n):
if len(c) < n:
return c[-1]
k = 2 / (n + 1)
e = sum(c[:n]) / n
for p in c[n:]:
e = p * k + e * (1 - k)
return e

def rsi(c, n=14):
if len(c) < n + 1:
return 50
g = l = 0.0
for i in range(len(c) - n, len(c)):
d = c[i] - c[i - 1]
if d > 0:
g += d
else:
l -= d
return 100 - 100 / (1 + g / (l or 0.001))

def rsi_divergence(c):
if len(c) < 40:
return “NONE”
r1 = rsi(c[-40:-20])
r2 = rsi(c[-20:])
p1 = min(c[-40:-20])
p2 = min(c[-20:])
ph1 = max(c[-40:-20])
ph2 = max(c[-20:])
if p2 < p1 and r2 > r1:
return “BULL_DIV”
if ph2 > ph1 and r2 < r1:
return “BEAR_DIV”
return “NONE”

def macd(c):
if len(c) < 26:
return 0
return ema(c, 12) - ema(c, 26)

def macd_signal(c):
if len(c) < 35:
return 0, 0
# Calcul MACD complet avec signal line
macd_vals = []
for i in range(26, len(c)):
m = ema(c[:i], 12) - ema(c[:i], 26)
macd_vals.append(m)
if len(macd_vals) < 9:
return macd_vals[-1] if macd_vals else 0, 0
sig = ema(macd_vals, 9)
return macd_vals[-1], sig

def bollinger(c, n=20):
if len(c) < n:
return c[-1], c[-1], c[-1]
s = c[-n:]
m = sum(s) / len(s)
std = (sum((x - m) ** 2 for x in s) / len(s)) ** 0.5
return m + 2 * std, m - 2 * std, m

def atr(h, l, c, n=14):
if len(c) < n + 1:
return (h[-1] - l[-1])
trs = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
for i in range(1, len(c))]
return sum(trs[-n:]) / n

def stoch(h, l, c, n=14):
if len(c) < n:
return 50
hi = max(h[-n:])
lo = min(l[-n:])
return 100 * (c[-1] - lo) / (hi - lo) if hi != lo else 50

def volume_spike(v, n=20):
if len(v) < n + 1:
return False
avg = sum(v[-n-1:-1]) / n
return v[-1] > avg * 1.5

# —————————————————————

# SMART MONEY CONCEPTS

# —————————————————————

def swing_points(h, l, lb=5):
sh, sl = [], []
for i in range(lb, len(h) - lb):
if all(h[i] >= h[i - j] for j in range(1, lb + 1)) and   
all(h[i] >= h[i + j] for j in range(1, lb + 1)):
sh.append((i, h[i]))
if all(l[i] <= l[i - j] for j in range(1, lb + 1)) and   
all(l[i] <= l[i + j] for j in range(1, lb + 1)):
sl.append((i, l[i]))
return sh, sl

def market_structure(h, l, c):
sh, sl = swing_points(h, l)
if len(sh) < 2 or len(sl) < 2:
return “NEUTRAL”, “NONE”, “NONE”
hh = sh[-1][1] > sh[-2][1]
hl = sl[-1][1] > sl[-2][1]
lh = sh[-1][1] < sh[-2][1]
ll = sl[-1][1] < sl[-2][1]
if hh and hl:
struct = “BULLISH”
elif lh and ll:
struct = “BEARISH”
else:
struct = “NEUTRAL”
price = c[-1]
bos   = “NONE”
choch = “NONE”
if struct == “BULLISH” and price > sh[-1][1]:
bos = “BOS_BULL”
if struct == “BEARISH” and price < sl[-1][1]:
bos = “BOS_BEAR”
if struct == “BULLISH” and price < sl[-1][1]:
choch = “CHOCH_BEAR”
if struct == “BEARISH” and price > sh[-1][1]:
choch = “CHOCH_BULL”
return struct, bos, choch

def order_blocks(o, h, l, c, lb=50):
bull_obs, bear_obs = [], []
start = max(1, len(c) - lb)
for i in range(start, len(c) - 1):
if c[i] < o[i] and c[i + 1] > h[i]:
bull_obs.append({“h”: h[i], “l”: l[i], “mid”: (h[i] + l[i]) / 2, “idx”: i})
if c[i] > o[i] and c[i + 1] < l[i]:
bear_obs.append({“h”: h[i], “l”: l[i], “mid”: (h[i] + l[i]) / 2, “idx”: i})
return bull_obs[-3:], bear_obs[-3:]

def fair_value_gaps(h, l, lb=50):
bull_fvg, bear_fvg = [], []
start = max(0, len(h) - lb)
for i in range(start, len(h) - 2):
if l[i + 2] > h[i]:
bull_fvg.append({“top”: l[i + 2], “bot”: h[i], “mid”: (l[i + 2] + h[i]) / 2})
if h[i + 2] < l[i]:
bear_fvg.append({“top”: l[i], “bot”: h[i + 2], “mid”: (l[i] + h[i + 2]) / 2})
return bull_fvg[-3:], bear_fvg[-3:]

def liquidity_sweep(h, l, c):
sh, sl = swing_points(h, l)
if not sh or not sl:
return False, False
prev  = c[-2]
price = c[-1]
swept_high = prev > sh[-1][1] and price < sh[-1][1]
swept_low  = prev < sl[-1][1] and price > sl[-1][1]
return swept_high, swept_low

def candle_pattern(o, h, l, c):
if len(c) < 3:
return “NONE”
body     = abs(c[-1] - o[-1])
rng      = h[-1] - l[-1]
if rng == 0:
return “NONE”
low_wick = min(o[-1], c[-1]) - l[-1]
up_wick  = h[-1] - max(o[-1], c[-1])
if low_wick > body * 2 and up_wick < body * 0.5:
return “BULL_PIN”
if up_wick > body * 2 and low_wick < body * 0.5:
return “BEAR_PIN”
if len(c) >= 2:
if c[-1] > o[-1] and c[-2] < o[-2] and   
c[-1] > o[-2] and o[-1] < c[-2] and body / rng > 0.6:
return “BULL_ENGULF”
if c[-1] < o[-1] and c[-2] > o[-2] and   
c[-1] < o[-2] and o[-1] > c[-2] and body / rng > 0.6:
return “BEAR_ENGULF”
return “NONE”

def price_in_ob(price, obs):
for ob in obs:
if ob[“l”] <= price <= ob[“h”]:
return True
return False

def price_near_fvg(price, fvgs, thr=0.0025):
for fvg in fvgs:
if abs(price - fvg[“mid”]) / price < thr:
return True
return False

def nearest_ob(price, obs, direction):
“”“Trouve l’OB le plus proche du prix dans la bonne direction”””
best = None
best_dist = 999999
for ob in obs:
if direction == “BULL” and ob[“mid”] < price:
dist = price - ob[“mid”]
if dist < best_dist:
best_dist = dist
best = ob
if direction == “BEAR” and ob[“mid”] > price:
dist = ob[“mid”] - price
if dist < best_dist:
best_dist = dist
best = ob
return best

# —————————————————————

# CALENDRIER ECONOMIQUE - LOGIQUE PRO

# —————————————————————

def get_news():
try:
r = requests.get(
“https://nfs.faireconomy.media/ff_calendar_thisweek.json”,
timeout=10
)
return r.json()
except:
return []

def classify_news_for_pair(pair_name, events):
“””
Analyse les news et retourne :
- status : “CLEAR”, “WAIT”, “TRADE_AFTER”, “AVOID”
- context : description de la situation
- bias : “BULL”, “BEAR”, “NONE” base sur consensus attendu
“””
now = datetime.now(timezone.utc)

```
# Devises concernees par la paire
curs = []
if "EUR" in pair_name: curs.append("EUR")
if "GBP" in pair_name: curs.append("GBP")
if "JPY" in pair_name: curs.append("JPY")
if "XAU" in pair_name: curs += ["USD", "XAU"]
curs.append("USD")

upcoming_high   = []  # News rouge a venir (< 45 min)
upcoming_medium = []  # News orange a venir (< 30 min)
just_released   = []  # News venant de sortir (< 15 min)
recent_high     = []  # News rouge recente (15-60 min)

for e in events:
    impact = e.get("impact", "")
    cur    = e.get("country", "").upper()

    if not any(c in cur for c in curs):
        continue
    if impact not in ["High", "Medium"]:
        continue

    try:
        et   = datetime.strptime(e["date"], "%Y-%m-%dT%H:%M:%S%z")
        diff = (et - now).total_seconds() / 60  # minutes

        if impact == "High":
            if 0 < diff <= 45:
                upcoming_high.append({**e, "mins": int(diff)})
            elif -15 <= diff <= 0:
                just_released.append({**e, "mins": int(diff)})
            elif -60 <= diff < -15:
                recent_high.append({**e, "mins": int(diff)})
        elif impact == "Medium":
            if 0 < diff <= 20:
                upcoming_medium.append({**e, "mins": int(diff)})

    except:
        pass

# LOGIQUE DE DECISION :

# 1. News rouge imminente (<45 min) -> attendre
if upcoming_high:
    n = upcoming_high[0]
    return {
        "status":  "WAIT",
        "reason":  f"News ROUGE dans {n['mins']}min : {n.get('title','?')} ({n.get('country','?')})",
        "action":  "Attendre la sortie puis trader la reaction",
        "bias":    "NONE",
        "events":  upcoming_high
    }

# 2. News rouge vient de sortir (<15 min) -> opportunite de trade la reaction
if just_released:
    n = just_released[0]
    # Essayer de determiner le biais base sur le titre
    title = n.get("title", "").upper()
    bias  = "NONE"
    # NFP, CPI, GDP positif = bullish USD
    if any(w in title for w in ["NFP", "CPI", "GDP", "RATE", "PMI"]):
        actual   = n.get("actual", "")
        forecast = n.get("forecast", "")
        if actual and forecast:
            try:
                a = float(actual.replace("K","000").replace("%","").replace("B","").strip())
                f = float(forecast.replace("K","000").replace("%","").replace("B","").strip())
                if a > f:
                    bias = "USD_STRONG"  # bullish USD
                elif a < f:
                    bias = "USD_WEAK"    # bearish USD
            except:
                pass
    return {
        "status":  "TRADE_AFTER",
        "reason":  f"News ROUGE sortie il y a {abs(int(n['mins']))}min : {n.get('title','?')}",
        "action":  "Trader la reaction - confirmer direction sur M15",
        "bias":    bias,
        "events":  just_released
    }

# 3. News rouge recente (15-60 min) -> marche en digestion, trade possible avec confirmation
if recent_high:
    n = recent_high[0]
    return {
        "status":  "TRADE_AFTER",
        "reason":  f"Post-news ROUGE ({abs(int(n['mins']))}min) : {n.get('title','?')}",
        "action":  "Marche en digestion - confirmer tendance",
        "bias":    "NONE",
        "events":  recent_high
    }

# 4. News orange imminente (<20 min) -> prudence mais pas blocage total
if upcoming_medium:
    n = upcoming_medium[0]
    return {
        "status":  "CAUTION",
        "reason":  f"News ORANGE dans {n['mins']}min : {n.get('title','?')}",
        "action":  "Trade possible mais reduire lot de 50%",
        "bias":    "NONE",
        "events":  upcoming_medium
    }

# 5. Tout est calme
return {
    "status":  "CLEAR",
    "reason":  "Aucune news impactante",
    "action":  "Trading normal",
    "bias":    "NONE",
    "events":  []
}
```

# —————————————————————

# SESSION DE TRADING

# —————————————————————

def session():
h = datetime.now(timezone.utc).hour
if 7  <= h < 12: return “🇬🇧 Londres”,       True,  1.0
if 12 <= h < 16: return “🇬🇧🇺🇸 London+NY”,  True,  1.2   # overlap = bonus
if 16 <= h < 21: return “🇺🇸 New York”,       True,  1.0
if 2  <= h <  5: return “🇯🇵 Tokyo”,           True,  0.7   # OK pour JPY
return “😴 Hors session”, False, 0

# —————————————————————

# GESTION DU RISQUE

# —————————————————————

def lot_size(sl_pips, pip_val=10, reduce=1.0):
risk = CAPITAL * RISK_PCT / 100 * reduce
lot  = risk / (sl_pips * pip_val) if sl_pips > 0 else 0.01
return round(max(0.01, min(lot, 2.0)), 2)

def daily_ok():
today = datetime.now().strftime(”%Y-%m-%d”)
if daily[“date”] != today:
daily.update({“date”: today, “count”: 0, “losses”: 0})
if daily[“count”] >= MAX_TRADES:
return False, f”Max {MAX_TRADES} trades/jour atteint”
if daily[“losses”] >= 2:
return False, “2 pertes consecutives - pause trading”
return True, “OK”

# —————————————————————

# ANALYSE PRINCIPALE

# —————————————————————

def analyze(pair_name, kraken_pair, news_ctx, session_mult):
# Recuperer les donnees multi-timeframe
D1  = ohlc(kraken_pair, 1440, 60)
H4  = ohlc(kraken_pair, 240,  100)
H1  = ohlc(kraken_pair, 60,   200)
M15 = ohlc(kraken_pair, 15,   150)
M5  = ohlc(kraken_pair, 5,    100)

```
if not H4 or not H1 or not M15:
    return None

price = H1["c"][-1]
dec   = 3 if "JPY" in pair_name else (1 if "XAU" in pair_name else 5)

# ── TENDANCE D1 ──
struct_d1 = "NEUTRAL"
if D1:
    struct_d1, _, _ = market_structure(D1["h"], D1["l"], D1["c"])

# ── INDICATEURS H4 ──
e50_h4  = ema(H4["c"], 50)
e200_h4 = ema(H4["c"], 100)
struct_h4, bos_h4, choch_h4 = market_structure(H4["h"], H4["l"], H4["c"])

# ── INDICATEURS H1 ──
e50   = ema(H1["c"], 50)
e200  = ema(H1["c"], 100)
r     = rsi(H1["c"])
rdiv  = rsi_divergence(H1["c"])
m, ms = macd_signal(H1["c"])
macd_cross_bull = m > ms and macd(H1["c"][:-1]) < 0  # croisement haussier
macd_cross_bear = m < ms and macd(H1["c"][:-1]) > 0  # croisement baissier
bb_u, bb_l, bb_m = bollinger(H1["c"])
atr_v  = atr(H1["h"], H1["l"], H1["c"])
sto    = stoch(H1["h"], H1["l"], H1["c"])
vol_sp = volume_spike(H1["v"])
candle = candle_pattern(H1["o"], H1["h"], H1["l"], H1["c"])

# ── SMC H1 ──
struct_h1, bos_h1, choch_h1 = market_structure(H1["h"], H1["l"], H1["c"])
bull_ob, bear_ob = order_blocks(H1["o"], H1["h"], H1["l"], H1["c"])
bull_fvg, bear_fvg = fair_value_gaps(H1["h"], H1["l"])
swept_high, swept_low = liquidity_sweep(H1["h"], H1["l"], H1["c"])
in_bull_ob   = price_in_ob(price, bull_ob)
in_bear_ob   = price_in_ob(price, bear_ob)
near_bull_fvg = price_near_fvg(price, bull_fvg)
near_bear_fvg = price_near_fvg(price, bear_fvg)

# ── SMC M15 (confirmation entree) ──
struct_m15, bos_m15, choch_m15 = market_structure(M15["h"], M15["l"], M15["c"])
candle_m15 = candle_pattern(M15["o"], M15["h"], M15["l"], M15["c"])
swept_high_m15, swept_low_m15 = liquidity_sweep(M15["h"], M15["l"], M15["c"])

# ── BIAIS NEWS ──
news_bias = news_ctx.get("bias", "NONE")

# ----------------------------------
# SCORING ACHAT (MAX = 30)
# ----------------------------------
bull_score   = 0
bull_reasons = []

# Tendance macro (poids fort)
if struct_d1 == "BULLISH":
    bull_score += 3
    bull_reasons.append("D1 tendance haussiere 📈")
if struct_h4 == "BULLISH":
    bull_score += 2
    bull_reasons.append("H4 structure HH+HL")
if struct_h1 == "BULLISH":
    bull_score += 2
    bull_reasons.append("H1 structure haussiere")
if price > e200_h4:
    bull_score += 1
    bull_reasons.append("Prix > EMA200 H4")

# Smart Money
if swept_low:
    bull_score += 3
    bull_reasons.append("⚡ Sweep liquidite bas H1 -> retournement")
if swept_low_m15:
    bull_score += 2
    bull_reasons.append("⚡ Sweep liquidite bas M15")
if in_bull_ob:
    bull_score += 3
    bull_reasons.append("🟩 Prix dans Order Block haussier")
if near_bull_fvg:
    bull_score += 2
    bull_reasons.append("🔵 Prix proche FVG haussier")
if bos_h1 == "BOS_BULL":
    bull_score += 2
    bull_reasons.append("Break of Structure haussier H1")
if choch_m15 == "CHOCH_BULL":
    bull_score += 2
    bull_reasons.append("Change of Character bullish M15")

# Indicateurs techniques
if r < 35:
    bull_score += 2
    bull_reasons.append(f"RSI survendu {r:.0f}")
if rdiv == "BULL_DIV":
    bull_score += 2
    bull_reasons.append("Divergence RSI haussiere")
if macd_cross_bull:
    bull_score += 2
    bull_reasons.append("MACD croisement haussier")
elif m > 0:
    bull_score += 1
    bull_reasons.append("MACD positif")
if price < bb_l:
    bull_score += 2
    bull_reasons.append("Prix sous BB basse -> rebond")
if sto < 20:
    bull_score += 2
    bull_reasons.append(f"Stochastique survendu {sto:.0f}")
if price > e50:
    bull_score += 1
    bull_reasons.append("Prix > EMA50")
if candle in ["BULL_PIN", "BULL_ENGULF"]:
    bull_score += 2
    bull_reasons.append(f"Pattern bougie : {candle}")
if candle_m15 in ["BULL_PIN", "BULL_ENGULF"]:
    bull_score += 1
    bull_reasons.append(f"Pattern M15 : {candle_m15}")
if vol_sp:
    bull_score += 1
    bull_reasons.append("Spike volume confirme")

# Biais news
if news_bias == "USD_WEAK" and "USD" in pair_name:
    bull_score += 2
    bull_reasons.append("📰 News : USD faible -> favorable ACHAT")
if news_bias == "USD_STRONG" and pair_name in ["EUR/USD", "GBP/USD", "XAU/USD"]:
    bull_score -= 2  # Contre le biais

# ----------------------------------
# SCORING VENTE (MAX = 30)
# ----------------------------------
bear_score   = 0
bear_reasons = []

if struct_d1 == "BEARISH":
    bear_score += 3
    bear_reasons.append("D1 tendance baissiere 📉")
if struct_h4 == "BEARISH":
    bear_score += 2
    bear_reasons.append("H4 structure LH+LL")
if struct_h1 == "BEARISH":
    bear_score += 2
    bear_reasons.append("H1 structure baissiere")
if price < e200_h4:
    bear_score += 1
    bear_reasons.append("Prix < EMA200 H4")

if swept_high:
    bear_score += 3
    bear_reasons.append("⚡ Sweep liquidite haut H1 -> retournement")
if swept_high_m15:
    bear_score += 2
    bear_reasons.append("⚡ Sweep liquidite haut M15")
if in_bear_ob:
    bear_score += 3
    bear_reasons.append("🟥 Prix dans Order Block baissier")
if near_bear_fvg:
    bear_score += 2
    bear_reasons.append("🔴 Prix proche FVG baissier")
if bos_h1 == "BOS_BEAR":
    bear_score += 2
    bear_reasons.append("Break of Structure baissier H1")
if choch_m15 == "CHOCH_BEAR":
    bear_score += 2
    bear_reasons.append("Change of Character bearish M15")

if r > 65:
    bear_score += 2
    bear_reasons.append(f"RSI surachet e {r:.0f}")
if rdiv == "BEAR_DIV":
    bear_score += 2
    bear_reasons.append("Divergence RSI baissiere")
if macd_cross_bear:
    bear_score += 2
    bear_reasons.append("MACD croisement baissier")
elif m < 0:
    bear_score += 1
    bear_reasons.append("MACD negatif")
if price > bb_u:
    bear_score += 2
    bear_reasons.append("Prix au-dessus BB haute -> rejet")
if sto > 80:
    bear_score += 2
    bear_reasons.append(f"Stochastique surachete {sto:.0f}")
if price < e50:
    bear_score += 1
    bear_reasons.append("Prix < EMA50")
if candle in ["BEAR_PIN", "BEAR_ENGULF"]:
    bear_score += 2
    bear_reasons.append(f"Pattern bougie : {candle}")
if candle_m15 in ["BEAR_PIN", "BEAR_ENGULF"]:
    bear_score += 1
    bear_reasons.append(f"Pattern M15 : {candle_m15}")
if vol_sp:
    bear_score += 1
    bear_reasons.append("Spike volume confirme")

if news_bias == "USD_STRONG" and pair_name in ["EUR/USD", "GBP/USD", "XAU/USD"]:
    bear_score += 2
    bear_reasons.append("📰 News : USD fort -> favorable VENTE")
if news_bias == "USD_WEAK" and "USD" in pair_name:
    bear_score -= 2

# ----------------------------------
# SIGNAL FINAL - Seuil 10/30
# ----------------------------------
MAX_SCORE = 30
THRESHOLD = 10  # Seuil assoupli mais garde la qualite

# Si on est en mode TRADE_AFTER (post-news) -> baisser le seuil legerement
if news_ctx["status"] == "TRADE_AFTER":
    THRESHOLD = 9

if bull_score >= THRESHOLD and bull_score > bear_score:
    signal  = "ACHAT"
    score   = bull_score
    reasons = bull_reasons
elif bear_score >= THRESHOLD and bear_score > bull_score:
    signal  = "VENTE"
    score   = bear_score
    reasons = bear_reasons
else:
    return None

confidence = min(95, int(score / MAX_SCORE * 100))

# ── SL/TP STRUCTUREL ──
sh_pts, sl_pts = swing_points(H1["h"], H1["l"])
atr_mult = 1.5

if signal == "ACHAT":
    sl_struct = sl_pts[-1][1] - atr_v * 0.3 if sl_pts else price - atr_v * atr_mult
    sl  = min(sl_struct, price - atr_v * atr_mult)
    tp1 = price + (price - sl) * 1.5
    tp2 = price + (price - sl) * 2.5
    tp3 = price + (price - sl) * 4.0
else:
    sl_struct = sh_pts[-1][1] + atr_v * 0.3 if sh_pts else price + atr_v * atr_mult
    sl  = max(sl_struct, price + atr_v * atr_mult)
    tp1 = price - (sl - price) * 1.5
    tp2 = price - (sl - price) * 2.5
    tp3 = price - (sl - price) * 4.0

pip_size = 0.01 if "JPY" in pair_name else (0.1 if "XAU" in pair_name else 0.0001)
sl_pips  = abs(price - sl) / pip_size
pip_val  = next((p["pip_val"] for p in PAIRS if p["name"] == pair_name), 10)

# Reduire lot si news orange ou session faible
lot_mult = 0.5 if news_ctx["status"] == "CAUTION" else 1.0
lot_mult *= session_mult
lot      = lot_size(sl_pips, pip_val, lot_mult)

return {
    "signal":     signal,
    "score":      score,
    "max_score":  MAX_SCORE,
    "confidence": confidence,
    "price":      price,
    "sl":         sl,
    "tp1":        tp1,
    "tp2":        tp2,
    "tp3":        tp3,
    "sl_pips":    sl_pips,
    "lot":        lot,
    "rsi":        r,
    "stoch":      sto,
    "macd":       m,
    "struct_d1":  struct_d1,
    "struct_h4":  struct_h4,
    "struct_h1":  struct_h1,
    "struct_m15": struct_m15,
    "atr":        atr_v,
    "candle":     candle,
    "vol_spike":  vol_sp,
    "reasons":    reasons[:8],
    "dec":        dec,
    "news_ctx":   news_ctx,
}
```

# —————————————————————

# FORMATAGE DU MESSAGE TELEGRAM

# —————————————————————

def format_signal(result, pair_name, sess_name):
sig  = result[“signal”]
dec  = result[“dec”]
conf = result[“confidence”]
news = result[“news_ctx”]

```
icon  = "🟢 BUY" if sig == "ACHAT" else "🔴 SELL"
stars = "⭐" * (1 + conf // 25)

msg  = f"{icon} - {pair_name} {stars}\n"
msg += "━━━━━━━━━━━━━━━━━━━━━━\n"
msg += f"💰 Prix    : {result['price']:.{dec}f}\n"
msg += f"🛑 SL      : {result['sl']:.{dec}f} ({result['sl_pips']:.0f} pips)\n"
msg += f"🎯 TP1     : {result['tp1']:.{dec}f} (R:R 1:1.5)\n"
msg += f"🎯 TP2     : {result['tp2']:.{dec}f} (R:R 1:2.5)\n"
msg += f"🎯 TP3     : {result['tp3']:.{dec}f} (R:R 1:4)\n"
msg += f"📦 Lot     : {result['lot']}\n"
msg += "━━━━━━━━━━━━━━━━━━━━━━\n"
msg += f"📊 Confiance : {conf}%  ({result['score']}/{result['max_score']})\n"
msg += f"🕐 Session   : {sess_name}\n"
msg += f"📈 D1  : {result['struct_d1']}\n"
msg += f"📈 H4  : {result['struct_h4']}\n"
msg += f"📈 H1  : {result['struct_h1']}\n"
msg += f"📈 M15 : {result['struct_m15']}\n"
msg += f"📉 RSI : {result['rsi']:.0f} | Stoch : {result['stoch']:.0f}\n"
if result["candle"] != "NONE":
    msg += f"🕯️ Bougie : {result['candle']}\n"
if result["vol_spike"]:
    msg += "📢 Volume spike detecte\n"

# Contexte news
if news["status"] != "CLEAR":
    msg += "━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"📰 NEWS : {news['reason']}\n"
    msg += f"-> {news['action']}\n"

msg += "━━━━━━━━━━━━━━━━━━━━━━\n"
msg += "💡 Confluences SMC :\n"
for r in result["reasons"]:
    msg += f"  • {r}\n"
msg += "━━━━━━━━━━━━━━━━━━━━━━\n"
msg += f"⚠️ Risque : 1% | Signal indicatif\n"
msg += "Gere ton MM - trade prudemment 🧠"

return msg
```

# —————————————————————

# VERIFICATION PAR PAIRE

# —————————————————————

def check(pair, news_events):
name = pair[“name”]

```
# 1. Session
sess_name, active, sess_mult = session()
if not active:
    return

# 2. Limites quotidiennes
ok, reason = daily_ok()
if not ok:
    return

# 3. Analyser les news pour cette paire (logique pro)
news_ctx = classify_news_for_pair(name, news_events)

# Si WAIT -> bloquer ET alerter une seule fois
if news_ctx["status"] == "WAIT":
    alert_key = name + news_ctx["reason"]
    if last_news_alert.get(name) != alert_key:
        last_news_alert[name] = alert_key
        msg  = f"⏸️ PAUSE - {name}\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━\n"
        msg += f"📰 {news_ctx['reason']}\n"
        msg += f"-> {news_ctx['action']}\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━\n"
        msg += "Je surveille et t'envoie le signal apres la news 👀"
        send(msg)
    return
else:
    last_news_alert[name] = None  # Reset

# 4. Analyse technique complete
result = analyze(name, pair["kraken"], news_ctx, sess_mult)
if not result:
    return

sig = result["signal"]

# 5. Anti-contradiction avec position ouverte
current = open_pos.get(name)
if current and current != sig:
    send(f"🔄 RETOURNEMENT {name}\n❌ Ferme ta position {current}\n✅ Nouveau signal : {sig}")

# 6. Eviter doublons (meme signal dans les 4h)
sig_key = f"{name}_{sig}"
if last_signals.get(sig_key):
    return

last_signals[sig_key] = True
open_pos[name]         = sig
daily["count"]        += 1

# Envoyer le signal formate
msg = format_signal(result, name, sess_name)
send(msg)
print(f"[{datetime.now().strftime('%H:%M')}] ✅ Signal {name} {sig} conf={result['confidence']}%")
```

# —————————————————————

# RESET SIGNAUX (toutes les 4h)

# —————————————————————

last_reset = datetime.now()

def maybe_reset_signals():
global last_reset
if (datetime.now() - last_reset).seconds > 14400:  # 4h
last_signals.clear()
last_reset = datetime.now()
print(”[RESET] Signaux reinitialises”)

# —————————————————————

# DEMARRAGE

# —————————————————————

now_str = datetime.now().strftime(”%d/%m/%Y %H:%M”)
send(
f”🚀 ARBI BOT PRO v6 - {now_str}\n”
f”━━━━━━━━━━━━━━━━━━━━━━\n”
f”🏦 Niveau : Institutionnel SMC\n”
f”💱 Paires : EUR/USD | GBP/USD | USD/JPY | XAU/USD\n”
f”📊 Analyse : D1 -> H4 -> H1 -> M15\n”
f”📰 News : Logique Pro (trade la reaction)\n”
f”🎯 Seuil signal : 10/30 confluences\n”
f”💰 Capital : {CAPITAL}$ | Risque : {RISK_PCT}%\n”
f”━━━━━━━━━━━━━━━━━━━━━━\n”
f”En surveillance… Les signaux arrivent 👀”
)
print(“✅ ArbiBot Pro v6 demarre”)

while True:
try:
# Recuperer les news une fois par cycle (pas par paire)
news_events = get_news()

```
    for p in PAIRS:
        try:
            check(p, news_events)
        except Exception as e:
            print(f"[ERROR] {p['name']}: {e}")
        time.sleep(2)

    maybe_reset_signals()
    print(f"[{datetime.now().strftime('%H:%M')}] Cycle termine - prochaine analyse dans 5min")
    time.sleep(SCAN_INTERVAL)

except KeyboardInterrupt:
    print("Bot arrete manuellement")
    break
except Exception as e:
    print(f"[ERREUR GLOBALE] {e}")
    time.sleep(60)
```
