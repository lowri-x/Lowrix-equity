import yfinance as yf
import pandas as pd
import numpy as np
import requests
import json
import os
import time
import urllib.request
import ssl
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# ==================== ਕ੍ਰੈਡੈਂਸ਼ੀਅਲਜ਼ ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
GIST_ID = os.environ.get("GIST_ID")
GIST_TOKEN = os.environ.get("GIST_TOKEN")

# ==================== ਸੈਕਟਰ ਅਤੇ ਉਹਨਾਂ ਦੇ ਟਾਪ ਸਟਾਕਸ ====================
SECTORS = {
    "IT": ["TCS.NS", "INFY.NS", "WIPRO.NS", "HCLTECH.NS", "TECHM.NS", "LTIM.NS", "PERSISTENT.NS"],
    "Banking": ["HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS", "AXISBANK.NS", "INDUSINDBK.NS", "BANKBARODA.NS"],
    "Auto": ["TATAMOTORS.NS", "M&M.NS", "MARUTI.NS", "BAJAJ-AUTO.NS", "EICHERMOT.NS", "HEROMOTOCO.NS", "TVSMOTOR.NS"],
    "Pharma": ["SUNPHARMA.NS", "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS", "APOLLOHOSP.NS", "LUPIN.NS", "AUROPHARMA.NS"],
    "FMCG": ["ITC.NS", "HINDUNILVR.NS", "NESTLEIND.NS", "BRITANNIA.NS", "TATACONSUM.NS", "DABUR.NS", "MARICO.NS"],
    "Metal": ["TATASTEEL.NS", "JSWSTEEL.NS", "HINDALCO.NS", "VEDL.NS", "JINDALSTEL.NS", "SAIL.NS", "NMDC.NS"],
    "Energy": ["RELIANCE.NS", "ONGC.NS", "NTPC.NS", "POWERGRID.NS", "BPCL.NS", "COALINDIA.NS", "IOC.NS"],
    "Finance": ["BAJFINANCE.NS", "BAJAJFINSV.NS", "JIOFIN.NS", "SHRIRAMFIN.NS", "CHOLAFIN.NS", "MUTHOOTFIN.NS"],
    "Infra": ["LT.NS", "ADANIPORTS.NS", "GMRINFRA.NS", "IRB.NS", "RVNL.NS", "IRCON.NS"],
    "Realty": ["DLF.NS", "GODREJPROP.NS", "OBEROIRLTY.NS", "PRESTIGE.NS", "PHOENIXLTD.NS"]
}

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

# ==================== GIST ਟ੍ਰੈਕਿੰਗ ====================
def load_trades():
    if not GIST_ID or not GIST_TOKEN: return {"active": [], "history": []}
    headers = {"Authorization": f"token {GIST_TOKEN}"}
    try:
        res = requests.get(f"https://api.github.com/gists/{GIST_ID}", headers=headers)
        if res.status_code == 200:
            files = res.json().get('files', {})
            if 'equity_trades.json' in files:
                return json.loads(files['equity_trades.json']['content'])
    except: pass
    return {"active": [], "history": []}

def save_trades(trades):
    if not GIST_ID or not GIST_TOKEN: return
    headers = {"Authorization": f"token {GIST_TOKEN}"}
    payload = {"files": {"equity_trades.json": {"content": json.dumps(trades, indent=4)}}}
    try: requests.patch(f"https://api.github.com/gists/{GIST_ID}", headers=headers, json=payload)
    except: pass

# ==================== ਨਿਊਜ਼ ਫੈਚਿੰਗ ====================
def get_news_headline(symbol):
    stock_name = symbol.replace(".NS", "")
    try:
        news_url = f"https://news.google.com/rss/search?q={stock_name}+stock+news&hl=en-IN&gl=IN&ceid=IN:en"
        req = urllib.request.Request(news_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            root = ET.fromstring(response.read())
            items = root.findall(".//item")
            if items:
                return items[0].find('title').text[:100] + "..."
    except: pass
    return "No recent news."

# ==================== ਇੰਡੀਕੇਟਰਜ਼ & ਫੰਡਾਮੈਂਟਲ ====================
def add_indicators(df):
    df = df.copy()
    close = df['Close']
    
    df['ema50'] = close.ewm(span=50, adjust=False).mean()
    df['ema200'] = close.ewm(span=200, adjust=False).mean()
    
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))
    
    df['vol_sma20'] = df['Volume'].rolling(20).mean()
    df['high_20'] = df['High'].shift(1).rolling(20).max()
    
    return df

def check_fundamentals(ticker):
    try:
        info = ticker.info
        pe = info.get('forwardPE', 0)
        roe = info.get('returnOnEquity', 0) * 100 
        debt = info.get('debtToEquity', 0)
        
        # ਫੰਡਾਮੈਂਟਲ ਫਿਲਟਰ: P/E 50 ਤੋਂ ਘੱਟ, ROE 15% ਤੋਂ ਵੱਧ, Debt 100 ਤੋਂ ਘੱਟ
        if pe > 0 and pe < 50 and roe > 15 and debt < 100:
            return True
    except: pass
    return False

# ==================== ਟ੍ਰੇਡ ਚੈੱਕਿੰਗ ====================
def check_active_trades(trades):
    if not trades["active"]: return trades
    
    remaining = []
    today_date = get_ist_time().strftime("%Y-%m-%d")
    
    for t in trades["active"]:
        ticker = yf.Ticker(t["symbol"] + ".NS")
        df = ticker.history(period="5d")
        
        if df.empty: 
            remaining.append(t)
            continue
            
        high = df['High'].iloc[-1]
        low = df['Low'].iloc[-1]
        
        status = None
        if high >= t["target"]: status = "TARGET_HIT ✅"
        elif low <= t["sl"]: status = "SL_HIT ❌"
            
        if status:
            t["status"] = status
            t["exit_date"] = today_date
            trades["history"].append(t)
            emoji = "✅" if "TARGET" in status else "❌"
            send_telegram(f"{emoji} <b>{t['symbol']} ਟ੍ਰੇਡ ਬੰਦ</b>\nਸਟੇਟਸ: {status}\nEntry: ₹{t['entry']} | Exit: ₹{t['target'] if 'TARGET' in status else t['sl']}")
        else:
            remaining.append(t)
            
    trades["active"] = remaining
    return trades

# ==================== ਮੁੱਖ ਸਕੈਨਰ ====================
def main():
    trades = load_trades()
    trades = check_active_trades(trades)
    
    all_signals = []
    print("ਸਾਰੇ ਸੈਕਟਰਾਂ ਦੇ ਸਟਾਕਸ ਸਕੈਨ ਕਰ ਰਹੇ ਹਾਂ...")
    
    for sector_name, tickers in SECTORS.items():
        print(f"-> {sector_name} ਚੈੱਕ ਕਰ ਰਹੇ ਹਾਂ...")
        for ticker_symbol in tickers:
            try:
                ticker = yf.Ticker(ticker_symbol)
                df = ticker.history(period="1y", interval="1d")
                
                if df.empty or len(df) < 50: continue
                df = add_indicators(df)
                curr = df.iloc[-1]
                
                # 1. ਟੈਕਨੀਕਲ ਫਿਲਟਰ
                tech_ok = (curr['Close'] > curr['ema50'] and curr['ema50'] > curr['ema200'] and 
                           55 <= curr['rsi'] <= 75 and curr['Close'] > curr['high_20'] and 
                           curr['Volume'] > 1.5 * curr['vol_sma20'])
                
                if tech_ok:
                    # 2. ਫੰਡਾਮੈਂਟਲ ਫਿਲਟਰ
                    if check_fundamentals(ticker):
                        news = get_news_headline(ticker_symbol)
                        all_signals.append({
                            'sector': sector_name,
                            'symbol': ticker_symbol.replace('.NS', ''),
                            'entry': round(curr['Close'], 2),
                            'sl': round(curr['Close'] * 0.95, 2),
                            'target': round(curr['Close'] * 1.15, 2),
                            'rsi': round(curr['rsi'], 1),
                            'volume_surge': round(curr['Volume'] / curr['vol_sma20'], 1),
                            'news': news
                        })
                time.sleep(1.2) # Yahoo ਬਲਾਕ ਨਾ ਕਰੇ
            except: continue

    # ਸਾਰੇ ਸਿਗਨਲਾਂ ਵਿੱਚੋਂ ਟਾਪ 10 ਚੁਣੋ (Volume Surge ਦੇ ਹਿਸਾਬ ਨਾਲ)
    all_signals.sort(key=lambda x: x['volume_surge'], reverse=True)
    top_10 = all_signals[:10]
    
    # ਟਾਪ 10 ਵਿੱਚੋਂ ਸਿਰਫ਼ ਟਾਪ 2 ਸਿਗਨਲ
    top_2 = top_10[:2]

    current_date = get_ist_time().strftime("%d-%b-%Y")

    if top_2:
        msg = f"🚀 <b>LowriX Equity Top Picks (Sector-wise)</b>\n📅 ਤਾਰੀਖ: {current_date}\n\n"
        
        for i, sig in enumerate(top_2, 1):
            msg += f"{i}. <b>{sig['symbol']}</b> ({sig['sector']})\n"
            msg += f"   💰 Entry: ₹{sig['entry']}\n"
            msg += f"   🛑 SL: ₹{sig['sl']} | 🎯 Target: ₹{sig['target']}\n"
            msg += f"   📈 RSI: {sig['rsi']} | Vol: {sig['volume_surge']}x\n"
            msg += f"   📰 <b>News:</b> {sig['news']}\n"
            msg += f"   🔗 <a href='https://www.screener.in/company/{sig['symbol']}/'>Fundamentals</a>\n\n"
            
            trades["active"].append({
                "symbol": sig['symbol'], "entry": sig['entry'], 
                "sl": sig['sl'], "target": sig['target'], 
                "date": current_date
            })
            
        send_telegram(msg)
        print("ਅਲਰਟ ਭੇਜ ਦਿੱਤਾ!")
    else:
        print("ਕੋਈ ਸਿਗਨਲ ਨਹੀਂ ਮਿਲਿਆ।")

    # ਡੇਲੀ ਰਿਪੋਰਟ (Win Rate)
    total_closed = len(trades["history"])
    if total_closed > 0:
        wins = sum(1 for t in trades["history"] if "TARGET" in t["status"])
        win_rate = (wins / total_closed) * 100
        report = f"📊 <b>LowriX Daily Report</b>\nਕੁੱਲ ਟ੍ਰੇਡ: {total_closed}\n✅ ਜਿੱਤੇ: {wins} | ❌ ਹਾਰੇ: {total_closed - wins}\n🏆 <b>Win Rate: {win_rate:.1f}%</b>\nਚੱਲ ਰਹੇ ਟ੍ਰੇਡ: {len(trades['active'])}"
        send_telegram(report)

    save_trades(trades)

if __name__ == "__main__":
    main()
