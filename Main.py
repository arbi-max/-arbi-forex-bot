import requests
import time
import os
from datetime import datetime, timezone

TOKEN = os.environ.get(‘TOKEN’, ‘’)
IDS = os.environ.get(‘IDS’, ‘525011337,7276558677’).split(’,’)

PAIRS = [
dict(name=‘EUR/USD’, kraken=‘EURUSD’,  pip=0.0001, pip_val=10),
dict(name=‘GBP/USD’, kraken=‘GBPUSD’,  pip=0.0001, pip_val=10),
dict(name=‘USD/JPY’, kraken=‘USDJPY’,  pip=0.01,   pip_val=9),
dict(name=‘XAU/USD’, kraken=‘XAUUSD’,  pip=0.1,    pip_val=1),
]

CAPITAL = 10000
RISK_PCT = 1.0
MAX_TRADES = 3
SCAN_INTERVAL = 300

last_signals = {}
open_pos = {}
daily = dict(date=’’, count=0, losses=0)
last_news_alert = {}
last_reset = datetime.now()

def send(msg):
for cid in IDS:
try:
requests.post(
‘https://api.telegram.org/bot’ + TOKEN + ‘/sendMessage’,
json=dict(chat_id=cid, text=msg),
timeout=10
)
except Exception as ex:
print(’Telegram error: ’ + str(ex))
time.sleep(0.3)

def ohlc(pair, interval=60, count=200):
try:
r = requests.get(
‘https://api.kraken.com/0/public/OHLC’,
params=dict(pair=pair, interval=interval),
timeout=10
)
d = r.json()[‘result’]
k = [x for x in d if x != ‘last’][0]
rows = d[k][-count:]
return dict(
o=[float(x[1]) for x in rows],
h=[float(x[2]) for x in rows],
l=[float(x[3]) for x in rows],
c=[float(x[4]) for x in rows],
v=[float(x[6]) for x in rows],
)
except Exception as ex:
print(’OHLC error ’ + pair + ’: ’ + str(ex))
return None

def ema(c, n):
if len(c) < n:
return c[-1]
k = 2.0 / (n + 1)
e = sum(c[:n]) / n
for p in c[n:]:
e = p * k + e * (1 - k)
return e

def rsi(c, n=14):
if len(c) < n + 1:
return 50
g = 0.0
lo = 0.0
for i in range(len(c) - n, len(c)):
d = c[i] - c[i - 1]
if d > 0:
g += d
else:
lo -= d
return 100 - 100 / (1 + g / (lo or 0.001))

def rsi_div(c):
if len(c) < 40:
return ‘NONE’
r1 = rsi(c[-40:-20])
r2 = rsi(c[-20:])
if min(c[-20:]) < min(c[-40:-20]) and r2 > r1:
return ‘BULL’
if max(c[-20:]) > max(c[-40:-20]) and r2 < r1:
return ‘BEAR’
return ‘NONE’

def macd(c):
if len(c) < 26:
return 0
return ema(c, 12) - ema(c, 26)

def bollinger(c, n=20):
if len(c) < n:
return c[-1], c[-1], c[-1]
s = c[-n:]
m = sum(s) / len(s)
std = (sum((x - m) ** 2 for x in s) / len(s)) ** 0.5
return m + 2 * std, m - 2 * std, m

def atr(h, l, c, n=14):
if len(c) < n + 1:
return h[-1] - l[-1]
trs = [max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])) for i in range(1, len(c))]
return sum(trs[-n:]) / n

def stoch(h, l, c, n=14):
if len(c) < n:
return 50
hi = max(h[-n:])
lo = min(l[-n:])
return 100 * (c[-1] - lo) / (hi - lo) if hi != lo else 50

def vol_spike(v, n=20):
if len(v) < n + 1:
return False
avg = sum(v[-n-1:-1]) / n
return v[-1] > avg * 1.5

def swings(h, l, lb=5):
sh = []
sl = []
for i in range(lb, len(h) - lb):
if all(h[i] >= h[i-j] for j in range(1, lb+1)) and all(h[i] >= h[i+j] for j in range(1, lb+1)):
sh.append((i, h[i]))
if all(l[i] <= l[i-j] for j in range(1, lb+1)) and all(l[i] <= l[i+j] for j in range(1, lb+1)):
sl.append((i, l[i]))
return sh, sl

def structure(h, l, c):
sh, sl = swings(h, l)
if len(sh) < 2 or len(sl) < 2:
return ‘NEUTRAL’, ‘NONE’, ‘NONE’
hh = sh[-1][1] > sh[-2][1]
hl = sl[-1][1] > sl[-2][1]
lh = sh[-1][1] < sh[-2][1]
ll = sl[-1][1] < sl[-2][1]
if hh and hl:
st = ‘BULLISH’
elif lh and ll:
st = ‘BEARISH’
else:
st = ‘NEUTRAL’
price = c[-1]
bos = ‘NONE’
choch = ‘NONE’
if st == ‘BULLISH’ and price > sh[-1][1]:
bos = ‘BOS_BULL’
if st == ‘BEARISH’ and price < sl[-1][1]:
bos = ‘BOS_BEAR’
if st == ‘BULLISH’ and price < sl[-1][1]:
choch = ‘CHOCH_BEAR’
if st == ‘BEARISH’ and price > sh[-1][1]:
choch = ‘CHOCH_BULL’
return st, bos, choch

def order_blocks(o, h, l, c, lb=50):
bull = []
bear = []
start = max(1, len(c) - lb)
for i in range(start, len(c) - 1):
if c[i] < o[i] and c[i+1] > h[i]:
bull.append(dict(h=h[i], l=l[i], mid=(h[i]+l[i])/2))
if c[i] > o[i] and c[i+1] < l[i]:
bear.append(dict(h=h[i], l=l[i], mid=(h[i]+l[i])/2))
return bull[-3:], bear[-3:]

def fair_value_gaps(h, l, lb=50):
bull = []
bear = []
start = max(0, len(h) - lb)
for i in range(start, len(h) - 2):
if l[i+2] > h[i]:
bull.append(dict(top=l[i+2], bot=h[i], mid=(l[i+2]+h[i])/2))
if h[i+2] < l[i]:
bear.append(dict(top=l[i], bot=h[i+2], mid=(l[i]+h[i+2])/2))
return bull[-3:], bear[-3:]

def sweep(h, l, c):
sh, sl = swings(h, l)
if not sh or not sl:
return False, False
prev = c[-2]
price = c[-1]
swept_h = prev > sh[-1][1] and price < sh[-1][1]
swept_l = prev < sl[-1][1] and price > sl[-1][1]
return swept_h, swept_l

def candle_pat(o, h, l, c):
if len(c) < 2:
return ‘NONE’
body = abs(c[-1] - o[-1])
rng = h[-1] - l[-1]
if rng == 0:
return ‘NONE’
lw = min(o[-1], c[-1]) - l[-1]
uw = h[-1] - max(o[-1], c[-1])
if lw > body * 2 and uw < body * 0.5:
return ‘BULL_PIN’
if uw > body * 2 and lw < body * 0.5:
return ‘BEAR_PIN’
if c[-1] > o[-1] and c[-2] < o[-2] and c[-1] > o[-2] and o[-1] < c[-2] and body/rng > 0.6:
return ‘BULL_ENG’
if c[-1] < o[-1] and c[-2] > o[-2] and c[-1] < o[-2] and o[-1] > c[-2] and body/rng > 0.6:
return ‘BEAR_ENG’
return ‘NONE’

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
r = requests.get(‘https://nfs.faireconomy.media/ff_calendar_thisweek.json’, timeout=10)
return r.json()
except:
return []

def classify_news(pair_name, events):
now = datetime.now(timezone.utc)
curs = [‘USD’]
if ‘EUR’ in pair_name: curs.append(‘EUR’)
if ‘GBP’ in pair_name: curs.append(‘GBP’)
if ‘JPY’ in pair_name: curs.append(‘JPY’)
uh = []
jr = []
rh = []
um = []
for e in events:
impact = e.get(‘impact’, ‘’)
cur = e.get(‘country’, ‘’).upper()
if not any(c in cur for c in curs): continue
if impact not in [‘High’, ‘Medium’]: continue
try:
et = datetime.strptime(e[‘date’], ‘%Y-%m-%dT%H:%M:%S%z’)
diff = (et - now).total_seconds() / 60
title = e.get(‘title’, ‘’)
country = e.get(‘country’, ‘’)
if impact == ‘High’:
if 0 < diff <= 45: uh.append(dict(title=title, country=country, mins=int(diff)))
elif -15 <= diff <= 0: jr.append(dict(title=title, country=country, mins=int(diff)))
elif -60 <= diff < -15: rh.append(dict(title=title, country=country, mins=int(diff)))
elif impact == ‘Medium’:
if 0 < diff <= 20: um.append(dict(title=title, country=country, mins=int(diff)))
except: pass
if uh:
n = uh[0]
return dict(status=‘WAIT’, reason=’News ROUGE dans ’ + str(n[‘mins’]) + ’min : ’ + n[‘title’], action=‘Attendre puis trader la reaction’)
if jr:
n = jr[0]
return dict(status=‘AFTER’, reason=’News sortie il y a ’ + str(abs(n[‘mins’])) + ’min : ’ + n[‘title’], action=‘Trader la reaction - confirmer M15’)
if rh:
n = rh[0]
return dict(status=‘AFTER’, reason=‘Post-news ’ + str(abs(n[‘mins’])) + ‘min : ’ + n[‘title’], action=‘Marche en digestion’)
if um:
n = um[0]
return dict(status=‘CAUTION’, reason=‘News ORANGE dans ’ + str(n[‘mins’]) + ‘min : ’ + n[‘title’], action=‘Lot reduit 50%’)
return dict(status=‘CLEAR’, reason=’’, action=’’)

def session():
h = datetime.now(timezone.utc).hour
if 7 <= h < 12: return ‘Londres’, True, 1.0
if 12 <= h < 16: return ‘LDN+NY’, True, 1.2
if 16 <= h < 21: return ‘New York’, True, 1.0
if 2 <= h < 5: return ‘Tokyo’, True, 0.7
return ‘Ferme’, False, 0

def lot_size(sl_pips, pip_val=10, mult=1.0):
risk = CAPITAL * RISK_PCT / 100 * mult
lot = risk / (sl_pips * pip_val) if sl_pips > 0 else 0.01
return round(max(0.01, min(lot, 2.0)), 2)

def daily_ok():
today = datetime.now().strftime(’%Y-%m-%d’)
if daily[‘date’] != today:
daily.update(dict(date=today, count=0, losses=0))
if daily[‘count’] >= MAX_TRADES: return False
if daily[‘losses’] >= 2: return False
return True

def analyze(pair_name, kraken_pair, nc, sess_mult):
D1  = ohlc(kraken_pair, 1440, 60)
H4  = ohlc(kraken_pair, 240, 100)
H1  = ohlc(kraken_pair, 60, 200)
M15 = ohlc(kraken_pair, 15, 150)
if not H4 or not H1 or not M15: return None
p = H1[‘c’][-1]
dec = 3 if ‘JPY’ in pair_name else (1 if ‘XAU’ in pair_name else 5)
sd1 = ‘NEUTRAL’
if D1: sd1, _, _ = structure(D1[‘h’], D1[‘l’], D1[‘c’])
e200h4 = ema(H4[‘c’], 100)
sh4, _, _ = structure(H4[‘h’], H4[‘l’], H4[‘c’])
sh1, bh1, _ = structure(H1[‘h’], H1[‘l’], H1[‘c’])
sm15, _, ch15 = structure(M15[‘h’], M15[‘l’], M15[‘c’])
e50 = ema(H1[‘c’], 50)
rv = rsi(H1[‘c’])
rd = rsi_div(H1[‘c’])
mv = macd(H1[‘c’])
bbu, bbl, _ = bollinger(H1[‘c’])
atrv = atr(H1[‘h’], H1[‘l’], H1[‘c’])
stv = stoch(H1[‘h’], H1[‘l’], H1[‘c’])
vsp = vol_spike(H1[‘v’])
cv = candle_pat(H1[‘o’], H1[‘h’], H1[‘l’], H1[‘c’])
bob, beb = order_blocks(H1[‘o’], H1[‘h’], H1[‘l’], H1[‘c’])
bfv, bfb = fair_value_gaps(H1[‘h’], H1[‘l’])
swh, swl = sweep(H1[‘h’], H1[‘l’], H1[‘c’])
swh15, swl15 = sweep(M15[‘h’], M15[‘l’], M15[‘c’])
cv15 = candle_pat(M15[‘o’], M15[‘h’], M15[‘l’], M15[‘c’])
bs = 0; br = []
if sd1 == ‘BULLISH’: bs += 3; br.append(‘D1 haussier’)
if sh4 == ‘BULLISH’: bs += 2; br.append(‘H4 HH+HL’)
if sh1 == ‘BULLISH’: bs += 2; br.append(‘H1 haussier’)
if p > e200h4: bs += 1; br.append(‘Prix > EMA200 H4’)
if swl: bs += 3; br.append(‘Sweep bas H1’)
if swl15: bs += 2; br.append(‘Sweep bas M15’)
if in_ob(p, bob): bs += 3; br.append(‘Order Block haussier’)
if near_fvg(p, bfv): bs += 2; br.append(‘FVG haussier’)
if bh1 == ‘BOS_BULL’: bs += 2; br.append(‘BOS haussier H1’)
if ch15 == ‘CHOCH_BULL’: bs += 2; br.append(‘CHoCH bullish M15’)
if rv < 35: bs += 2; br.append(’RSI survendu ’ + str(round(rv,1)))
if rd == ‘BULL’: bs += 2; br.append(‘Divergence RSI bull’)
if mv > 0: bs += 1; br.append(‘MACD positif’)
if p < bbl: bs += 2; br.append(‘Prix sous BB basse’)
if stv < 20: bs += 2; br.append(’Stoch survendu ’ + str(round(stv,1)))
if p > e50: bs += 1; br.append(‘Prix > EMA50’)
if cv in [‘BULL_PIN’, ‘BULL_ENG’]: bs += 2; br.append(’Bougie : ’ + cv)
if cv15 in [‘BULL_PIN’, ‘BULL_ENG’]: bs += 1; br.append(’Bougie M15 : ’ + cv15)
if vsp: bs += 1; br.append(‘Volume spike’)
if nc[‘status’] == ‘AFTER’: bs += 1; br.append(‘Post-news opportunite’)
ss = 0; sr = []
if sd1 == ‘BEARISH’: ss += 3; sr.append(‘D1 baissier’)
if sh4 == ‘BEARISH’: ss += 2; sr.append(‘H4 LH+LL’)
if sh1 == ‘BEARISH’: ss += 2; sr.append(‘H1 baissier’)
if p < e200h4: ss += 1; sr.append(‘Prix < EMA200 H4’)
if swh: ss += 3; sr.append(‘Sweep haut H1’)
if swh15: ss += 2; sr.append(‘Sweep haut M15’)
if in_ob(p, beb): ss += 3; sr.append(‘Order Block baissier’)
if near_fvg(p, bfb): ss += 2; sr.append(‘FVG baissier’)
if bh1 == ‘BOS_BEAR’: ss += 2; sr.append(‘BOS baissier H1’)
if ch15 == ‘CHOCH_BEAR’: ss += 2; sr.append(‘CHoCH bearish M15’)
if rv > 65: ss += 2; sr.append(’RSI surachete ’ + str(round(rv,1)))
if rd == ‘BEAR’: ss += 2; sr.append(‘Divergence RSI bear’)
if mv < 0: ss += 1; sr.append(‘MACD negatif’)
if p > bbu: ss += 2; sr.append(‘Prix > BB haute’)
if stv > 80: ss += 2; sr.append(’Stoch surachete ’ + str(round(stv,1)))
if p < e50: ss += 1; sr.append(‘Prix < EMA50’)
if cv in [‘BEAR_PIN’, ‘BEAR_ENG’]: ss += 2; sr.append(’Bougie : ’ + cv)
if cv15 in [‘BEAR_PIN’, ‘BEAR_ENG’]: ss += 1; sr.append(’Bougie M15 : ’ + cv15)
if vsp: ss += 1; sr.append(‘Volume spike’)
if nc[‘status’] == ‘AFTER’: ss += 1; sr.append(‘Post-news opportunite’)
THRESH = 10
MAX = 30
if bs >= THRESH and bs > ss: sig = ‘ACHAT’; sc = bs; reasons = br
elif ss >= THRESH and ss > bs: sig = ‘VENTE’; sc = ss; reasons = sr
else: return None
conf = min(95, int(sc / MAX * 100))
sh_pts, sl_pts = swings(H1[‘h’], H1[‘l’])
if sig == ‘ACHAT’:
sl_s = sl_pts[-1][1] - atrv * 0.3 if sl_pts else p - atrv * 1.5
sl = min(sl_s, p - atrv * 1.5)
tp1 = p + (p - sl) * 1.5
tp2 = p + (p - sl) * 2.5
tp3 = p + (p - sl) * 4.0
else:
sl_s = sh_pts[-1][1] + atrv * 0.3 if sh_pts else p + atrv * 1.5
sl = max(sl_s, p + atrv * 1.5)
tp1 = p - (sl - p) * 1.5
tp2 = p - (sl - p) * 2.5
tp3 = p - (sl - p) * 4.0
pip_size = 0.01 if ‘JPY’ in pair_name else (0.1 if ‘XAU’ in pair_name else 0.0001)
sl_pips = abs(p - sl) / pip_size
pv = next((x[‘pip_val’] for x in PAIRS if x[‘name’] == pair_name), 10)
lm = 0.5 if nc[‘status’] == ‘CAUTION’ else 1.0
lv = lot_size(sl_pips, pv, lm * sess_mult)
return dict(sig=sig, sc=sc, MAX=MAX, conf=conf, p=p, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
sl_pips=sl_pips, lot=lv, rsi=rv, stoch=stv, sd1=sd1, sh4=sh4, sh1=sh1,
sm15=sm15, cv=cv, vsp=vsp, reasons=reasons[:8], dec=dec, nc=nc)

def fmt(res, name, sess):
sig = res[‘sig’]
dec = res[‘dec’]
icon = ‘BUY’ if sig == ‘ACHAT’ else ‘SELL’
m = icon + ’ ’ + sig + ’ - ’ + name + chr(10)
m += ‘========================’ + chr(10)
m += ‘Prix  : ’ + str(round(res[‘p’], dec)) + chr(10)
m += ‘SL    : ’ + str(round(res[‘sl’], dec)) + ’ (’ + str(round(res[‘sl_pips’])) + ’ pips)’ + chr(10)
m += ‘TP1   : ’ + str(round(res[‘tp1’], dec)) + ’ (RR 1:1.5)’ + chr(10)
m += ‘TP2   : ’ + str(round(res[‘tp2’], dec)) + ’ (RR 1:2.5)’ + chr(10)
m += ‘TP3   : ’ + str(round(res[‘tp3’], dec)) + ’ (RR 1:4)’ + chr(10)
m += ’Lot   : ’ + str(res[‘lot’]) + chr(10)
m += ‘========================’ + chr(10)
m += ’Confiance : ’ + str(res[‘conf’]) + ‘% (’ + str(res[‘sc’]) + ‘/’ + str(res[‘MAX’]) + ‘)’ + chr(10)
m += ’Session : ’ + sess + chr(10)
m += ’D1  : ’ + res[‘sd1’] + chr(10)
m += ’H4  : ’ + res[‘sh4’] + chr(10)
m += ’H1  : ’ + res[‘sh1’] + chr(10)
m += ’M15 : ’ + res[‘sm15’] + chr(10)
m += ’RSI : ’ + str(round(res[‘rsi’],1)) + ’ Stoch : ’ + str(round(res[‘stoch’],1)) + chr(10)
if res[‘cv’] != ‘NONE’: m += ’Bougie : ’ + res[‘cv’] + chr(10)
if res[‘vsp’]: m += ‘Volume spike’ + chr(10)
nc = res[‘nc’]
if nc[‘status’] != ‘CLEAR’:
m += ‘========================’ + chr(10)
m += ’NEWS : ’ + nc[‘reason’] + chr(10)
m += nc[‘action’] + chr(10)
m += ‘========================’ + chr(10)
m += ‘Confluences :’ + chr(10)
for x in res[‘reasons’]:
m += ’  - ’ + x + chr(10)
m += ‘========================’ + chr(10)
m += ‘Risque 1% - Signal indicatif’
return m

def check(pair, events):
name = pair[‘name’]
sess, active, smult = session()
if not active: return
if not daily_ok(): return
nc = classify_news(name, events)
if nc[‘status’] == ‘WAIT’:
key = name + nc[‘reason’]
if last_news_alert.get(name) != key:
last_news_alert[name] = key
send(‘PAUSE ’ + name + chr(10) + nc[‘reason’] + chr(10) + nc[‘action’] + chr(10) + ‘Signal apres la news’)
return
last_news_alert[name] = None
res = analyze(name, pair[‘kraken’], nc, smult)
if not res: return
sig = res[‘sig’]
cur = open_pos.get(name)
if cur and cur != sig:
send(‘RETOURNEMENT ’ + name + chr(10) + ‘Ferme ’ + cur + chr(10) + ‘Nouveau : ’ + sig)
key = name + sig
if last_signals.get(key): return
last_signals[key] = True
open_pos[name] = sig
daily[‘count’] += 1
send(fmt(res, name, sess))
print(’[’ + datetime.now().strftime(’%H:%M’) + ’] ’ + name + ’ ’ + sig + ’ ’ + str(res[‘conf’]) + ‘%’)

def reset_check():
global last_reset
if (datetime.now() - last_reset).seconds > 14400:
last_signals.clear()
last_reset = datetime.now()

now_str = datetime.now().strftime(’%d/%m/%Y %H:%M’)
send(’ARBI BOT PRO v6 - ’ + now_str + chr(10) + ‘Paires : EUR/USD GBP/USD USD/JPY XAU/USD’ + chr(10) + ‘D1 > H4 > H1 > M15’ + chr(10) + ‘En surveillance…’)
print(‘Bot demarre’)

while True:
try:
events = get_news()
for p in PAIRS:
try:
check(p, events)
except Exception as ex:
print(‘Error ’ + p[‘name’] + ‘: ’ + str(ex))
time.sleep(2)
reset_check()
print(’[’ + datetime.now().strftime(’%H:%M’) + ‘] Cycle ok’)
time.sleep(SCAN_INTERVAL)
except KeyboardInterrupt:
break
except Exception as ex:
print(’Erreur: ’ + str(ex))
time.sleep(60)
