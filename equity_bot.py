import urllib.request
import json
import ssl
import time
import pandas as pd
from datetime import datetime, timedelta, timezone
import os

# ==================== ਟੈਲੀਗਰਾਮ ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# Nifty 50 ਦੇ ਕੁਝ ਮੁੱਖ ਸਟਾਕਸ (ਤੁਸੀਂ ਇਹਨਾਂ ਨੂੰ ਵਧਾ ਵੀ ਸਕਦੇ ਹੋ)
NIFTY_50_TICKERS = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
    "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "LT.NS", "KOTAKBANK.NS",
    "AXISBANK.NS", "TATAMOTORS.NS", "TATASTEEL.NS", "JSWSTEEL.NS", "M&M.NS",
    "SUNPHARMA.NS", "NTPC.NS", "POWERGRID.NS", "TITAN.NS", "BAJFINANCE.NS"
]

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    try:
        urllib.request.urlopen(req, context=ctx, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

# ==================== ਡੇਟਾ ਫੈਚਿੰਗ ====================
def fetch_daily_data(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1y"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            result = data['chart']['result'][0]
            quotes = result['indicators']['quote'][0]
            
            df = pd.DataFrame({
                'high': quotes['high'],
                'low': quotes['low'],
                'close': quotes['close'],
                'volume': quotes['volume']
            }).dropna()
            return df
    except Exception as e:
        return None

# ==================== ਇੰਡੀਕੇਟਰਜ਼ ====================
def calc_ema(prices, period):
    if len(prices) < period: return 0
    k = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return ema

def calc_rsi(prices, period=14):
    if len(prices) < period + 1: return 50
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        gains.append(max(diff, 0)); losses.append(max(-diff, 0))
    avg_gain = sum(gains[:period]) / period; avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0: return 100
    return 100 - (100 / (1 + (avg_gain / avg_loss)))

# ==================== ਮੁੱਖ ਸਕੈਨਰ ====================
def scan_market():
    signals = []
    print("ਮਾਰਕੀਟ ਸਕੈਨ ਕਰ ਰਹੇ ਹਾਂ... (ਇਸ ਵਿੱਚ ਕੁਝ ਸਮਾਂ ਲੱਗੇਗਾ)")
    
    for ticker in NIFTY_50_TICKERS:
        df = fetch_daily_data(ticker)
        if df is None or len(df) < 50: 
            continue
        
        closes = df['close'].tolist()
        current_close = closes[-1]
        current_vol = df['volume'].iloc[-1]
        
        ema50 = calc_ema(closes, 50)
        ema200 = calc_ema(closes, 200) if len(closes) >= 200 else 0
        rsi = calc_rsi(closes, 14)
        
        # 20 ਦਿਨਾਂ ਦਾ ਹਾਈ
        high_20 = df['high'].iloc[-21:-1].max()
        avg_vol_20 = df['volume'].iloc[-21:-1].mean()
        
        # 🚀 ਸਿਗਨਲ ਦੀਆਂ ਸ਼ਰਤਾਂ (Breakout with Volume)
        if current_close > ema50 and (ema200 == 0 or ema50 > ema200):
            if rsi > 60:
                if current_close > high_20 and current_vol > (1.5 * avg_vol_20):
                    
                    # ਰਿਸਕ ਮੈਨੇਜਮੈਂਟ (SL ਅਤੇ Target)
                    entry = current_close
                    sl = entry * 0.95 # 5% SL
                    target = entry * 1.15 # 15% Target (1:3)
                    
                    signals.append({
                        "ticker": ticker.replace(".NS", ""),
                        "entry": round(entry, 2),
                        "sl": round(sl, 2),
                        "target": round(target, 2),
                        "rsi": round(rsi, 1)
                    })
        
        time.sleep(1) # Yahoo ਨੂੰ ਬਲਾਕ ਨਾ ਕਰਨ ਲਈ 1 ਸਕਿੰਟ ਦਾ ਸਮਾਂ
        
    return signals

def main():
    signals = scan_market()
    
    if not signals:
        print("ਅੱਜ ਕੋਈ ਵਧੀਆ ਬ੍ਰੇਕਆਉਟ ਨਹੀਂ ਮਿਲਿਆ।")
        # send_telegram("📉 <b>Equity Scan:</b> ਅੱਜ ਕੋਈ ਵਧੀਆ ਸਵਿੰਗ ਸੈਟਅੱਪ ਨਹੀਂ ਮਿਲਿਆ।")
        return

    # ਸਿਰਫ਼ ਟਾਪ 2 ਸਟਾਕਸ ਭੇਜੋ (ਜਿਹਨਾਂ ਦਾ RSI ਸਭ ਤੋਂ ਵੱਧ ਹੈ)
    signals = sorted(signals, key=lambda x: x['rsi'], reverse=True)[:2]
    
    msg = "📈 <b>LowriX EQUITY SWING ALERTS</b>\n"
    msg += "(2-3 ਮਹੀਨਿਆਂ ਲਈ ਸਵਿੰਗ ਟ੍ਰੇਡ)\n\n"
    
    for sig in signals:
        msg += f"🏢 <b>{sig['ticker']}</b>\n"
        msg += f"🟢 Entry: ₹{sig['entry']}\n"
        msg += f"🛑 SL: ₹{sig['sl']} (5%)\n"
        msg += f"🎯 Target: ₹{sig['target']} (15%)\n"
        msg += f"📊 RSI: {sig['rsi']}\n"
        msg += f"🔗 <a href='https://www.screener.in/company/{sig['ticker']}/'>Fundamentals ਚੈੱਕ ਕਰੋ</a>\n\n"
        
    msg += "<i>ਧਿਆਨ ਦਿਓ: ਇਹ ਸਿਰਫ਼ ਟੈਕਨੀਕਲ ਬ੍ਰੇਕਆਉਟ ਹੈ। ਖਰੀਦਣ ਤੋਂ ਪਹਿਲਾਂ ਫੰਡਾਮੈਂਟਲ ਜ਼ਰੂਰ ਚੈੱਕ ਕਰੋ।</i>"
    send_telegram(msg)
    print("ਅਲਰਟ ਭੇਜ ਦਿੱਤਾ ਗਿਆ!")

if __name__ == "__main__":
    main()
