import requests
import time

TOKEN = "8636672541:AAElNEq4IKwrRzTLuqoaqttadmkGKAVEVlM"
IDS = ["525011337", "7276558677"]

def send(msg):
    for cid in IDS:
        try:
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                json={"chat_id": cid, "text": msg}, timeout=10)
        except:
            pass
        time.sleep(1)

send("BOT DEMARRE !")
print("Message envoye")

while True:
    time.sleep(60)
    print("Bot actif...")
