from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import numpy as np

logger = logging.getLogger("Hokage.Features")

# Cache folder path relative to project root
CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "cache"

def ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

def clean_symbol(symbol: str) -> str:
    """Clean symbol name for file naming."""
    return symbol.replace("/", "_").replace(":", "_").upper()

def get_cached_data_path(symbol: str) -> Path:
    ensure_cache_dir()
    return CACHE_DIR / f"{clean_symbol(symbol)}.csv"

def is_cache_valid(path: Path, max_age_hours: float = 1.0) -> bool:
    """Check if cache file exists and is newer than max_age_hours."""
    if not path.exists():
        return False
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return (datetime.now() - mtime) < timedelta(hours=max_age_hours)

def fetch_data_from_yfinance(symbol: str, timeframe: str = "1d", limit_days: int = 180) -> pd.DataFrame | None:
    """Fetch historical daily/intraday stock or commodity data from yfinance."""
    try:
        import yfinance as yf
        logger.info(f"Downloading {symbol} from yfinance...")
        ticker = yf.Ticker(symbol)
        period = f"{limit_days}d"
        interval = "1d" if timeframe == "1d" else ("1h" if timeframe == "1h" else "15m")
        
        # Adjust period based on interval to avoid yfinance limits
        if interval != "1d":
            period = "60d"
            
        df = ticker.history(period=period, interval=interval)
        if df.empty:
            logger.warning(f"yfinance returned empty data for {symbol}")
            return None
            
        df.reset_index(inplace=True)
        rename_map = {
            "Date": "timestamp", "Datetime": "timestamp", "Date Time": "timestamp",
            "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"
        }
        df.rename(columns={c: rename_map[c] for c in df.columns if c in rename_map}, inplace=True)
        
        # Ensure standard columns
        for col in ["timestamp", "open", "high", "low", "close", "volume"]:
            if col not in df.columns:
                df[col] = np.nan
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df
    except Exception as e:
        logger.error(f"Error fetching {symbol} from yfinance: {e}")
        return None

def fetch_data_from_ccxt(symbol: str, timeframe: str = "1d", limit: int = 200) -> pd.DataFrame | None:
    """Fetch crypto historical data using CCXT (Binance)."""
    try:
        import ccxt
        logger.info(f"Downloading {symbol} from ccxt...")
        ccxt_symbol = symbol
        if "USDT" in symbol and "/" not in symbol:
            ccxt_symbol = symbol.replace("USDT", "/USDT")
            
        exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future' if 'usdt' in ccxt_symbol.lower() else 'spot'
            }
        })
        ccxt_tf = "1d" if timeframe == "1d" else ("1h" if timeframe == "1h" else "15m")
        
        ohlcv = exchange.fetch_ohlcv(ccxt_symbol, timeframe=ccxt_tf, limit=limit)
        if not ohlcv:
            logger.warning(f"ccxt returned empty data for {ccxt_symbol}")
            return None
            
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit='ms')
        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df
    except Exception as e:
        logger.error(f"Error fetching {symbol} from ccxt: {e}")
        try:
            import ccxt
            exchange = ccxt.binance({'enableRateLimit': True})
            ccxt_tf = "1d" if timeframe == "1d" else ("1h" if timeframe == "1h" else "15m")
            ccxt_symbol = symbol
            if "USDT" in symbol and "/" not in symbol:
                ccxt_symbol = symbol.replace("USDT", "/USDT")
            ohlcv = exchange.fetch_ohlcv(ccxt_symbol, timeframe=ccxt_tf, limit=limit)
            if ohlcv:
                df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit='ms')
                df.sort_values("timestamp", inplace=True)
                df.reset_index(drop=True, inplace=True)
                return df
        except Exception as e2:
            logger.error(f"CCXT Spot fallback also failed: {e2}")
        return None

def fetch_and_cache_ohlcv(symbol: str, timeframe: str = "1d") -> pd.DataFrame | None:
    """Fetch OHLCV data using the appropriate data library (yfinance or ccxt) and cache it."""
    cache_path = get_cached_data_path(symbol)
    
    # 1. Try to read from cache first
    if is_cache_valid(cache_path, max_age_hours=1.0):
        try:
            logger.info(f"Loading {symbol} from cache: {cache_path}")
            df = pd.read_csv(cache_path)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            return df
        except Exception as e:
            logger.warning(f"Failed to read cache file {cache_path}: {e}")
            
    # 2. Determine which API to use
    symbol_upper = symbol.upper()
    is_crypto = any(c in symbol_upper for c in ["BTC", "ETH", "SOL", "XRP", "USDT"]) or "/" in symbol_upper
    
    df = None
    if is_crypto:
        df = fetch_data_from_ccxt(symbol_upper, timeframe)
    else:
        # Map internal MCX/NSE symbols to valid yfinance tickers
        YFINANCE_SYMBOL_MAP = {
            "CRUDE_OIL": "CL=F",          # WTI Crude Oil Futures
            "CRUDEOIL":  "CL=F",
            "NATURAL_GAS": "NG=F",        # Natural Gas Futures
            "NATURALGAS": "NG=F",
            "GOLD":      "GC=F",          # Gold Futures
            "SILVER":    "SI=F",          # Silver Futures
            "COPPER":    "HG=F",          # Copper Futures
            "NIFTY":     "^NSEI",         # Nifty 50 Index
            "BANKNIFTY": "^NSEBANK",      # Bank Nifty Index
            "SENSEX":    "^BSESN",        # BSE Sensex
            "NIFTY50":   "^NSEI",
        }
        yf_ticker = YFINANCE_SYMBOL_MAP.get(symbol_upper, symbol_upper)
        df = fetch_data_from_yfinance(yf_ticker, timeframe)
        
    # 3. Cache it if fetched successfully
    if df is not None and not df.empty:
        try:
            ensure_cache_dir()
            df.to_csv(cache_path, index=False)
            logger.info(f"Cached {symbol} data to {cache_path}")
        except Exception as e:
            logger.warning(f"Failed to write cache file {cache_path}: {e}")
        return df
        
    # 4. Fallback to expired cache if fetching fails
    if cache_path.exists():
        try:
            logger.warning(f"Fetching failed. Falling back to expired cache for {symbol}...")
            df = pd.read_csv(cache_path)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            return df
        except Exception:
            pass
            
    return None

def calculate_features(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate Log Returns, Historical Volatility, ATR, and Bollinger Band width features."""
    if df is None or df.empty or len(df) < 20:
        return df
        
    df = df.copy()
    
    # 1. Log Returns
    df["log_returns"] = np.log(df["close"] / df["close"].shift(1))
    
    # 2. Historical Volatility (20-period rolling standard deviation of log returns)
    df["hist_volatility"] = df["log_returns"].rolling(window=20).std()
    
    # 3. Average True Range (ATR)
    high_low = df["high"] - df["low"]
    high_close_prev = np.abs(df["high"] - df["close"].shift(1))
    low_close_prev = np.abs(df["low"] - df["close"].shift(1))
    
    true_range = np.maximum(high_low, np.maximum(high_close_prev, low_close_prev))
    df["atr"] = true_range.rolling(window=14).mean()
    
    # 4. Bollinger Bands and Bollinger Band Width
    middle_band = df["close"].rolling(window=20).mean()
    std_dev = df["close"].rolling(window=20).std()
    upper_band = middle_band + (2 * std_dev)
    lower_band = middle_band - (2 * std_dev)
    
    df["bb_width"] = (upper_band - lower_band) / middle_band
    
    # Fill rolling window NaNs cleanly
    df.bfill(inplace=True)
    df.ffill(inplace=True)
    df.fillna(0.0, inplace=True)
    
    return df
