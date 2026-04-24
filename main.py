import requests
import time
import os
from datetime import datetime, timezone

TOKEN = os.environ.get(‘TOKEN’, ‘’)
IDS = [‘525011337’, ‘7276558677’]

PAIRS = [
dict(name=‘EUR/USD’, kraken=‘EURUSD’),
dict(name=‘GBP/USD’, kraken=‘GBPUSD’),
dict(name=‘USD/JPY’, kraken=‘USDJPY’),
dict(name=‘XAU/USD’, kraken=‘XAUUSD’),
]

CAPITAL = 10000
RISK_PCT = 1.0
MAX_TRADES = 3

last_signals = {}
open_positions = {}
daily = dict(date=’’, count=0, losses=0)
last_news_alert = {}
last_reset = datetime.now()

def send(msg):
for cid in IDS:
try:
url = ‘https://api.telegram.org/bot’ + TOKEN + ‘/sendMessage’
requests.post(url, json=dict(chat_id=cid, text=msg), timeout=10)
except Exception as e:
print(’Telegram error: ’ + str(e))
time.sleep(0.5)

def candles(pair, interval=60, count=200):
try:
url = ‘https://api.kraken.com/0/public/OHLC’
r = requests.get(url, params=dict(pair=pair, interval=interval), timeout=10)
d = r.json()[‘result’]
k = [x for x in d if x != ‘last’][0]
data = d[k][-count:]
return dict(
o=[float(c[1]) for c in data],
h=[float(c[2]) for c in data],
l=[float(c[3]) for c in data],
c=[float(c[4]) for c in data],
v=[float(c[6]) for c in data],
)
except Exception as e:
print(’OHLC error ’ + pair + ’: ’ + str(e))
return None

def ema(closes, n):
if len(closes) < n:
return closes[-1]
k = 2.0 / (n + 1)
e = sum(closes[:n]) / n
for p in closes[n:]:
e = p * k + e * (1 - k)
return e

def rsi(closes, n=14):
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
s = closes[-n:]
mid = sum(s) / len(s)
std = (sum((x - mid) ** 2 for x in s) / len(s)) ** 0.5
return mid + 2 * std, mid - 2 * std, mid

def stoch(highs, lows, closes, n=14):
h = max(highs[-n:])
l = min(lows[-n:])
if h == l:
return 50
return 100 * (closes[-1] - l) / (h - l)

def atr(highs, lows, closes, n=14):
trs = []
for i in range(1, len(closes)):
tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
trs.append(tr)
return sum(trs[-n:]) / n

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

def ob(opens, highs, lows, closes, lb=50):
bull = []
bear = []
start = max(1, len(closes) - lb)
for i in range(start, len(closes) - 1):
if closes[i] < opens[i] and closes[i+1] > highs[i]:
bull.append(dict(h=highs[i], l=lows[i], mid=(highs[i]+lows[i])/2))
if closes[i] > opens[i] and closes[i+1] < lows[i]:
bear.append(dict(h=highs[i], l=lows[i], mid=(highs[i]+lows[i])/2))
return bull[-3:], bear[-3:]

def fvg(highs, lows, lb=50):
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
if x[‘l’] <= price <= x[‘h’]:
return True
return False

def near_fvg(price, fvgs, thr=0.0025):
for x in fvgs:
if abs(price - x[‘mid’]) / price < thr:
return True
return False

def get_news():
try:
url = ‘https://nfs.faireconomy.media/ff_calendar_thisweek.json’
r = requests.get(url, timeout=10)
return r.json()
except:
return []

def classify_news(pair_name, events):
now = datetime.now(timezone.utc)
curs = [‘USD’]
if ‘EUR’ in pair_name:
curs.append(‘EUR’)
if ‘GBP’ in pair_name:
curs.append(‘GBP’)
if ‘JPY’ in pair_name:
curs.append(‘JPY’)
uh = []
jr = []
rh = []
um = []
for e in events:
impact = e.get(‘impact’, ‘’)
cur = e.get(‘country’, ‘’).upper()
if not any(c in cur for c in curs):
continue
if impact not in [‘High’, ‘Medium’]:
continue
try:
et = datetime.strptime(e[‘date’], ‘%Y-%m-%dT%H:%M:%S%z’)
diff = (et - now).total_seconds() / 60
title = e.get(‘title’, ‘’)
country = e.get(‘country’, ‘’)
if impact == ‘High’:
if 0 < diff <= 45:
uh.append(dict(title=title, country=country, mins=int(diff)))
elif -15 <= diff <= 0:
jr.append(dict(title=title, country=country, mins=int(diff)))
elif -60 <= diff < -15:
rh.append(dict(title=title, country=country, mins=int(diff)))
elif impact == ‘Medium’:
if 0 < diff <= 20:
um.append(dict(title=title, country=country, mins=int(diff)))
except:
pass
if uh:
n = uh[0]
return dict(status=1, reason=’News ROUGE dans ’ + str(n[‘mins’]) + ’min : ’ + n[‘title’], action=‘Attendre puis trader la reaction’)
if jr:
n = jr[0]
return dict(status=2, reason=’News sortie il y a ’ + str(abs(n[‘mins’])) + ’min : ’ + n[‘title’], action=‘Trader la reaction - confirmer M15’)
if rh:
n = rh[0]
return dict(status=2, reason=‘Post-news ’ + str(abs(n[‘mins’])) + ‘min : ’ + n[‘title’], action=‘Marche en digestion’)
if um:
n = um[0]
return dict(status=3, reason=‘News ORANGE dans ’ + str(n[‘mins’]) + ‘min : ’ + n[‘title’], action=‘Lot reduit 50%’)
return dict(status=0, reason=’’, action=’’)

def session():
h = datetime.now(timezone.utc).hour
if 7 <= h < 12:
return ‘Londres’, True, 1.0
if 12 <= h < 16:
return ‘LDN+NY’, True, 1.2
if 16 <= h < 21:
return ‘New York’, True, 1.0
if 2 <= h < 5:
return ‘Tokyo’, True, 0.7
return ‘Ferme’, False, 0

def lot_size(sl_pips, pip_val=10, mult=1.0):
risk = CAPITAL * RISK_PCT / 100 * mult
lot = risk / (sl_pips * pip_val) if sl_pips > 0 else 0.01
return round(max(0.01, min(lot, 2.0)), 2)

def daily_ok():
today = datetime.now().strftime(’%Y-%m-%d’)
if daily[‘date’] != today:
daily.update(dict(date=today, count=0, losses=0))
if daily[‘count’] >= MAX_TRADES:
return False
if daily[‘losses’] >= 2:
return False
return True

def analyze(pair_name, kraken_pair, nc, sess_mult):
D1  = candles(kraken_pair, 1440, 60)
H4  = candles(kraken_pair, 240, 100)
H1  = candles(kraken_pair, 60, 200)
M15 = candles(kraken_pair, 15, 150)
if not H4 or not H1 or not M15:
return None
price = H1[‘c’][-1]
dec = 3 if ‘JPY’ in pair_name else (1 if ‘XAU’ in pair_name else 5)
sd1 = 0
if D1:
sd1, _, _ = structure(D1[‘h’], D1[‘l’], D1[‘c’])
e200h4 = ema(H4[‘c’], 100)
sh4, _, _ = structure(H4[‘h’], H4[‘l’], H4[‘c’])
sh1, bh1, _ = structure(H1[‘h’], H1[‘l’], H1[‘c’])
sm15, _, ch15 = structure(M15[‘h’], M15[‘l’], M15[‘c’])
e9  = ema(H1[‘c’], 9)
e21 = ema(H1[‘c’], 21)
e50 = ema(H1[‘c’], 50)
rv  = rsi(H1[‘c’])
rd  = rsi_div(H1[‘c’])
mv  = macd(H1[‘c’])
bbu, bbl, _ = bollinger(H1[‘c’])
atrv = atr(H1[‘h’], H1[‘l’], H1[‘c’])
stv  = stoch(H1[‘h’], H1[‘l’], H1[‘c’])
bob, beb = ob(H1[‘o’], H1[‘h’], H1[‘l’], H1[‘c’])
bfv, bfb = fvg(H1[‘h’], H1[‘l’])
swh, swl = sweep(H1[‘h’], H1[‘l’], H1[‘c’])
swh15, swl15 = sweep(M15[‘h’], M15[‘l’], M15[‘c’])

```
bs = 0
br = []
if sd1 == 1:    bs += 3; br.append('D1 haussier')
if sh4 == 1:    bs += 2; br.append('H4 HH+HL')
if sh1 == 1:    bs += 2; br.append('H1 haussier')
if price > e200h4: bs += 1; br.append('Prix > EMA200 H4')
if swl:         bs += 3; br.append('Sweep bas H1')
if swl15:       bs += 2; br.append('Sweep bas M15')
if in_ob(price, bob): bs += 3; br.append('Order Block haussier')
if near_fvg(price, bfv): bs += 2; br.append('FVG haussier')
if bh1 == 1:    bs += 2; br.append('BOS haussier H1')
if ch15 == 1:   bs += 2; br.append('CHoCH bullish M15')
if rv < 35:     bs += 2; br.append('RSI survendu ' + str(round(rv, 1)))
if rd == 1:     bs += 2; br.append('Divergence RSI bull')
if mv > 0:      bs += 1; br.append('MACD positif')
if price < bbl: bs += 2; br.append('Prix sous BB basse')
if stv < 20:    bs += 2; br.append('Stoch survendu ' + str(round(stv, 1)))
if price > e50: bs += 1; br.append('Prix > EMA50')
if e9 > e21:    bs += 1; br.append('EMA9 > EMA21')
if nc['status'] == 2: bs += 1; br.append('Post-news opportunite')

ss = 0
sr = []
if sd1 == -1:   ss += 3; sr.append('D1 baissier')
if sh4 == -1:   ss += 2; sr.append('H4 LH+LL')
if sh1 == -1:   ss += 2; sr.append('H1 baissier')
if price < e200h4: ss += 1; sr.append('Prix < EMA200 H4')
if swh:         ss += 3; sr.append('Sweep haut H1')
if swh15:       ss += 2; sr.append('Sweep haut M15')
if in_ob(price, beb): ss += 3; sr.append('Order Block baissier')
if near_fvg(price, bfb): ss += 2; sr.append('FVG baissier')
if bh1 == -1:   ss += 2; sr.append('BOS baissier H1')
if ch15 == -1:  ss += 2; sr.append('CHoCH bearish M15')
if rv > 65:     ss += 2; sr.append('RSI surachete ' + str(round(rv, 1)))
if rd == -1:    ss += 2; sr.append('Divergence RSI bear')
if mv < 0:      ss += 1; sr.append('MACD negatif')
if price > bbu: ss += 2; sr.append('Prix > BB haute')
if stv > 80:    ss += 2; sr.append('Stoch surachete ' + str(round(stv, 1)))
if price < e50: ss += 1; sr.append('Prix < EMA50')
if e9 < e21:    ss += 1; sr.append('EMA9 < EMA21')
if nc['status'] == 2: ss += 1; sr.append('Post-news opportunite')

THRESH = 10
MAX = 30
if bs >= THRESH and bs > ss:
    sig = 1; sc = bs; reasons = br
elif ss >= THRESH and ss > bs:
    sig = -1; sc = ss; reasons = sr
else:
    return None

conf = min(95, int(sc / MAX * 100))
sh_pts, sl_pts = swings(H1['h'], H1['l'])
if sig == 1:
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

pip_size = 0.01 if 'JPY' in pair_name else (0.1 if 'XAU' in pair_name else 0.0001)
sl_pips = abs(price - sl) / pip_size
pv = next((p['pip_val'] for p in PAIRS if p['name'] == pair_name), 10)
lm = 0.5 if nc['status'] == 3 else 1.0
lv = lot_size(sl_pips, pv, lm * sess_mult)

sd1_txt = 'BULLISH' if sd1 == 1 else ('BEARISH' if sd1 == -1 else 'NEUTRAL')
sh4_txt = 'BULLISH' if sh4 == 1 else ('BEARISH' if sh4 == -1 else 'NEUTRAL')
sh1_txt = 'BULLISH' if sh1 == 1 else ('BEARISH' if sh1 == -1 else 'NEUTRAL')
sm15_txt = 'BULLISH' if sm15 == 1 else ('BEARISH' if sm15 == -1 else 'NEUTRAL')

return dict(sig=sig, sc=sc, MAX=MAX, conf=conf, price=price, sl=sl,
            tp1=tp1, tp2=tp2, tp3=tp3, sl_pips=sl_pips, lot=lv,
            rsi=rv, stoch=stv, sd1=sd1_txt, sh4=sh4_txt, sh1=sh1_txt,
            sm15=sm15_txt, reasons=reasons[:8], dec=dec, nc=nc)
```

def check(pair, events):
name = pair[‘name’]
sess, active, smult = session()
if not active:
return
if not daily_ok():
return
nc = classify_news(name, events)
if nc[‘status’] == 1:
key = name + nc[‘reason’]
if last_news_alert.get(name) != key:
last_news_alert[name] = key
send(’PAUSE ’ + name + ‘\n’ + nc[‘reason’] + ‘\n’ + nc[‘action’] + ‘\nSignal apres la news’)
return
last_news_alert[name] = None
res = analyze(name, pair[‘kraken’], nc, smult)
if not res:
return
sig = res[‘sig’]
sig_txt = ‘ACHAT’ if sig == 1 else ‘VENTE’
cur = open_positions.get(name)
if cur and cur != sig:
cur_txt = ‘ACHAT’ if cur == 1 else ‘VENTE’
send(’RETOURNEMENT ’ + name + ’\nFerme ta position ’ + cur_txt + ’\nNouveau signal : ’ + sig_txt)
key = name + str(sig)
if last_signals.get(key):
return
last_signals[key] = True
open_positions[name] = sig
daily[‘count’] += 1
dec = res[‘dec’]
icon = ‘BUY’ if sig == 1 else ‘SELL’
nc_info = res[‘nc’]
msg = icon + ’ SIGNAL ’ + sig_txt + ’ - ’ + name + ‘\n’
msg += ‘========================\n’
msg += ‘Prix  : ’ + str(round(res[‘price’], dec)) + ‘\n’
msg += ‘SL    : ’ + str(round(res[‘sl’], dec)) + ’ (’ + str(round(res[‘sl_pips’])) + ’ pips)\n’
msg += ‘TP1   : ’ + str(round(res[‘tp1’], dec)) + ’ (RR 1:1.5)\n’
msg += ‘TP2   : ’ + str(round(res[‘tp2’], dec)) + ’ (RR 1:2.5)\n’
msg += ‘TP3   : ’ + str(round(res[‘tp3’], dec)) + ’ (RR 1:4)\n’
msg += ’Lot   : ’ + str(res[‘lot’]) + ‘\n’
msg += ‘========================\n’
msg += ’Confiance : ’ + str(res[‘conf’]) + ‘% (’ + str(res[‘sc’]) + ‘/’ + str(res[‘MAX’]) + ‘)\n’
msg += ’Session   : ’ + sess + ‘\n’
msg += ’D1  : ’ + res[‘sd1’] + ‘\n’
msg += ’H4  : ’ + res[‘sh4’] + ‘\n’
msg += ‘H1  : ’ + res[‘sh1’] + ‘\n’
msg += ‘M15 : ’ + res[‘sm15’] + ‘\n’
msg += ‘RSI : ’ + str(round(res[‘rsi’], 1)) + ’ | Stoch : ’ + str(round(res[‘stoch’], 1)) + ‘\n’
if nc_info[‘status’] != 0:
msg += ‘========================\n’
msg += ‘NEWS : ’ + nc_info[‘reason’] + ‘\n’
msg += nc_info[‘action’] + ‘\n’
msg += ‘========================\n’
msg += ‘Confluences SMC :\n’
for r in res[‘reasons’]:
msg += ’  - ’ + r + ‘\n’
msg += ‘========================\n’
msg += ‘Risque 1% - Signal indicatif’
send(msg)
print(’[’ + datetime.now().strftime(’%H:%M’) + ’] ’ + name + ’ ’ + sig_txt + ’ ’ + str(res[‘conf’]) + ‘%’)

def reset_check():
global last_reset
if (datetime.now() - last_reset).seconds > 14400:
last_signals.clear()
last_reset = datetime.now()

now = datetime.now().strftime(’%d/%m/%Y %H:%M’)
send(’ARBI BOT PRO v6 - ’ + now + ‘\nPaires : EUR/USD GBP/USD USD/JPY XAU/USD\nAnalyse : D1 > H4 > H1 > M15\nEn surveillance…’)
print(‘ArbiBot v6 demarre’)

while True:
try:
events = get_news()
for p in PAIRS:
try:
check(p, events)
except Exception as e:
print(‘Error ’ + p[‘name’] + ‘: ’ + str(e))
time.sleep(2)
reset_check()
print(’[’ + datetime.now().strftime(’%H:%M’) + ‘] Cycle ok’)
time.sleep(300)
except KeyboardInterrupt:
break
except Exception as e:
print(’Erreur: ’ + str(e))
time.sleep(60)
