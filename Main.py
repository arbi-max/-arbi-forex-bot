import requests
import time
import os
from datetime import datetime, timezone

TOKEN = os.environ.get(“TOKEN”, “”)
IDS = [“525011337”, “7276558677”]

PAIRS = [
{“name”: “EUR/USD”, “kraken”: “EURUSD”},
{“name”: “GBP/USD”, “kraken”: “GBPUSD”},
{“name”: “USD/JPY”, “kraken”: “USDJPY”},
{“name”: “XAU/USD”, “kraken”: “XAUUSD”},
]

CAPITAL = 10000
RISK_PCT = 1.0
MAX_TRADES = 3

last_signals = {}
open_positions = {}
daily = {“date”: “”, “count”: 0, “losses”: 0}
last_news_alert = {}
last_reset = datetime.now()

def send(msg):
for cid in IDS:
try:
requests.post(
f”https://api.telegram.org/bot{TOKEN}/sendMessage”,
json={“chat_id”: cid, “text”: msg},
timeout=10)
except Exception as e:
print(f”Telegram error: {e}”)
time.sleep(0.5)

def candles(pair, interval=60, count=200):
try:
r = requests.get(
“https://api.kraken.com/0/public/OHLC”,
params={“pair”: pair, “interval”: interval},
timeout=10)
d = r.json()[“result”]
k = [x for x in d if x != “last”][0]
data = d[k][-count:]
return {
“open”:  [float(c[1]) for c in data],
“high”:  [float(c[2]) for c in data],
“low”:   [float(c[3]) for c in data],
“close”: [float(c[4]) for c in data],
“vol”:   [float(c[6]) for c in data],
}
except Exception as e:
print(f”OHLC error {pair}: {e}”)
return None

def ema(closes, n):
if len(closes) < n:
return closes[-1]
k = 2 / (n + 1)
e = sum(closes[:n]) / n
for p in closes[n:]:
e = p * k + e * (1 - k)
return e

def rsi(closes, n=14):
g = 0.0
l = 0.0
for i in range(len(closes) - n, len(closes)):
d = closes[i] - closes[i - 1]
if d > 0:
g += d
else:
l -= d
return 100 - 100 / (1 + g / (l or 0.001))

def rsi_divergence(closes):
if len(closes) < 40:
return “NONE”
r1 = rsi(closes[-40:-20])
r2 = rsi(closes[-20:])
if min(closes[-20:]) < min(closes[-40:-20]) and r2 > r1:
return “BULL”
if max(closes[-20:]) > max(closes[-40:-20]) and r2 < r1:
return “BEAR”
return “NONE”

def macd(closes):
if len(closes) < 26:
return 0
return ema(closes, 12) - ema(closes, 26)

def bollinger(closes, n=20):
s = closes[-n:]
mid = sum(s) / len(s)
std = (sum((x - mid) ** 2 for x in s) / len(s)) ** 0.5
return mid + 2 * std, mid - 2 * std, mid

def stochastic(highs, lows, closes, n=14):
h = max(highs[-n:])
l = min(lows[-n:])
if h == l:
return 50
return 100 * (closes[-1] - l) / (h - l)

def atr(highs, lows, closes, n=14):
trs = []
for i in range(1, len(closes)):
tr = max(highs[i] - lows[i],
abs(highs[i] - closes[i - 1]),
abs(lows[i] - closes[i - 1]))
trs.append(tr)
return sum(trs[-n:]) / n

def swings(highs, lows, lb=5):
sh = []
sl = []
for i in range(lb, len(highs) - lb):
if all(highs[i] >= highs[i-j] for j in range(1, lb+1)) and   
all(highs[i] >= highs[i+j] for j in range(1, lb+1)):
sh.append((i, highs[i]))
if all(lows[i] <= lows[i-j] for j in range(1, lb+1)) and   
all(lows[i] <= lows[i+j] for j in range(1, lb+1)):
sl.append((i, lows[i]))
return sh, sl

def market_structure(highs, lows, closes):
sh, sl = swings(highs, lows)
if len(sh) < 2 or len(sl) < 2:
return “NEUTRAL”, “NONE”, “NONE”
hh = sh[-1][1] > sh[-2][1]
hl = sl[-1][1] > sl[-2][1]
lh = sh[-1][1] < sh[-2][1]
ll = sl[-1][1] < sl[-2][1]
if hh and hl:
st = “BULLISH”
elif lh and ll:
st = “BEARISH”
else:
st = “NEUTRAL”
price = closes[-1]
bos = “NONE”
choch = “NONE”
if st == “BULLISH” and price > sh[-1][1]:
bos = “BOS_BULL”
if st == “BEARISH” and price < sl[-1][1]:
bos = “BOS_BEAR”
if st == “BULLISH” and price < sl[-1][1]:
choch = “CHOCH_BEAR”
if st == “BEARISH” and price > sh[-1][1]:
choch = “CHOCH_BULL”
return st, bos, choch

def order_blocks(opens, highs, lows, closes, lb=50):
bull = []
bear = []
start = max(1, len(closes) - lb)
for i in range(start, len(closes) - 1):
if closes[i] < opens[i] and closes[i+1] > highs[i]:
bull.append({“h”: highs[i], “l”: lows[i], “mid”: (highs[i]+lows[i])/2})
if closes[i] > opens[i] and closes[i+1] < lows[i]:
bear.append({“h”: highs[i], “l”: lows[i], “mid”: (highs[i]+lows[i])/2})
return bull[-3:], bear[-3:]

def fair_value_gaps(highs, lows, lb=50):
bull = []
bear = []
start = max(0, len(highs) - lb)
for i in range(start, len(highs) - 2):
if lows[i+2] > highs[i]:
bull.append({“mid”: (lows[i+2]+highs[i])/2})
if highs[i+2] < lows[i]:
bear.append({“mid”: (lows[i]+highs[i+2])/2})
return bull[-3:], bear[-3:]

def liquidity_sweep(highs, lows, closes):
sh, sl = swings(highs, lows)
if not sh or not sl:
return False, False
prev = closes[-2]
price = closes[-1]
swept_h = prev > sh[-1][1] and price < sh[-1][1]
swept_l = prev < sl[-1][1] and price > sl[-1][1]
return swept_h, swept_l

def candle_pattern(opens, highs, lows, closes):
if len(closes) < 2:
return “NONE”
body = abs(closes[-1] - opens[-1])
rng = highs[-1] - lows[-1]
if rng == 0:
return “NONE”
lw = min(opens[-1], closes[-1]) - lows[-1]
uw = highs[-1] - max(opens[-1], closes[-1])
if lw > body * 2 and uw < body * 0.5:
return “BULL_PIN”
if uw > body * 2 and lw < body * 0.5:
return “BEAR_PIN”
if closes[-1] > opens[-1] and closes[-2] < opens[-2] and   
closes[-1] > opens[-2] and opens[-1] < closes[-2] and body/rng > 0.6:
return “BULL_ENGULF”
if closes[-1] < opens[-1] and closes[-2] > opens[-2] and   
closes[-1] < opens[-2] and opens[-1] > closes[-2] and body/rng > 0.6:
return “BEAR_ENGULF”
return “NONE”

def in_ob(price, obs):
for x in obs:
if x[“l”] <= price <= x[“h”]:
return True
return False

def near_fvg(price, fvgs, thr=0.0025):
for x in fvgs:
if abs(price - x[“mid”]) / price < thr:
return True
return False

def get_news():
try:
r = requests.get(
“https://nfs.faireconomy.media/ff_calendar_thisweek.json”,
timeout=10)
return r.json()
except:
return []

def classify_news(pair_name, events):
now = datetime.now(timezone.utc)
curs = [“USD”]
if “EUR” in pair_name: curs.append(“EUR”)
if “GBP” in pair_name: curs.append(“GBP”)
if “JPY” in pair_name: curs.append(“JPY”)
uh = []
jr = []
rh = []
um = []
for e in events:
impact = e.get(“impact”, “”)
cur = e.get(“country”, “”).upper()
if not any(c in cur for c in curs):
continue
if impact not in [“High”, “Medium”]:
continue
try:
et = datetime.strptime(e[“date”], “%Y-%m-%dT%H:%M:%S%z”)
diff = (et - now).total_seconds() / 60
title = e.get(“title”, “”)
country = e.get(“country”, “”)
if impact == “High”:
if 0 < diff <= 45:
uh.append({“title”: title, “country”: country, “mins”: int(diff)})
elif -15 <= diff <= 0:
jr.append({“title”: title, “country”: country, “mins”: int(diff)})
elif -60 <= diff < -15:
rh.append({“title”: title, “country”: country, “mins”: int(diff)})
elif impact == “Medium”:
if 0 < diff <= 20:
um.append({“title”: title, “country”: country, “mins”: int(diff)})
except:
pass
if uh:
n = uh[0]
return {“status”: “WAIT”, “reason”: f”News ROUGE dans {n[‘mins’]}min : {n[‘title’]}”, “action”: “Attendre puis trader la reaction”}
if jr:
n = jr[0]
return {“status”: “AFTER”, “reason”: f”News sortie il y a {abs(n[‘mins’])}min : {n[‘title’]}”, “action”: “Trader la reaction - confirmer M15”}
if rh:
n = rh[0]
return {“status”: “AFTER”, “reason”: f”Post-news {abs(n[‘mins’])}min : {n[‘title’]}”, “action”: “Marche en digestion”}
if um:
n = um[0]
return {“status”: “CAUTION”, “reason”: f”News ORANGE dans {n[‘mins’]}min : {n[‘title’]}”, “action”: “Lot reduit 50%”}
return {“status”: “CLEAR”, “reason”: “”, “action”: “”}

def session():
h = datetime.now(timezone.utc).hour
if 7 <= h < 12: return “Londres”, True, 1.0
if 12 <= h < 16: return “LDN+NY”, True, 1.2
if 16 <= h < 21: return “New York”, True, 1.0
if 2 <= h < 5: return “Tokyo”, True, 0.7
return “Ferme”, False, 0

def lot_size(sl_pips, pip_val=10, mult=1.0):
risk = CAPITAL * RISK_PCT / 100 * mult
lot = risk / (sl_pips * pip_val) if sl_pips > 0 else 0.01
return round(max(0.01, min(lot, 2.0)), 2)

def daily_ok():
today = datetime.now().strftime(”%Y-%m-%d”)
if daily[“date”] != today:
daily.update({“date”: today, “count”: 0, “losses”: 0})
if daily[“count”] >= MAX_TRADES:
return False
if daily[“losses”] >= 2:
return False
return True

def analyze(pair_name, kraken_pair, nc, sess_mult):
D1  = candles(kraken_pair, 1440, 60)
H4  = candles(kraken_pair, 240, 100)
H1  = candles(kraken_pair, 60, 200)
M15 = candles(kraken_pair, 15, 150)
if not H4 or not H1 or not M15:
return None
price = H1[“close”][-1]
dec = 3 if “JPY” in pair_name else (1 if “XAU” in pair_name else 5)
sd1 = “NEUTRAL”
if D1:
sd1, _, _ = market_structure(D1[“high”], D1[“low”], D1[“close”])
e200h4 = ema(H4[“close”], 100)
sh4, _, _ = market_structure(H4[“high”], H4[“low”], H4[“close”])
sh1, bh1, _ = market_structure(H1[“high”], H1[“low”], H1[“close”])
sm15, _, ch15 = market_structure(M15[“high”], M15[“low”], M15[“close”])
e9  = ema(H1[“close”], 9)
e21 = ema(H1[“close”], 21)
e50 = ema(H1[“close”], 50)
rv  = rsi(H1[“close”])
rd  = rsi_divergence(H1[“close”])
mv  = macd(H1[“close”])
bbu, bbl, _ = bollinger(H1[“close”])
atrv = atr(H1[“high”], H1[“low”], H1[“close”])
stv  = stochastic(H1[“high”], H1[“low”], H1[“close”])
cv   = candle_pattern(H1[“open”], H1[“high”], H1[“low”], H1[“close”])
bob, beb = order_blocks(H1[“open”], H1[“high”], H1[“low”], H1[“close”])
bfv, bfb = fair_value_gaps(H1[“high”], H1[“low”])
swh, swl = liquidity_sweep(H1[“high”], H1[“low”], H1[“close”])
swh15, swl15 = liquidity_sweep(M15[“high”], M15[“low”], M15[“close”])
cv15 = candle_pattern(M15[“open”], M15[“high”], M15[“low”], M15[“close”])
bs = 0; br = []
if sd1 == “BULLISH”:                    bs += 3; br.append(“D1 haussier”)
if sh4 == “BULLISH”:                    bs += 2; br.append(“H4 HH+HL”)
if sh1 == “BULLISH”:                    bs += 2; br.append(“H1 haussier”)
if price > e200h4:                      bs += 1; br.append(“Prix > EMA200 H4”)
if swl:                                 bs += 3; br.append(“Sweep bas H1”)
if swl15:                               bs += 2; br.append(“Sweep bas M15”)
if in_ob(price, bob):                   bs += 3; br.append(“Order Block haussier”)
if near_fvg(price, bfv):               bs += 2; br.append(“FVG haussier”)
if bh1 == “BOS_BULL”:                   bs += 2; br.append(“BOS haussier H1”)
if ch15 == “CHOCH_BULL”:               bs += 2; br.append(“CHoCH bullish M15”)
if rv < 35:                             bs += 2; br.append(f”RSI survendu {rv:.1f}”)
if rd == “BULL”:                        bs += 2; br.append(“Divergence RSI bull”)
if mv > 0:                              bs += 1; br.append(“MACD positif”)
if price < bbl:                         bs += 2; br.append(“Prix sous BB basse”)
if stv < 20:                            bs += 2; br.append(f”Stoch survendu {stv:.1f}”)
if price > e50:                         bs += 1; br.append(“Prix > EMA50”)
if e9 > e21:                            bs += 1; br.append(“EMA9 > EMA21”)
if cv in [“BULL_PIN”, “BULL_ENGULF”]:   bs += 2; br.append(f”Bougie : {cv}”)
if cv15 in [“BULL_PIN”, “BULL_ENGULF”]: bs += 1; br.append(f”Bougie M15 : {cv15}”)
if nc[“status”] == “AFTER”:             bs += 1; br.append(“Post-news opportunite”)
ss = 0; sr = []
if sd1 == “BEARISH”:                    ss += 3; sr.append(“D1 baissier”)
if sh4 == “BEARISH”:                    ss += 2; sr.append(“H4 LH+LL”)
if sh1 == “BEARISH”:                    ss += 2; sr.append(“H1 baissier”)
if price < e200h4:                      ss += 1; sr.append(“Prix < EMA200 H4”)
if swh:                                 ss += 3; sr.append(“Sweep haut H1”)
if swh15:                               ss += 2; sr.append(“Sweep haut M15”)
if in_ob(price, beb):                   ss += 3; sr.append(“Order Block baissier”)
if near_fvg(price, bfb):               ss += 2; sr.append(“FVG baissier”)
if bh1 == “BOS_BEAR”:                   ss += 2; sr.append(“BOS baissier H1”)
if ch15 == “CHOCH_BEAR”:               ss += 2; sr.append(“CHoCH bearish M15”)
if rv > 65:                             ss += 2; sr.append(f”RSI surachete {rv:.1f}”)
if rd == “BEAR”:                        ss += 2; sr.append(“Divergence RSI bear”)
if mv < 0:                              ss += 1; sr.append(“MACD negatif”)
if price > bbu:                         ss += 2; sr.append(“Prix > BB haute”)
if stv > 80:                            ss += 2; sr.append(f”Stoch surachete {stv:.1f}”)
if price < e50:                         ss += 1; sr.append(“Prix < EMA50”)
if e9 < e21:                            ss += 1; sr.append(“EMA9 < EMA21”)
if cv in [“BEAR_PIN”, “BEAR_ENGULF”]:   ss += 2; sr.append(f”Bougie : {cv}”)
if cv15 in [“BEAR_PIN”, “BEAR_ENGULF”]: ss += 1; sr.append(f”Bougie M15 : {cv15}”)
if nc[“status”] == “AFTER”:             ss += 1; sr.append(“Post-news opportunite”)
THRESH = 10
MAX = 30
if bs >= THRESH and bs > ss:
sig = “ACHAT”; sc = bs; reasons = br
elif ss >= THRESH and ss > bs:
sig = “VENTE”; sc = ss; reasons = sr
else:
return None
conf = min(95, int(sc / MAX * 100))
sh_pts, sl_pts = swings(H1[“high”], H1[“low”])
if sig == “ACHAT”:
sl_s = sl_pts[-1][1] - atrv * 0.3 if sl_pts else price - atrv * 1.5
sl = min(sl_s, price - atrv * 1.5)
tp1 = price + (price - sl) * 1.5
tp2 = price + (price - sl) * 2.5
tp3 = price + (price - sl) * 4.0
else:
sl_s = sh_pts[-1][1] + atrv * 0.3 if sh_pts else price + atrv * 1.5
sl = max(sl_s, price + atrv * 1.5)
tp1 = price - (sl - price) * 1.5
tp2 = price - (sl - price) * 2.5
tp3 = price - (sl - price) * 4.0
pip_size = 0.01 if “JPY” in pair_name else (0.1 if “XAU” in pair_name else 0.0001)
sl_pips = abs(price - sl) / pip_size
pv = next((p[“pip_val”] for p in PAIRS if p[“name”] == pair_name), 10)
lm = 0.5 if nc[“status”] == “CAUTION” else 1.0
lv = lot_size(sl_pips, pv, lm * sess_mult)
return {
“sig”: sig, “sc”: sc, “MAX”: MAX, “conf”: conf,
“price”: price, “sl”: sl, “tp1”: tp1, “tp2”: tp2, “tp3”: tp3,
“sl_pips”: sl_pips, “lot”: lv, “rsi”: rv, “stoch”: stv,
“sd1”: sd1, “sh4”: sh4, “sh1”: sh1, “sm15”: sm15,
“cv”: cv, “reasons”: reasons[:8], “dec”: dec, “nc”: nc,
}

def check(pair, events):
name = pair[“name”]
sess, active, smult = session()
if not active:
return
if not daily_ok():
return
nc = classify_news(name, events)
if nc[“status”] == “WAIT”:
key = name + nc[“reason”]
if last_news_alert.get(name) != key:
last_news_alert[name] = key
send(f”PAUSE {name}\n{nc[‘reason’]}\n{nc[‘action’]}\nSignal apres la news”)
return
last_news_alert[name] = None
res = analyze(name, pair[“kraken”], nc, smult)
if not res:
return
sig = res[“sig”]
cur = open_positions.get(name)
if cur and cur != sig:
send(f”RETOURNEMENT {name}\nFerme ta position {cur}\nNouveau signal : {sig}”)
key = name + “_” + sig
if last_signals.get(key):
return
last_signals[key] = True
open_positions[name] = sig
daily[“count”] += 1
dec = res[“dec”]
icon = “BUY” if sig == “ACHAT” else “SELL”
nc_info = res[“nc”]
msg = f”{icon} SIGNAL {sig} - {name}\n”
msg += “========================\n”
msg += f”Prix  : {res[‘price’]:.{dec}f}\n”
msg += f”SL    : {res[‘sl’]:.{dec}f} ({res[‘sl_pips’]:.0f} pips)\n”
msg += f”TP1   : {res[‘tp1’]:.{dec}f} (RR 1:1.5)\n”
msg += f”TP2   : {res[‘tp2’]:.{dec}f} (RR 1:2.5)\n”
msg += f”TP3   : {res[‘tp3’]:.{dec}f} (RR 1:4)\n”
msg += f”Lot   : {res[‘lot’]}\n”
msg += “========================\n”
msg += f”Confiance : {res[‘conf’]}% ({res[‘sc’]}/{res[‘MAX’]})\n”
msg += f”Session   : {sess}\n”
msg += f”D1  : {res[‘sd1’]}\n”
msg += f”H4  : {res[‘sh4’]}\n”
msg += f”H1  : {res[‘sh1’]}\n”
msg += f”M15 : {res[‘sm15’]}\n”
msg += f”RSI : {res[‘rsi’]:.1f} | Stoch : {res[‘stoch’]:.1f}\n”
if res[“cv”] != “NONE”:
msg += f”Bougie : {res[‘cv’]}\n”
if nc_info[“status”] != “CLEAR”:
msg += “========================\n”
msg += f”NEWS : {nc_info[‘reason’]}\n”
msg += f”{nc_info[‘action’]}\n”
msg += “========================\n”
msg += “Confluences SMC :\n”
for r in res[“reasons”]:
msg += f”  - {r}\n”
msg += “========================\n”
msg += “Risque 1% - Signal indicatif”
send(msg)
print(f”[{datetime.now().strftime(’%H:%M’)}] {name} {sig} {res[‘conf’]}%”)

def reset_check():
global last_reset
if (datetime.now() - last_reset).seconds > 14400:
last_signals.clear()
last_reset = datetime.now()

now = datetime.now().strftime(”%d/%m/%Y %H:%M”)
send(f”ARBI BOT PRO v6 - {now}\nPaires : EUR/USD GBP/USD USD/JPY XAU/USD\nAnalyse : D1 > H4 > H1 > M15\nEn surveillance…”)
print(“ArbiBot v6 demarre”)

while True:
try:
events = get_news()
for p in PAIRS:
try:
check(p, events)
except Exception as e:
print(f”Error {p[‘name’]}: {e}”)
time.sleep(2)
reset_check()
print(f”[{datetime.now().strftime(’%H:%M’)}] Cycle ok”)
time.sleep(300)
except KeyboardInterrupt:
break
except Exception as e:
print(f”Erreur: {e}”)
time.sleep(60)
