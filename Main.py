import requests
import time

TOKEN = "8636672541:AAElNEq4IKwrRzTLuqoaqttadmkGKAVEVlM"
IDS = ["525011337", "7276558677"]

PAIRS = [
    {"name": "EUR/USD", "kraken": "EURUSD"},
    {"name": "GBP/USD", "kraken": "GBPUSD"},
    {"name": "USD/JPY", "kraken": "USDJPY"},
]

def send(msg):
    for cid in IDS:
        try:
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                json={"chat_id": cid, "text": msg}, timeout=10)
        except:
            pass
        time.sleep(1)

def candles(pair):
    r = requests.get("https://api.kraken.com/0/public/OHLC",
        params={"pair": pair, "interval": 60}, timeout=10)
    d = r.json()["result"]
    k = [x for x in d if x != "last"][0]
    return [float(c[4]) for c in d[k][-100:]]

def ema(closes, n):
    k = 2/(n+1)
    e = sum(closes[:n])/n
    for p in closes[n:]:
        e = p*k + e*(1-k)
    return e

def rsi(closes):
    g = l = 0
    for i in range(len(closes)-14, len(closes)):
        d = closes[i]-closes[i-1]
        if d > 0: g += d
        else: l -= d
    return 100 - 100/(1+g/(l or 0.001))

last = {}

def check(pair):
    c = candles(pair["kraken"])
    e9 = ema(c, 9)
    e21 = ema(c, 21)
    e50 = ema(c, 50)
    r = rsi(c)
    price = c[-1]
    score = 0
    if r < 32: score += 2
    elif r > 68: score -= 2
    if e9 > e21: score += 1
    else: score -= 1
    if e21 > e50: score += 1
    else: score -= 1
    sig = "ACHAT" if score >= 3 else "VENTE" if score <= -2 else "ATTENDRE"
    if sig != "ATTENDRE" and last.get(pair["name"]) != sig:
        last[pair["name"]] = sig
        msg = f"SIGNAL {sig}\n{pair['name']}\nPrix: {price:.5f}\nRSI: {r:.1f}\nConf: {min(95,abs(score)*15+25)}%\nSignal indicatif"
        send(msg)
        print(f"Signal envoye: {pair['name']} {sig}")

send("ARBI BOT DEMARRE - Surveillance en cours...")
print("Bot demarre")

while True:
    for p in PAIRS:
        try:
            check(p)
        except Exception as e:
            print(f"Erreur: {e}")
        time.sleep(2)
    time.sleep(300)
