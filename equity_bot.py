import os
import sys
import logging
import requests
import io
import pandas as pd
import numpy as np
import yfinance as yf
import json
import urllib.request
import ssl
from datetime import datetime, timezone, timedelta

# ==================== ਲੌਗਿੰਗ ====================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("LowriX")

# ==================== ਸੈਟਿੰਗਜ਼ ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
GIST_ID = os.getenv("GIST_ID")
GIST_TOKEN = os.getenv("GIST_TOKEN")
CAPITAL = 10000 
RISK_PER_TRADE = 50 

def get_ist_time():
    return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    try: urllib.request.urlopen(req, context=ctx, timeout=10)
    except Exception as e: logger.error(f"Telegram Error: {e}")

# ==================== GIST ਟ੍ਰੈਕਿੰਗ ====================
def load_trades():
    if not GIST_ID or not GIST_TOKEN: 
        return {"active": [], "history": []}
    headers = {"Authorization": f"token {GIST_TOKEN}"}
    try:
        res = requests.get(f"https://api.github.com/gists/{GIST_ID}", headers=headers)
        if res.status_code == 200:
            # ਅਸੀਂ equity_trades.json ਵਿੱਚ ਸੇਵ ਕਰਾਂਗੇ
            files = res.json().get('files', {})
            if 'equity_trades.json' in files:
                return json.loads(files['equity_trades.json']['content'])
            return {"active": [], "history": []}
    except Exception as e:
        logger.error(f"Gist Read Error: {e}")
    return {"active": [], "history": []}

def save_trades(trades):
    if not GIST_ID or not GIST_TOKEN: return
    headers = {"Authorization": f"token {GIST_TOKEN}"}
    payload = {"files": {"equity_trades.json": {"content": json.dumps(trades, indent=4)}}}
    try: 
        requests.patch(f"https://api.github.com/gists/{GIST_ID}", headers=headers, json=payload)
    except Exception as e: 
        logger.error(f"Gist Save Error: {e}")

# ==================== ਡੇਟਾ ਫੈਚਿੰਗ & ਇੰਡੀਕੇਟਰ ====================
def get_nifty100_tickers():
    url = "https://archives.nseindia.com/content/indices/ind_nifty100list.csv"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.text))
        return sorted([f"{symbol.strip()}.NS" for symbol in df["Symbol"].dropna().unique()])
    except Exception:
        return ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS", "SBIN.NS"]

def compute_indicators(df):
    df["EMA_50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["EMA_200"] = df["Close"].ewm(span=200, adjust=False).mean()
    df["High_20_Prior"] = df["High"].shift(1).rolling(window=20).max()
    df["Low_10_Prior"] = df["Low"].shift(1).rolling(window=10).min()
    df["Vol_SMA_20"] = df["Volume"].shift(1).rolling(window=20).mean()

    prev_close = df["Close"].shift(1)
    tr1 = df["High"] - df["Low"]
    tr2 = (df["High"] - prev_close).abs()
    tr3 = (df["Low"] - prev_close).abs()
    df["TR"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["ATR_14"] = df["TR"].rolling(window=14).mean()

    delta = df["Close"].diff()
    gain = delta.clip(lower=0); loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["RSI_14"] = 100 - (100 / (1 + rs))
    return df

def check_market_regime():
    nifty = yf.download("^NSEI", period="3y", interval="1d", progress=False)
    if nifty.empty or len(nifty) < 200: return True, "Data Missing"
    if isinstance(nifty.columns, pd.MultiIndex): nifty.columns = nifty.columns.get_level_values(0)
    nifty["EMA_200"] = nifty["Close"].ewm(span=200, adjust=False).mean()
    latest = nifty.iloc[-1]
    return float(latest["Close"]) > float(latest["EMA_200"]), f"Nifty: {float(latest['Close']):.1f}"

# ==================== ਟ੍ਰੇਡ ਚੈੱਕਿੰਗ ====================
def check_active_trades(trades):
    if not trades["active"]: return trades
    
    logger.info(f"{len(trades['active'])} ਚੱਲ ਰਹੇ ਟ੍ਰੇਡਸ ਚੈੱਕ ਕਰ ਰਹੇ ਹਾਂ...")
    remaining = []
    today_date = get_ist_time().strftime("%Y-%m-%d")
    
    for t in trades["active"]:
        ticker = t["symbol"] + ".NS"
        df = yf.download(ticker, period="5d", interval="1d", progress=False)
        
        if df.empty or len(df) < 1:
            remaining.append(t)
            continue
            
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        latest = df.iloc[-1]
        high = float(latest["High"])
        low = float(latest["Low"])
        
        status = None
        # T1 ਚੈੱਕ ਕਰੋ
        if high >= t["t1"]:
            status = "TARGET_HIT ✅"
        # SL ਚੈੱਕ ਕਰੋ
        elif low <= t["sl"]:
            status = "SL_HIT ❌"
            
        if status:
            t["status"] = status
            t["exit_date"] = today_date
            trades["history"].append(t)
            
            emoji = "✅" if "TARGET" in status else "❌"
            msg = f"{emoji} <b>LowriX Equity Exit</b>\n\n📌 <b>{t['symbol']}</b>\nਸਟੇਟਸ: {status}\nEntry: ₹{t['entry']} | Exit: ₹{t['t1'] if 'TARGET' in status else t['sl']}"
            send_telegram(msg)
        else:
            remaining.append(t)
            
    trades["active"] = remaining
    return trades

# ==================== ਮੁੱਖ ਸਕੈਨਰ ====================
def scan_market(tickers, active_symbols):
    logger.info(f"ਸਕੈਨਿੰਗ {len(tickers)} ਸਟਾਕਸ...")
    data = yf.download(tickers=tickers, period="3y", interval="1d", group_by="ticker", auto_adjust=False, threads=True, progress=False)
    signals = []

    for ticker in tickers:
        try:
            sym = ticker.replace(".NS", "")
            if sym in active_symbols: continue # ਜੇ ਪਹਿਲਾਂ ਹੀ ਟ੍ਰੇਡ ਚੱਲ ਰਿਹਾ ਹੈ ਤਾਂ ਛੱਡ ਦਿਓ
            
            if ticker not in data.columns.levels[0]: continue
            df = data[ticker].dropna(how="all").copy()
            if len(df) < 250: continue

            df = compute_indicators(df)
            curr = df.iloc[-1]

            trend_ok = (curr["Close"] > curr["EMA_50"]) and (curr["EMA_50"] > curr["EMA_200"])
            rsi_ok = 60.0 <= curr["RSI_14"] <= 78.0
            breakout_ok = curr["Close"] > curr["High_20_Prior"]
            vol_surge = curr["Volume"] / curr["Vol_SMA_20"]
            vol_ok = vol_surge > 1.5
            
            day_range = curr["High"] - curr["Low"]
            range_ok = ((curr["Close"] - curr["Low"]) / day_range) > 0.5 if day_range > 0 else False

            if trend_ok and rsi_ok and breakout_ok and vol_ok and range_ok:
                entry = float(curr["Close"])
                atr = float(curr["ATR_14"])
                swing_low = float(curr["Low_10_Prior"])
                stop_loss = round(min(swing_low, entry - (2.0 * atr)), 2)
                risk = entry - stop_loss
                
                if risk <= 0: continue
                qty = int(RISK_PER_TRADE / risk)
                if qty == 0: continue

                signals.append({
                    "symbol": sym, "entry": round(entry, 2), "sl": stop_loss,
                    "qty": qty, "t1": round(entry + (2.0 * risk), 2),
                    "vol_surge": round(vol_surge, 2), "rsi": round(float(curr["RSI_14"]), 1),
                    "date": get_ist_time().strftime("%Y-%m-%d")
                })
        except Exception:
            continue
    return signals

# ==================== ਮੇਨ ====================
def main():
    trades = load_trades()
    
    # 1. ਪੁਰਾਣੇ ਟ੍ਰੇਡਸ ਚੈੱਕ ਕਰੋ
    trades = check_active_trades(trades)
    
    # 2. ਮਾਰਕੀਟ ਰਿਜੀਮ ਚੈੱਕ ਕਰੋ
    is_bull, regime_msg = check_market_regime()
    if not is_bull:
        save_trades(trades)
        send_telegram(f"⚠️ <b>LowriX Equity:</b> ਮਾਰਕੀਟ ਡਾਊਨ ਹੈ।\n{regime_msg}\nਨਵੇਂ ਟ੍ਰੇਡ ਨਹੀਂ ਲਵਾਂਗੇ।")
        return

    # 3. ਨਵੇਂ ਸਿਗਨਲ ਲੱਭੋ
    tickers = get_nifty100_tickers()
    active_symbols = [t["symbol"] for t in trades["active"]]
    signals = scan_market(tickers, active_symbols)

    # 4. ਰਿਪੋਰਟ ਅਤੇ ਅਲਰਟ
    if signals:
        # ਵਾਲੀਅਮ ਦੇ ਹਿਸਾਬ ਨਾਲ ਟਾਪ 2 ਚੁਣੋ
        signals = sorted(signals, key=lambda x: x['vol_surge'], reverse=True)[:2]
        
        msg = "🚀 <b>LowriX SWING ALERTS (Top 2)</b>\n\n"
        for s in signals:
            msg += f"📌 <b>{s['symbol']}</b>\n"
            msg += f"🟢 Entry: ₹{s['entry']}\n"
            msg += f"🛑 SL: ₹{s['sl']}\n"
            msg += f"🎯 Target: ₹{s['t1']} (2R)\n"
            msg += f"📦 Qty: <b>{s['qty']} shares</b>\n"
            msg += f"📊 Vol: {s['vol_surge']}x | RSI: {s['rsi']}\n"
            msg += f"────────────────────\n"
            
            trades["active"].append(s) # ਚਾਲੂ ਟ੍ਰੇਡਸ ਵਿੱਚ ਐਡ ਕਰੋ
            
        send_telegram(msg)
    else:
        logger.info("ਕੋਈ ਨਵਾਂ ਵਧੀਆ ਸਿਗਨਲ ਨਹੀਂ ਮਿਲਿਆ।")

    save_trades(trades)
    
    # 5. ਡੇਲੀ ਰਿਪੋਰਟ (ਹਰ ਰੋਜ਼)
    total_closed = len(trades["history"])
    if total_closed > 0:
        wins = sum(1 for t in trades["history"] if "TARGET" in t["status"])
        win_rate = (wins / total_closed) * 100
        report = f"📈 <b>LowriX Daily Report</b>\n"
        report += f"ਕੁੱਲ ਪੂਰੇ ਹੋਏ ਟ੍ਰੇਡ: {total_closed}\n"
        report += f"✅ ਜਿੱਤੇ: {wins} | ❌ ਹਾਰੇ: {total_closed - wins}\n"
        report += f"🏆 <b>Win Rate: {win_rate:.1f}%</b>\n"
        report += f"ਚੱਲ ਰਹੇ ਟ੍ਰੇਡ: {len(trades['active'])}"
        send_telegram(report)
    else:
        send_telegram(f"📈 <b>LowriX:</b> ਸਿਸਟਮ ਚੱਲ ਰਿਹਾ ਹੈ। ਅੱਜ ਕੋਈ ਨਵਾਂ ਸਿਗਨਲ ਨਹੀਂ ਮਿਲਿਆ।")

if __name__ == "__main__":
    main()
