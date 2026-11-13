import yfinance as yf
import pandas as pd
import numpy as np
import requests
import json
import os
import time
import urllib.request
import ssl
from datetime import datetime, timedelta, timezone

# ==================== ਕ੍ਰੈਡੈਂਸ਼ੀਅਲਜ਼ ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
GIST_ID = os.environ.get("GIST_ID")
GIST_TOKEN = os.environ.get("GIST_TOKEN")

# ਟਾਪ 20 ਸਭ ਤੋਂ ਵੱਧ ਲਿਕੁਡ ਸਟਾਕਸ (ਇੰਟਰਾਡੇ ਲਈ)
WATCHLIST = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS", 
    "SBIN.NS", "TATAMOTORS.NS", "TATASTEEL.NS", "M&M.NS", "MARUTI.NS",
    "AXISBANK.NS", "KOTAKBANK.NS", "BHARTIARTL.NS", "ITC.NS", "LT.NS",
    "SUNPHARMA.NS", "NTPC.NS", "POWERGRID.NS", "TITAN.NS", "BAJFINANCE.NS"
]

def get_ist_time():
    return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    try: urllib.request.urlopen(req, context=ctx, timeout=10)
    except Exception as e: print(f"Telegram Error: {e}", flush=True)

# ==================== GIST ਹੈਂਡਲਿੰਗ ====================
def load_trades():
    if not GIST_ID or not GIST_TOKEN: return {"active": [], "history": []}
    headers = {"Authorization": f"token {GIST_TOKEN}"}
    try:
        res = requests.get(f"https://api.github.com/gists/{GIST_ID}", headers=headers)
        if res.status_code == 200:
            return json.loads(res.json()['files']['intraday_trades.json']['content'])
    except: pass
    return {"active": [], "history": []}

def save_trades(trades):
    if not GIST_ID or not GIST_TOKEN: return
    headers = {"Authorization": f"token {GIST_TOKEN}"}
    payload = {"files": {"intraday_trades.json": {"content": json.dumps(trades, indent=4)}}}
    try: requests.patch(f"https://api.github.com/gists/{GIST_ID}", headers=headers, json=payload)
    except: pass

# ==================== ਡੇਟਾ ਫੈਚਿੰਗ ====================
def fetch_data(ticker, interval="5m"):
    try:
        df = yf.download(ticker, period="1d", interval=interval, progress=False)
        if df.empty: return None
        
        # VWAP ਦਾ ਹਿਸਾਬ
        df['Typical'] = (df['High'] + df['Low'] + df['Close']) / 3
        df['TP_Vol'] = df['Typical'] * df['Volume']
        df['VWAP'] = df['TP_Vol'].cumsum() / df['Volume'].cumsum()
        
        # EMA ਅਤੇ RSI ਦਾ ਹਿਸਾਬ
        df['EMA9'] = df['Close'].ewm(span=9, adjust=False).mean()
        df['EMA21'] = df['Close'].ewm(span=21, adjust=False).mean()
        
        delta = df['Close'].diff()
        gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
        rs = gain / loss.replace(0, np.nan)
        df['RSI'] = 100 - (100 / (1 + rs))
        
        return df
    except: return None

# ==================== ਟ੍ਰੇਡ ਟ੍ਰੈਕਿੰਗ ====================
def check_trades(trades):
    if not trades["active"]: return trades
    remaining = []
    
    for t in trades["active"]:
        df = fetch_data(t["symbol"])
        if df is None or df.empty:
            remaining.append(t)
            continue
            
        curr_price = float(df['Close'].iloc[-1])
        
        status = None
        if curr_price >= t["target"]: status = "TARGET_HIT ✅"
        elif curr_price <= t["sl"]: status = "SL_HIT ❌"
        
        # 2:55 PM ਤੋਂ ਬਾਅਦ ਸਾਰੇ ਟ੍ਰੇਡ ਬੰਦ
        now = get_ist_time()
        if now.hour == 14 and now.minute >= 55:
            status = "EOD_EXIT ⏰"
            
        if status:
            t["status"] = status
            t["exit_price"] = curr_price
            trades["history"].append(t)
            emoji = "✅" if "TARGET" in status else ("❌" if "SL" in status else "⏰")
            send_telegram(f"{emoji} <b>{t['symbol']} ਟ੍ਰੇਡ ਬੰਦ</b>\n{status}\nEntry: ₹{t['entry']:.2f} | Exit: ₹{curr_price:.2f}")
        else:
            remaining.append(t)
            
    trades["active"] = remaining
    return trades

# ==================== ਮੁੱਖ ਲੂਪ ====================
def main():
    now = get_ist_time()
    
    if now.weekday() >= 5:
        send_telegram("📴 <b>LowriX Intraday:</b> ਅੱਜ ਵੀਕੈਂਡ ਹੈ, ਬੋਟ ਬੰਦ ਹੈ।")
        return

    if now.hour >= 15 or (now.hour == 14 and now.minute >= 55):
        send_telegram("⏰ <b>LowriX Intraday:</b> ਮਾਰਕੀਟ ਬੰਦ ਹੋ ਗਈ ਹੈ। ਕੱਲ੍ਹ ਸਵੇਰੇ ਦੁਬਾਰਾ ਮਿਲਦੇ ਹਾਂ।")
        return

    send_telegram("✅ <b>LowriX Intraday Bot ਚਾਲੂ ਹੋ ਗਿਆ ਹੈ</b>\nਅਸੀਂ 9:30 ਤੋਂ ਬਾਅਦ ਸਿਗਨਲ ਦੇਵਾਂਗੇ।")
    
    trades = load_trades()
    signals_found = False

    # 🚨 ਇੰਟਰਾਡੇ ਲੂਪ
    while True:
        now = get_ist_time()
        
        if now.hour >= 15 or (now.hour == 14 and now.minute >= 55):
            print("ਇੰਟਰਾਡੇ ਸੈਸ਼ਨ ਖਤਮ ਹੋ ਗਿਆ (2:55 PM)।")
            break
            
        if now.hour == 9 and now.minute < 30:
            print("9:30 AM ਤੱਕ ਇੰਤਜ਼ਾਰ...")
            time.sleep(60)
            continue
            
        print(f"[{now.strftime('%H:%M')}] ਸਕੈਨ ਕਰ ਰਹੇ ਹਾਂ...")
        
        trades = check_trades(trades)
        
        for ticker in WATCHLIST:
            if any(t["symbol"] == ticker for t in trades["active"]): continue
            
            df_5m = fetch_data(ticker, "5m")
            df_15m = fetch_data(ticker, "15m")
            
            if df_5m is None or df_15m is None or len(df_5m) < 20: continue
            
            # 15m ਦਾ ਟ੍ਰੈਂਡ
            c15 = df_15m.iloc[-1]
            htf_bull = float(c15['Close']) > float(c15['EMA21'])
            
            # 5m ਦਾ ਐਂਟਰੀ
            c5 = df_5m.iloc[-1]
            if htf_bull and (float(c5['Close']) > float(c5['VWAP'])) and (float(c5['EMA9']) > float(c5['EMA21'])) and (55 <= float(c5['RSI']) <= 75):
                entry = float(c5['Close'])
                sl = entry * 0.99 # 1% SL
                target = entry * 1.015 # 1.5% Target
                
                trade = {
                    "symbol": ticker, "entry": round(entry, 2), 
                    "sl": round(sl, 2), "target": round(target, 2),
                    "time": now.strftime("%H:%M")
                }
                trades["active"].append(trade)
                signals_found = True
                
                msg = f"🚀 <b>INTRADAY BUY SIGNAL</b>\n\n"
                msg += f"📊 {ticker}\n"
                msg += f"💰 Entry: ₹{entry:.2f}\n"
                msg += f"🛑 SL: ₹{sl:.2f} (1%)\n"
                msg += f"🎯 Target: ₹{target:.2f} (1.5%)\n"
                msg += f"⏰ ਸਮਾਂ: {now.strftime('%H:%M')}"
                send_telegram(msg)
                
        save_trades(trades)
        time.sleep(300) # 5 ਮਿੰਟ ਦੀ ਉਡੀਕ

    if not signals_found:
        send_telegram("📊 <b>LowriX Intraday:</b> ਅੱਜ ਦਿਨ ਭਰ ਸਕੈਨ ਕੀਤਾ, ਪਰ ਕੋਈ ਵੀ ਸਟਾਕ ਸਾਡੀਆਂ ਸ਼ਰਤਾਂ (VWAP, RSI, Trend) 'ਤੇ ਖਰਾ ਨਹੀਂ ਉਤਰਿਆ।")

if __name__ == "__main__":
    main()
