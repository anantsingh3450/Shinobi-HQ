from __future__ import annotations

import logging
from pathlib import Path
import pandas as pd
import numpy as np

logger = logging.getLogger("Hokage.MLEngine")

MODEL_DIR = Path(__file__).resolve().parents[3] / "data" / "ml_models"

def ensure_model_dir() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

class MLEngine:
    """XGBoost Probability Model Engine for identifying market edges."""
    
    def __init__(self, model_dir: Path = MODEL_DIR) -> None:
        self.model_dir = model_dir
        ensure_model_dir()
        
    def get_model_path(self, symbol: str) -> Path:
        from bots.strategy.features import clean_symbol
        return self.model_dir / f"{clean_symbol(symbol)}_xgb.json"
        
    def prepare_training_data(self, df: pd.DataFrame, target_horizon: int = 10) -> tuple[pd.DataFrame, pd.Series] | tuple[None, None]:
        """Prepare features X and target y where y = 1 if close_{t+horizon} > close_t, else 0."""
        if df is None or len(df) < 50:
            return None, None
            
        df = df.copy()
        
        shifted = df["close"].shift(-target_horizon)
        df["target"] = (shifted > df["close"]).astype(float)
        df.loc[shifted.isna(), "target"] = np.nan
        
        # Features list
        feature_cols = ["log_returns", "hist_volatility", "atr", "bb_width"]
        
        # Drop rows with NaNs (specifically at the end due to shifting target)
        df_clean = df.dropna(subset=["target"] + feature_cols)
        
        if len(df_clean) < 30:
            return None, None
            
        try:
            X = df_clean[feature_cols].astype(float)
        except ValueError:
            return None, None
            
        y = df_clean["target"]
        return X, y

    def train_model(self, symbol: str, df: pd.DataFrame) -> bool:
        """Train an XGBoost classifier (or Random Forest fallback) and save the model."""
        X, y = self.prepare_training_data(df)
        if X is None or len(X) < 30:
            logger.warning(f"Insufficient data to train model for {symbol}.")
            return False
            
        model_path = self.get_model_path(symbol)
        
        try:
            import xgboost as xgb
            # Train XGBoost model
            model = xgb.XGBClassifier(
                n_estimators=50,
                max_depth=3,
                learning_rate=0.1,
                eval_metric="logloss",
                random_state=42
            )
            model.fit(X, y)
            model.save_model(str(model_path))
            logger.info(f"Successfully trained and saved XGBoost model for {symbol} to {model_path}.")
            return True
        except Exception as e:
            logger.warning(f"Failed to train/save XGBoost model: {e}. Attempting Random Forest fallback...")
            try:
                from sklearn.ensemble import RandomForestClassifier
                import joblib
                model = RandomForestClassifier(n_estimators=30, max_depth=4, random_state=42)
                model.fit(X, y)
                rf_path = model_path.with_suffix(".joblib")
                joblib.dump(model, rf_path)
                logger.info(f"Successfully trained and saved Random Forest model for {symbol} to {rf_path}.")
                return True
            except Exception as ex:
                logger.error(f"Fallback Random Forest training failed: {ex}")
                return False

    def predict_upward_probability(self, symbol: str, df: pd.DataFrame) -> float:
        """Predict the probability of upward movement in the next 10 candles."""
        if df is None or len(df) < 20:
            logger.warning(f"Insufficient data for {symbol} prediction.")
            return 0.5
            
        # Get last row for prediction features
        last_row = df.iloc[-1]
        feature_cols = ["log_returns", "hist_volatility", "atr", "bb_width"]
        
        # Verify features are valid
        try:
            X_pred = last_row[feature_cols].values.astype(float).reshape(1, -1)
            if np.isnan(X_pred).any():
                logger.warning(f"Prediction features contain NaN for {symbol}.")
                return 0.5
        except ValueError:
            logger.warning(f"Prediction features could not be coerced to float for {symbol}.")
            return 0.5
            
        model_path = self.get_model_path(symbol)
        rf_path = model_path.with_suffix(".joblib")
        
        # Try loading XGBoost
        if model_path.exists():
            try:
                import xgboost as xgb
                model = xgb.XGBClassifier()
                model.load_model(str(model_path))
                probs = model.predict_proba(X_pred)
                prob_up = float(probs[0][1])
                return prob_up
            except Exception as e:
                logger.warning(f"Failed to load/predict with XGBoost model for {symbol}: {e}")
                
        # Try loading Random Forest fallback
        if rf_path.exists():
            try:
                import joblib
                model = joblib.load(rf_path)
                probs = model.predict_proba(X_pred)
                prob_up = float(probs[0][1])
                return prob_up
            except Exception as e:
                logger.error(f"Failed to load/predict with fallback Random Forest model for {symbol}: {e}")
                
        # If no model exists, train one now and predict
        logger.info(f"No trained model found for {symbol}. Training model on the fly...")
        trained = self.train_model(symbol, df)
        if trained:
            return self.predict_upward_probability(symbol, df)
            
        return 0.5
        
    def get_zone_recommendation(self, symbol: str, df: pd.DataFrame) -> tuple[str, float]:
        """
        Evaluate probability edge using the 5 Fundamental Truths of Trading in the Zone.
        
        Returns:
            A tuple of (recommendation_string, probability_score)
            recommendation_string can be "long", "short", or "neutral".
        """
        prob = self.predict_upward_probability(symbol, df)
        
        if prob >= 0.60:
            rec = "long"
            logger.info(
                f"Probabilistic Edge Identified: {symbol} has {prob * 100:.1f}% probability of upward movement in the next 10 candles. "
                f"Trading in the Zone: Anything can happen, but this edge is statistically in our favor. Placing order."
            )
        elif prob <= 0.40:
            rec = "short"
            logger.info(
                f"Probabilistic Edge Identified: {symbol} has {(1 - prob) * 100:.1f}% probability of downward movement in the next 10 candles. "
                f"Trading in the Zone: Accepting risk, placing short order based on probability edge."
            )
        else:
            rec = "neutral"
            logger.info(
                f"No Probabilistic Edge: {symbol} upward probability is {prob * 100:.1f}%. "
                f"Trading in the Zone: Staying neutral. We do not chase uncertainty without a statistical edge."
            )
            
        return rec, prob
