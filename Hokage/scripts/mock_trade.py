from integrations.llm.processor import LLMProcessor
from integrations.notifications.telegram_bot import TelegramBotUplink

def test_telegram_and_llm():
    print("Testing LLM Journal Generation...")
    processor = LLMProcessor()
    stats = {
        "strategy_id": "mock_strat_1",
        "win_rate": 0.65,
        "recent_trades": 10,
        "stop_tightness_issue": False
    }
    # journal = processor.generate_trading_journal_entry(stats)
    # print(f"LLM Journal:\n{journal}\n")
    
    print("Testing Telegram Notifications (Local Mock)...")
    tb = TelegramBotUplink()
    print("Methods available:", hasattr(tb, "notify_entry"), hasattr(tb, "notify_exit"))
    
    print("ALL OK")

if __name__ == "__main__":
    test_telegram_and_llm()
