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

# ==================== ਲੌਗਿੰਗ ====================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("LowriX")

# ==================== ਸੈਟਿੰਗਜ਼ ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
CAPITAL = 10000 
RISK_PER_TRADE = 50 

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID: 
        print("Telegram Token Missing")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    try: urllib.request.urlopen(req, context=ctx, timeout=10)
    except Exception as e: logger.error(f"Telegram Error: {e}")

# ==================== Nifty 100 ਲਿਸਟ ====================
def get_nifty100_tickers():
    url = "https://archives.nseindia.com/content/indices/ind_nifty100list.csv"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.text))
        tickers = [f"{symbol.strip()}.NS" for symbol in df["Symbol"].dropna().unique()]
        return sorted(tickers)
    except Exception as e:
        logger.warning(f"NSE ਲਿਸਟ ਫੇਲ, ਬੈਕਅੱਪ ਵਰਤ ਰਹੇ ਹਾਂ: {e}")
        return ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
                "BHARTIARTL.NS", "ITC.NS", "SBIN.NS", "LICI.NS", "LT.NS",
                "HINDUNILVR.NS", "BAJFINANCE.NS", "HCLTECH.NS", "MARUTI.NS", "SUNPHARMA.NS",
                "TATAMOTORS.NS", "KOTAKBANK.NS", "NTPC.NS", "ONGC.NS", "TITAN.NS"]

# ==================== ਇੰਡੀਕੇਟਰਜ਼ ====================
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

# ==================== ਮਾਰਕੀਟ ਰਿਜੀਮ ====================
def check_market_regime():
    logger.info("Nifty Regime ਚੈੱਕ ਕਰ ਰਹੇ ਹਾਂ...")
    nifty = yf.download("^NSEI", period="3y", interval="1d", progress=False)
    if nifty.empty or len(nifty) < 200: return True, "ਡੇਟਾ ਨਹੀਂ ਮਿਲਿਆ"
    
    if isinstance(nifty.columns, pd.MultiIndex):
        nifty.columns = nifty.columns.get_level_values(0)

    nifty["EMA_200"] = nifty["Close"].ewm(span=200, adjust=False).mean()
    latest = nifty.iloc[-1]
    close, ema200 = float(latest["Close"]), float(latest["EMA_200"])
    
    if close > ema200:
        return True, f"Nifty: {close:.1f} > 200 EMA: {ema200:.1f}"
    else:
        return False, f"⚠️ Nifty 200 EMA ਤੋਂ ਹੇਠਾਂ ਹੈ ({close:.1f} < {ema200:.1f})"

# ==================== ਸਕੈਨਰ ====================
def scan_market(tickers):
    logger.info(f"{len(tickers)} ਸਟਾਕਸ ਦਾ ਡੇਟਾ ਲੈ ਰਹੇ ਹਾਂ...")
    data = yf.download(tickers=tickers, period="3y", interval="1d", group_by="ticker", auto_adjust=False, threads=True, progress=False)
    signals = []

    for ticker in tickers:
        try:
            if ticker not in data.columns.levels[0]: continue
            df = data[ticker].dropna(how="all").copy()
            if len(df) < 250: continue

            df = compute_indicators(df)
            curr = df.iloc[-1]

            # ਸਿਗਨਲ ਦੀਆਂ ਸ਼ਰਤਾਂ
            trend_ok = (curr["Close"] > curr["EMA_50"]) and (curr["EMA_50"] > curr["EMA_200"])
            rsi_ok = 60.0 <= curr["RSI_14"] <= 78.0
            breakout_ok = curr["Close"] > curr["High_20_Prior"]
            vol_ok = curr["Volume"] > (1.5 * curr["Vol_SMA_20"])
            
            day_range = curr["High"] - curr["Low"]
            range_ok = ((curr["Close"] - curr["Low"]) / day_range) > 0.5 if day_range > 0 else False

            if trend_ok and rsi_ok and breakout_ok and vol_ok and range_ok:
                entry = float(curr["Close"])
                atr = float(curr["ATR_14"])
                swing_low = float(curr["Low_10_Prior"])
                
                # SL: ATR ਅਤੇ Support ਵਿੱਚੋਂ ਜੋ ਵੱਧ ਸੁਰੱਖਿਅਤ ਹੈ
                atr_stop = entry - (2.0 * atr)
                stop_loss = round(min(swing_low, atr_stop), 2)
                
                risk = entry - stop_loss
                if risk <= 0: continue

                # Position Sizing (₹50 ਰਿਸਕ ਲਈ)
                qty = int(RISK_PER_TRADE / risk)
                if qty == 0: continue # ਜੇਕਰ 1 ਸ਼ੇਅਰ ਵੀ ਰਿਸਕ ਤੋਂ ਵੱਧ ਹੈ ਤਾਂ ਛੱਡ ਦਿਓ

                target_2r = round(entry + (2.0 * risk), 2)
                target_3r = round(entry + (3.0 * risk), 2)

                signals.append({
                    "symbol": ticker.replace(".NS", ""), "entry": round(entry, 2),
                    "sl": stop_loss, "risk": round(risk, 2), "qty": qty,
                    "target_2r": target_2r, "target_3r": target_3r,
                    "rsi": round(float(curr["RSI_14"]), 1)
                })
        except Exception as e:
            continue
    return signals

# ==================== ਮੇਨ ====================
def main():
    is_bull, regime_msg = check_market_regime()
    if not is_bull:
        send_telegram(f"⚠️ <b>LowriX Equity:</b> ਮਾਰਕੀਟ ਡਾਊਨ ਹੈ।\n{regime_msg}\nਅੱਜ ਕੋਈ ਟ੍ਰੇਡ ਨਹੀਂ ਲਵਾਂਗੇ।")
        return

    tickers = get_nifty100_tickers()
    signals = scan_market(tickers)

    if not signals:
        send_telegram(f"📊 <b>LowriX Equity:</b> ਮਾਰਕੀਟ ਠੀਕ ਹੈ ਪਰ ਅੱਜ ਕੋਈ ਵਧੀਆ ਬ੍ਰੇਕਆਉਟ ਨਹੀਂ ਮਿਲਿਆ।")
        return

    signals = sorted(signals, key=lambda x: x['rsi'], reverse=True)[:2] # ਟਾਪ 2
    
    msg = "🚀 <b>LowriX SWING ALERTS (V1.3)</b>\n"
    msg += f"💰 Capital: ₹{CAPITAL} | Max Risk: ₹{RISK_PER_TRADE}\n\n"
    
    for s in signals:
        msg += f"📌 <b>{s['symbol']}</b>\n"
        msg += f"🟢 Entry: ₹{s['entry']}\n"
        msg += f"🛑 SL: ₹{s['sl']} (Risk: ₹{s['risk']}/share)\n"
        msg += f"🎯 T1 (2R): ₹{s['target_2r']}\n"
        msg += f"🎯 T2 (3R): ₹{s['target_3r']}\n"
        msg += f"📦 Qty: <b>{s['qty']} shares</b> (Total Risk: ₹{s['qty']*s['risk']:.2f})\n"
        msg += f"📊 RSI: {s['rsi']}\n"
        msg += f"────────────────────\n"
        
    send_telegram(msg)
    logger.info("ਅਲਰਟ ਭੇਜ ਦਿੱਤਾ ਗਿਆ!")

if __name__ == "__main__":
    main()
