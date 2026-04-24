#!/usr/bin/env python3
import requests
import time
from datetime import datetime, timezone

TOKEN = ‘8636672541:AAElNEq4IKwrRzTLuqoaqttadmkGKAVEVlM’
IDS = [‘525011337’, ‘7276558677’]

PAIRS = [
{‘name’: ‘EUR/USD’, ‘kraken’: ‘EURUSD’,  ‘pip’: 0.0001, ‘pip_val’: 10},
{‘name’: ‘GBP/USD’, ‘kraken’: ‘GBPUSD’,  ‘pip’: 0.0001, ‘pip_val’: 10},
{‘name’: ‘USD/JPY’, ‘kraken’: ‘USDJPY’,  ‘pip’: 0.01,   ‘pip_val’: 9},
{‘name’: ‘XAU/USD’, ‘kraken’: ‘XAUUSD’,  ‘pip’: 0.1,    ‘pip_val’: 1},
]

CAPITAL = 10000
RISK_PCT = 1.0
MAX_TRADES = 3
SCAN_INTERVAL = 300

last_signals = {}
open_pos = {}
daily = {‘date’: ‘’, ‘count’: 0, ‘losses’: 0}
last_news_alert = {}
last_reset = datetime.now()

def send(msg):
for cid in IDS:
try:
requests.post(
‘https://api.telegram.org/bot’ + TOKEN + ‘/sendMessage’,
json={‘chat_id’: cid, ‘text’: msg},
timeout=10
)
except Exception as e:
print(’Telegram error: ’ + str(e))
time.sleep(0.3)

def ohlc(pair, interval=60, count=200):
try:
r = requests.get(
‘https://api.kraken.com/0/public/OHLC’,
params={‘pair’: pair, ‘interval’: interval},
timeout=10
)
d = r.json()[‘result’]
k = [x for x in d if x != ‘last’][0]
rows = d[k][-count:]
return {
‘o’: [float(x[1]) for x in rows],
‘h’: [float(x[2]) for x in rows],
‘l’: [float(x[3]) for x in rows],
‘c’: [float(x[4]) for x in rows],
‘v’: [float(x[6]) for x in rows],
}
except Exception as e:
print(’OHLC error ’ + pair + ’: ’ + str(e))
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
l = 0.0
for i in range(len(c) - n, len(c)):
d = c[i] - c[i - 1]
if d > 0:
g += d
else:
l -= d
return 100 - 100 / (1 + g / (l or 0.001))

def rsi_divergence(c):
if len(c) < 40:
return ‘NONE’
r1 = rsi(c[-40:-20])
r2 = rsi(c[-20:])
p1 = min(c[-40:-20])
p2 = min(c[-20:])
ph1 = max(c[-40:-20])
ph2 = max(c[-20:])
if p2 < p1 and r2 > r1:
return ‘BULL_DIV’
if ph2 > ph1 and r2 < r1:
return ‘BEAR_DIV’
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
trs = [max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1])) for i in range(1, len(c))]
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

def swing_points(h, l, lb=5):
sh = []
sl = []
for i in range(lb, len(h) - lb):
if all(h[i] >= h[i-j] for j in range(1, lb+1)) and all(h[i] >= h[i+j] for j in range(1, lb+1)):
sh.append((i, h[i]))
if all(l[i] <= l[i-j] for j in range(1, lb+1)) and all(l[i] <= l[i+j] for j in range(1, lb+1)):
sl.append((i, l[i]))
return sh, sl

def market_structure(h, l, c):
sh, sl = swing_points(h, l)
if len(sh) < 2 or len(sl) < 2:
return ‘NEUTRAL’, ‘NONE’, ‘NONE’
hh = sh[-1][1] > sh[-2][1]
hl = sl[-1][1] > sl[-2][1]
lh = sh[-1][1] < sh[-2][1]
ll = sl[-1][1] < sl[-2][1]
if hh and hl:
struct = ‘BULLISH’
elif lh and ll:
struct = ‘BEARISH’
else:
struct = ‘NEUTRAL’
price = c[-1]
bos = ‘NONE’
choch = ‘NONE’
if struct == ‘BULLISH’ and price > sh[-1][1]:
bos = ‘BOS_BULL’
if struct == ‘BEARISH’ and price < sl[-1][1]:
bos = ‘BOS_BEAR’
if struct == ‘BULLISH’ and price < sl[-1][1]:
choch = ‘CHOCH_BEAR’
if struct == ‘BEARISH’ and price > sh[-1][1]:
choch = ‘CHOCH_BULL’
return struct, bos, choch

def order_blocks(o, h, l, c, lb=50):
bull_obs = []
bear_obs = []
start = max(1, len(c) - lb)
for i in range(start, len(c) - 1):
if c[i] < o[i] and c[i+1] > h[i]:
bull_obs.append({‘h’: h[i], ‘l’: l[i], ‘mid’: (h[i] + l[i]) / 2})
if c[i] > o[i] and c[i+1] < l[i]:
bear_obs.append({‘h’: h[i], ‘l’: l[i], ‘mid’: (h[i] + l[i]) / 2})
return bull_obs[-3:], bear_obs[-3:]

def fair_value_gaps(h, l, lb=50):
bull_fvg = []
bear_fvg = []
start = max(0, len(h) - lb)
for i in range(start, len(h) - 2):
if l[i+2] > h[i]:
bull_fvg.append({‘top’: l[i+2], ‘bot’: h[i], ‘mid’: (l[i+2] + h[i]) / 2})
if h[i+2] < l[i]:
bear_fvg.append({‘top’: l[i], ‘bot’: h[i+2], ‘mid’: (l[i] + h[i+2]) / 2})
return bull_fvg[-3:], bear_fvg[-3:]

def liquidity_sweep(h, l, c):
sh, sl = swing_points(h, l)
if not sh or not sl:
return False, False
prev = c[-2]
price = c[-1]
swept_high = prev > sh[-1][1] and price < sh[-1][1]
swept_low = prev < sl[-1][1] and price > sl[-1][1]
return swept_high, swept_low

def candle_pattern(o, h, l, c):
if len(c) < 2:
return ‘NONE’
body = abs(c[-1] - o[-1])
rng = h[-1] - l[-1]
if rng == 0:
return ‘NONE’
low_wick = min(o[-1], c[-1]) - l[-1]
up_wick = h[-1] - max(o[-1], c[-1])
if low_wick > body * 2 and up_wick < body * 0.5:
return ‘BULL_PIN’
if up_wick > body * 2 and low_wick < body * 0.5:
return ‘BEAR_PIN’
if c[-1] > o[-1] and c[-2] < o[-2] and c[-1] > o[-2] and o[-1] < c[-2] and body / rng > 0.6:
return ‘BULL_ENGULF’
if c[-1] < o[-1] and c[-2] > o[-2] and c[-1] < o[-2] and o[-1] > c[-2] and body / rng > 0.6:
return ‘BEAR_ENGULF’
return ‘NONE’

def price_in_ob(price, obs):
for ob in obs:
if ob[‘l’] <= price <= ob[‘h’]:
return True
return False

def price_near_fvg(price, fvgs, thr=0.0025):
for fvg in fvgs:
if abs(price - fvg[‘mid’]) / price < thr:
return True
return False

def get_news():
try:
r = requests.get(
‘https://nfs.faireconomy.media/ff_calendar_thisweek.json’,
timeout=10
)
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

```
upcoming_high = []
just_released = []
recent_high = []
upcoming_medium = []

for e in events:
    impact = e.get('impact', '')
    cur = e.get('country', '').upper()
    if not any(c in cur for c in curs):
        continue
    if impact not in ['High', 'Medium']:
        continue
    try:
        et = datetime.strptime(e['date'], '%Y-%m-%dT%H:%M:%S%z')
        diff = (et - now).total_seconds() / 60
        if impact == 'High':
            if 0 < diff <= 45:
                upcoming_high.append({'title': e.get('title', ''), 'currency': e.get('country', ''), 'mins': int(diff)})
            elif -15 <= diff <= 0:
                just_released.append({'title': e.get('title', ''), 'currency': e.get('country', ''), 'mins': int(diff)})
            elif -60 <= diff < -15:
                recent_high.append({'title': e.get('title', ''), 'currency': e.get('country', ''), 'mins': int(diff)})
        elif impact == 'Medium':
            if 0 < diff <= 20:
                upcoming_medium.append({'title': e.get('title', ''), 'currency': e.get('country', ''), 'mins': int(diff)})
    except:
        pass

if upcoming_high:
    n = upcoming_high[0]
    return {'status': 'WAIT', 'reason': 'News ROUGE dans ' + str(n['mins']) + 'min : ' + n['title'], 'action': 'Attendre la sortie puis trader la reaction'}

if just_released:
    n = just_released[0]
    return {'status': 'TRADE_AFTER', 'reason': 'News ROUGE sortie il y a ' + str(abs(n['mins'])) + 'min : ' + n['title'], 'action': 'Trader la reaction - confirmer sur M15'}

if recent_high:
    n = recent_high[0]
    return {'status': 'TRADE_AFTER', 'reason': 'Post-news ' + str(abs(n['mins'])) + 'min : ' + n['title'], 'action': 'Marche en digestion - confirmer tendance'}

if upcoming_medium:
    n = upcoming_medium[0]
    return {'status': 'CAUTION', 'reason': 'News ORANGE dans ' + str(n['mins']) + 'min : ' + n['title'], 'action': 'Trade possible mais lot reduit 50%'}

return {'status': 'CLEAR', 'reason': 'Aucune news impactante', 'action': 'Trading normal'}
```

def session():
h = datetime.now(timezone.utc).hour
if 7 <= h < 12:
return ‘Londres’, True, 1.0
if 12 <= h < 16:
return ‘Londres+NY’, True, 1.2
if 16 <= h < 21:
return ‘New York’, True, 1.0
if 2 <= h < 5:
return ‘Tokyo’, True, 0.7
return ‘Hors session’, False, 0

def lot_size(sl_pips, pip_val=10, reduce=1.0):
risk = CAPITAL * RISK_PCT / 100 * reduce
lot = risk / (sl_pips * pip_val) if sl_pips > 0 else 0.01
return round(max(0.01, min(lot, 2.0)), 2)

def daily_ok():
today = datetime.now().strftime(’%Y-%m-%d’)
if daily[‘date’] != today:
daily.update({‘date’: today, ‘count’: 0, ‘losses’: 0})
if daily[‘count’] >= MAX_TRADES:
return False, ‘Max ’ + str(MAX_TRADES) + ’ trades/jour atteint’
if daily[‘losses’] >= 2:
return False, ‘2 pertes consecutives - pause trading’
return True, ‘OK’

def analyze(pair_name, kraken_pair, news_ctx, session_mult):
D1 = ohlc(kraken_pair, 1440, 60)
H4 = ohlc(kraken_pair, 240, 100)
H1 = ohlc(kraken_pair, 60, 200)
M15 = ohlc(kraken_pair, 15, 150)

```
if not H4 or not H1 or not M15:
    return None

price = H1['c'][-1]
if 'JPY' in pair_name:
    dec = 3
elif 'XAU' in pair_name:
    dec = 1
else:
    dec = 5

struct_d1 = 'NEUTRAL'
if D1:
    struct_d1, _, _ = market_structure(D1['h'], D1['l'], D1['c'])

e200_h4 = ema(H4['c'], 100)
struct_h4, _, _ = market_structure(H4['h'], H4['l'], H4['c'])

e50 = ema(H1['c'], 50)
r = rsi(H1['c'])
rdiv = rsi_divergence(H1['c'])
m = macd(H1['c'])
bb_u, bb_l, bb_m = bollinger(H1['c'])
atr_v = atr(H1['h'], H1['l'], H1['c'])
sto = stoch(H1['h'], H1['l'], H1['c'])
vol_sp = volume_spike(H1['v'])
candle = candle_pattern(H1['o'], H1['h'], H1['l'], H1['c'])

struct_h1, bos_h1, _ = market_structure(H1['h'], H1['l'], H1['c'])
bull_ob, bear_ob = order_blocks(H1['o'], H1['h'], H1['l'], H1['c'])
bull_fvg, bear_fvg = fair_value_gaps(H1['h'], H1['l'])
swept_high, swept_low = liquidity_sweep(H1['h'], H1['l'], H1['c'])
in_bull_ob = price_in_ob(price, bull_ob)
in_bear_ob = price_in_ob(price, bear_ob)
near_bull_fvg = price_near_fvg(price, bull_fvg)
near_bear_fvg = price_near_fvg(price, bear_fvg)

struct_m15, _, choch_m15 = market_structure(M15['h'], M15['l'], M15['c'])
candle_m15 = candle_pattern(M15['o'], M15['h'], M15['l'], M15['c'])
swept_high_m15, swept_low_m15 = liquidity_sweep(M15['h'], M15['l'], M15['c'])

bull_score = 0
bull_reasons = []

if struct_d1 == 'BULLISH':
    bull_score += 3
    bull_reasons.append('D1 tendance haussiere')
if struct_h4 == 'BULLISH':
    bull_score += 2
    bull_reasons.append('H4 structure HH+HL')
if struct_h1 == 'BULLISH':
    bull_score += 2
    bull_reasons.append('H1 structure haussiere')
if price > e200_h4:
    bull_score += 1
    bull_reasons.append('Prix > EMA200 H4')
if swept_low:
    bull_score += 3
    bull_reasons.append('Sweep liquidite bas H1')
if swept_low_m15:
    bull_score += 2
    bull_reasons.append('Sweep liquidite bas M15')
if in_bull_ob:
    bull_score += 3
    bull_reasons.append('Prix dans Order Block haussier')
if near_bull_fvg:
    bull_score += 2
    bull_reasons.append('Prix proche FVG haussier')
if bos_h1 == 'BOS_BULL':
    bull_score += 2
    bull_reasons.append('Break of Structure haussier H1')
if choch_m15 == 'CHOCH_BULL':
    bull_score += 2
    bull_reasons.append('Change of Character bullish M15')
if r < 35:
    bull_score += 2
    bull_reasons.append('RSI survendu ' + str(round(r, 1)))
if rdiv == 'BULL_DIV':
    bull_score += 2
    bull_reasons.append('Divergence RSI haussiere')
if m > 0:
    bull_score += 1
    bull_reasons.append('MACD positif')
if price < bb_l:
    bull_score += 2
    bull_reasons.append('Prix sous BB basse')
if sto < 20:
    bull_score += 2
    bull_reasons.append('Stochastique survendu ' + str(round(sto, 1)))
if price > e50:
    bull_score += 1
    bull_reasons.append('Prix > EMA50')
if candle in ['BULL_PIN', 'BULL_ENGULF']:
    bull_score += 2
    bull_reasons.append('Pattern bougie : ' + candle)
if candle_m15 in ['BULL_PIN', 'BULL_ENGULF']:
    bull_score += 1
    bull_reasons.append('Pattern M15 : ' + candle_m15)
if vol_sp:
    bull_score += 1
    bull_reasons.append('Volume spike confirme')
if news_ctx['status'] == 'TRADE_AFTER':
    bull_score += 1
    bull_reasons.append('Post-news : opportunite')

bear_score = 0
bear_reasons = []

if struct_d1 == 'BEARISH':
    bear_score += 3
    bear_reasons.append('D1 tendance baissiere')
if struct_h4 == 'BEARISH':
    bear_score += 2
    bear_reasons.append('H4 structure LH+LL')
if struct_h1 == 'BEARISH':
    bear_score += 2
    bear_reasons.append('H1 structure baissiere')
if price < e200_h4:
    bear_score += 1
    bear_reasons.append('Prix < EMA200 H4')
if swept_high:
    bear_score += 3
    bear_reasons.append('Sweep liquidite haut H1')
if swept_high_m15:
    bear_score += 2
    bear_reasons.append('Sweep liquidite haut M15')
if in_bear_ob:
    bear_score += 3
    bear_reasons.append('Prix dans Order Block baissier')
if near_bear_fvg:
    bear_score += 2
    bear_reasons.append('Prix proche FVG baissier')
if bos_h1 == 'BOS_BEAR':
    bear_score += 2
    bear_reasons.append('Break of Structure baissier H1')
if choch_m15 == 'CHOCH_BEAR':
    bear_score += 2
    bear_reasons.append('Change of Character bearish M15')
if r > 65:
    bear_score += 2
    bear_reasons.append('RSI surachete ' + str(round(r, 1)))
if rdiv == 'BEAR_DIV':
    bear_score += 2
    bear_reasons.append('Divergence RSI baissiere')
if m < 0:
    bear_score += 1
    bear_reasons.append('MACD negatif')
if price > bb_u:
    bear_score += 2
    bear_reasons.append('Prix au-dessus BB haute')
if sto > 80:
    bear_score += 2
    bear_reasons.append('Stochastique surachete ' + str(round(sto, 1)))
if price < e50:
    bear_score += 1
    bear_reasons.append('Prix < EMA50')
if candle in ['BEAR_PIN', 'BEAR_ENGULF']:
    bear_score += 2
    bear_reasons.append('Pattern bougie : ' + candle)
if candle_m15 in ['BEAR_PIN', 'BEAR_ENGULF']:
    bear_score += 1
    bear_reasons.append('Pattern M15 : ' + candle_m15)
if vol_sp:
    bear_score += 1
    bear_reasons.append('Volume spike confirme')
if news_ctx['status'] == 'TRADE_AFTER':
    bear_score += 1
    bear_reasons.append('Post-news : opportunite')

MAX_SCORE = 30
THRESHOLD = 10

if bull_score >= THRESHOLD and bull_score > bear_score:
    signal = 'ACHAT'
    score = bull_score
    reasons = bull_reasons
elif bear_score >= THRESHOLD and bear_score > bull_score:
    signal = 'VENTE'
    score = bear_score
    reasons = bear_reasons
else:
    return None

confidence = min(95, int(score / MAX_SCORE * 100))

sh_pts, sl_pts = swing_points(H1['h'], H1['l'])

if signal == 'ACHAT':
    sl_struct = sl_pts[-1][1] - atr_v * 0.3 if sl_pts else price - atr_v * 1.5
    sl = min(sl_struct, price - atr_v * 1.5)
    tp1 = price + (price - sl) * 1.5
    tp2 = price + (price - sl) * 2.5
    tp3 = price + (price - sl) * 4.0
else:
    sl_struct = sh_pts[-1][1] + atr_v * 0.3 if sh_pts else price + atr_v * 1.5
    sl = max(sl_struct, price + atr_v * 1.5)
    tp1 = price - (sl - price) * 1.5
    tp2 = price - (sl - price) * 2.5
    tp3 = price - (sl - price) * 4.0

if 'JPY' in pair_name:
    pip_size = 0.01
elif 'XAU' in pair_name:
    pip_size = 0.1
else:
    pip_size = 0.0001

sl_pips = abs(price - sl) / pip_size
pip_val = next((p['pip_val'] for p in PAIRS if p['name'] == pair_name), 10)
lot_mult = 0.5 if news_ctx['status'] == 'CAUTION' else 1.0
lot_mult = lot_mult * session_mult
lot = lot_size(sl_pips, pip_val, lot_mult)

return {
    'signal': signal,
    'score': score,
    'max_score': MAX_SCORE,
    'confidence': confidence,
    'price': price,
    'sl': sl,
    'tp1': tp1,
    'tp2': tp2,
    'tp3': tp3,
    'sl_pips': sl_pips,
    'lot': lot,
    'rsi': r,
    'stoch': sto,
    'struct_d1': struct_d1,
    'struct_h4': struct_h4,
    'struct_h1': struct_h1,
    'struct_m15': struct_m15,
    'candle': candle,
    'vol_spike': vol_sp,
    'reasons': reasons[:8],
    'dec': dec,
    'news_ctx': news_ctx,
}
```

def format_signal(result, pair_name, sess_name):
sig = result[‘signal’]
dec = result[‘dec’]
conf = result[‘confidence’]
news = result[‘news_ctx’]

```
if sig == 'ACHAT':
    icon = 'BUY'
else:
    icon = 'SELL'

msg = icon + ' SIGNAL ' + sig + ' - ' + pair_name + '\n'
msg += '========================\n'
msg += 'Prix  : ' + str(round(result['price'], dec)) + '\n'
msg += 'SL    : ' + str(round(result['sl'], dec)) + ' (' + str(round(result['sl_pips'], 0)) + ' pips)\n'
msg += 'TP1   : ' + str(round(result['tp1'], dec)) + ' (RR 1:1.5)\n'
msg += 'TP2   : ' + str(round(result['tp2'], dec)) + ' (RR 1:2.5)\n'
msg += 'TP3   : ' + str(round(result['tp3'], dec)) + ' (RR 1:4)\n'
msg += 'Lot   : ' + str(result['lot']) + '\n'
msg += '========================\n'
msg += 'Confiance : ' + str(conf) + '% (' + str(result['score']) + '/' + str(result['max_score']) + ')\n'
msg += 'Session   : ' + sess_name + '\n'
msg += 'D1  : ' + result['struct_d1'] + '\n'
msg += 'H4  : ' + result['struct_h4'] + '\n'
msg += 'H1  : ' + result['struct_h1'] + '\n'
msg += 'M15 : ' + result['struct_m15'] + '\n'
msg += 'RSI : ' + str(round(result['rsi'], 1)) + ' | Stoch : ' + str(round(result['stoch'], 1)) + '\n'
if result['candle'] != 'NONE':
    msg += 'Bougie : ' + result['candle'] + '\n'
if result['vol_spike']:
    msg += 'Volume spike detecte\n'
if news['status'] != 'CLEAR':
    msg += '========================\n'
    msg += 'NEWS : ' + news['reason'] + '\n'
    msg += news['action'] + '\n'
msg += '========================\n'
msg += 'Confluences SMC :\n'
for reason in result['reasons']:
    msg += '  - ' + reason + '\n'
msg += '========================\n'
msg += 'Risque : 1% | Signal indicatif\n'
msg += 'Gere ton MM - trade prudemment'
return msg
```

def check(pair, news_events):
name = pair[‘name’]
sess_name, active, sess_mult = session()
if not active:
return
ok, reason = daily_ok()
if not ok:
return

```
news_ctx = classify_news(name, news_events)

if news_ctx['status'] == 'WAIT':
    alert_key = name + news_ctx['reason']
    if last_news_alert.get(name) != alert_key:
        last_news_alert[name] = alert_key
        msg = 'PAUSE - ' + name + '\n'
        msg += news_ctx['reason'] + '\n'
        msg += news_ctx['action'] + '\n'
        msg += 'Signal envoye apres la news'
        send(msg)
    return
else:
    last_news_alert[name] = None

result = analyze(name, pair['kraken'], news_ctx, sess_mult)
if not result:
    return

sig = result['signal']
current = open_pos.get(name)
if current and current != sig:
    send('RETOURNEMENT ' + name + '\nFerme ta position ' + current + '\nNouveau signal : ' + sig)

sig_key = name + '_' + sig
if last_signals.get(sig_key):
    return

last_signals[sig_key] = True
open_pos[name] = sig
daily['count'] += 1

msg = format_signal(result, name, sess_name)
send(msg)
print('[' + datetime.now().strftime('%H:%M') + '] Signal ' + name + ' ' + sig + ' conf=' + str(result['confidence']) + '%')
```

def maybe_reset_signals():
global last_reset
if (datetime.now() - last_reset).seconds > 14400:
last_signals.clear()
last_reset = datetime.now()
print(’[RESET] Signaux reinitialises’)

now_str = datetime.now().strftime(’%d/%m/%Y %H:%M’)
msg_start = ’ARBI BOT PRO v6 - ’ + now_str + ‘\n’
msg_start += ‘Paires : EUR/USD | GBP/USD | USD/JPY | XAU/USD\n’
msg_start += ‘Analyse : D1 > H4 > H1 > M15\n’
msg_start += ‘News : Logique Pro\n’
msg_start += ’Capital : ’ + str(CAPITAL) + ’$ | Risque : ’ + str(RISK_PCT) + ‘%\n’
msg_start += ‘En surveillance…’
send(msg_start)
print(‘ArbiBot Pro v6 demarre’)

while True:
try:
news_events = get_news()
for p in PAIRS:
try:
check(p, news_events)
except Exception as e:
print(‘Error ’ + p[‘name’] + ‘: ’ + str(e))
time.sleep(2)
maybe_reset_signals()
print(’[’ + datetime.now().strftime(’%H:%M’) + ‘] Cycle termine’)
time.sleep(SCAN_INTERVAL)
except KeyboardInterrupt:
print(‘Bot arrete’)
break
except Exception as e:
print(’Erreur globale: ’ + str(e))
time.sleep(60)
