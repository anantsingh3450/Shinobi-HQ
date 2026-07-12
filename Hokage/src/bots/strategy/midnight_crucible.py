import logging
from datetime import datetime, timezone
from integrations.data.trade_ledger import ledger

logger = logging.getLogger("Hokage.MidnightCrucible")

class MidnightCrucible:
    """
    Hooks into the 23:30 IST CronScheduler to evaluate the day's trades 
    from the SQLite ledger, grade AI logic, and update LLM synthesis weights.
    """
    def __init__(self):
        self.ledger = ledger

    def run_daily_evaluation(self):
        """Grades logic based on the Immutable Execution Ledger."""
        logger.info("Midnight Crucible activated. Auditing daily execution ledger...")
        
        # Retrieve today's trades
        trades = self.ledger.get_all_trades(limit=1000)
        today = datetime.now(timezone.utc).date()
        
        todays_trades = [
            t for t in trades 
            if datetime.fromisoformat(t['timestamp']).date() == today
        ]
        
        if not todays_trades:
            logger.info("No trades logged today. Evaluation skipped.")
            return

        total_trades = len(todays_trades)
        winning_trades = sum(1 for t in todays_trades if t['exit_price'] and t['entry_price'] and 
                             ((t['direction'] == 'BUY' and t['exit_price'] > t['entry_price']) or 
                              (t['direction'] == 'SELL' and t['exit_price'] < t['entry_price'])))
        
        win_rate = winning_trades / total_trades
        
        logger.info(f"Daily Audit Complete. Trades: {total_trades}, Win Rate: {win_rate*100:.2f}%")
        
        # Adjust Logic Weights (mock reinforcement update)
        if win_rate > 0.55:
            self._update_llm_weights(positive_reinforcement=True)
        elif win_rate < 0.45:
            self._update_llm_weights(positive_reinforcement=False)

    def _update_llm_weights(self, positive_reinforcement: bool):
        """Simulates updating the LLM processor's logic weights."""
        if positive_reinforcement:
            logger.info("Midnight Crucible: Logic yielded positive alpha. Reinforcing current macro/micro weights.")
        else:
            logger.info("Midnight Crucible: Logic yielded negative alpha. Depreciating utilized macro/micro weights.")

    def get_bayesian_kelly_parameters(self):
        """Returns Empirical Win Probability (p), Expected Gain (b), Expected Loss (L)"""
        trades = self.ledger.get_all_trades(limit=5000)
        
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        cutoff = now - datetime.timedelta(days=30)
        
        wins = 0
        losses = 0
        total_gain = 0.0
        total_loss = 0.0
        
        for t in trades:
            try:
                ts = datetime.datetime.fromisoformat(t['timestamp'])
                if ts < cutoff:
                    continue
                
                # Check if exit_price is valid
                entry = t.get('entry_price')
                exit_p = t.get('exit_price')
                
                if not entry or not exit_p:
                    continue
                    
                direction = t.get('direction', 'BUY').upper()
                if direction == 'BUY' or direction == 'LONG':
                    pnl_pct = (exit_p - entry) / entry
                else:
                    pnl_pct = (entry - exit_p) / entry
                    
                if pnl_pct > 0:
                    wins += 1
                    total_gain += pnl_pct
                else:
                    losses += 1
                    total_loss += abs(pnl_pct)
            except Exception:
                pass
                
        # Bayesian Update (Beta Distribution)
        alpha = 1.0 + wins
        beta = 1.0 + losses
        p = alpha / (alpha + beta)
        
        b = (total_gain / wins) if wins > 0 else 0.02
        L = (total_loss / losses) if losses > 0 else 0.02
        
        return {
            'total_trades': wins + losses,
            'p': p,
            'b': b,
            'L': L
        }

crucible = MidnightCrucible()
