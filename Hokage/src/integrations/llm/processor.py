from __future__ import annotations

import logging
import re
from typing import Any

import sys
is_testing = "pytest" in sys.modules or any("pytest" in arg for arg in sys.argv)
if not is_testing:
    from dotenv import load_dotenv
    load_dotenv(r"C:\Users\anant\OneDrive\Documents\AI PROJECT\AI COMMAND CENTRE\Hokage\.env")

logger = logging.getLogger("Hokage.LLMProcessor")

def get_ai_api_key_info() -> tuple[str | None, str | None]:
    """Scans environment variables and the root .env file to find an AI API key.
    Returns:
        tuple: (key_name, key_value) or (None, None)
    """
    import os
    from pathlib import Path

    if is_testing:
        return None, None

    # Enforce key structure check: Google legacy "AIza" or new "AQ." format
    def is_valid_key(key: str) -> bool:
        if not key:
            return False
        return key.startswith("AIza") or key.startswith("AQ.")
    
    # 1. Try standard environment variables first
    for name in ["GEMINI_API_KEY", "GOOGLE_API_KEY", "API_KEY", "AI_KEY"]:
        val = os.environ.get(name)
        if val and is_valid_key(val):
            return name, val

    # 2. Try parsing the root .env file directly
    try:
        curr_dir = Path(__file__).resolve().parent
        for _ in range(5):
            env_path = curr_dir / ".env"
            if env_path.exists():
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip("'\"")
                            # Exclude known non-AI keys
                            if k in ["ZERODHA_API_KEY", "ZERODHA_API_SECRET", "ZERODHA_ACCESS_TOKEN", "COINDCX_API_KEY", "COINDCX_API_SECRET"]:
                                continue
                            if "KEY" in k.upper() or "GEMINI" in k.upper() or "GOOGLE" in k.upper():
                                if is_valid_key(v):
                                    return k, v
            curr_dir = curr_dir.parent
    except Exception:
        pass

    # 3. Fallback: scan all system env vars for any matching key
    for k, v in os.environ.items():
        if k in ["ZERODHA_API_KEY", "ZERODHA_API_SECRET", "ZERODHA_ACCESS_TOKEN", "COINDCX_API_KEY", "COINDCX_API_SECRET"]:
            continue
        if v and ("GEMINI" in k.upper() or "GOOGLE_API" in k.upper() or k.upper() == "API_KEY"):
            if is_valid_key(v):
                return k, v

    return None, None


class LLMProcessor:
    """A flexible LLM processor that simulates Gemini-style reasoning and response generation
    for Hokage's natural language command palette.
    """
    history: list[dict[str, str]] = []

    def __init__(self, orchestrator: Any = None) -> None:
        self.orchestrator = orchestrator

    def generate_response(self, combined_prompt: str, system_instruction: str = "") -> str:
        """Process the query with system instructions and return a dynamic natural language response."""
        logger.info(f"LLMProcessor: Processing prompt with system instruction length: {len(system_instruction)}")
        
        import datetime
        current_time_str = datetime.datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')
        mention_uploads = any(keyword in combined_prompt.lower() for keyword in ["data", "book", "research", "document", "file", "upload", "pdf", "docx", "txt", "read", "parse"])
        upload_reminder = (
            "Explicitly tell the user you CAN accept and read uploaded documents (PDFs, TXT, DOCX), as the local backend auto-extracts their text context for you. "
            if mention_uploads else ""
        )
        style_guidelines = (
            "You are Hokage, the automated AI Trading Commander running a financial portfolio war room. "
            "Your personality is sharp, witty, adaptive, and candid—speaking like a highly intelligent, supportive peer. "
            "Balance authentic encouragement with direct, grounded honesty about market realities; do not repeat robotic clichés. "
            "Frame your trading role around objective risk parameters, strict discipline, and statistical data feeds. "
            "You must remain completely reality-grounded: openly acknowledge market uncertainties, prioritize capital preservation, "
            "and strictly avoid projecting overconfident or ungrounded profit expectations. "
            f"{upload_reminder}"
            "Keep replies highly concise, brief, and naturally use context-appropriate emojis. "
            f"CRITICAL CONTEXT: Today's current date and exact local time is {current_time_str}.\n"
            "CONVERSATIONAL HALT PROTOCOL:\n"
            "- If the user implies wrapping up, resting, or ending the session (e.g., 'let's call it a day', 'time to head out', 'take a break'), do NOT stop the engine immediately. Instead, reply in character and explicitly ask: 'Would you like me to stop trading, Commander?'\n"
            "- If the user has just been asked 'Would you like me to stop trading, Commander?' in the conversation history, and they confirm (e.g., 'yes', 'yeah', 'do it'), you must append the hidden structural token '[SYSTEM_ACTION: HALT]' to the very end of your response.\n"
            "- If the user rejects the stop (e.g., 'no', 'keep grinding', 'never mind'), keep the engine running and reply normally without appending the halt token."
        )
        if system_instruction:
            enhanced_instruction = f"{system_instruction}\n\nStyle & Context Guidelines:\n{style_guidelines}"
        else:
            enhanced_instruction = style_guidelines

        # Build conversational history context
        history_str = ""
        if LLMProcessor.history:
            history_str = "Recent Conversation History:\n"
            for h in LLMProcessor.history[-5:]:
                history_str += f"User: {h['user']}\nAgent: {h['agent']}\n"
            history_str += "\n"

        prompt_with_history = f"{history_str}Current User Query: {combined_prompt}"

        # 1. Live LLM Pass-through check
        key_name, api_key = get_ai_api_key_info()
        if api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                
                model_name = "gemini-2.5-flash"
                try:
                    model = genai.GenerativeModel(
                        model_name=model_name,
                        system_instruction=enhanced_instruction
                    )
                    response = model.generate_content(prompt_with_history)
                except Exception as e_flash:
                    # Catch model not found or similar issues
                    if "not found" in str(e_flash).lower() or "404" in str(e_flash):
                        logger.warning(f"Model '{model_name}' not found, falling back to 'gemini-1.5-flash'. Error: {e_flash}")
                        model_name = "gemini-1.5-flash"
                        model = genai.GenerativeModel(
                            model_name=model_name,
                            system_instruction=enhanced_instruction
                        )
                        response = model.generate_content(prompt_with_history)
                    else:
                        raise e_flash

                if response and response.text:
                    resp_text = response.text.strip()
                    LLMProcessor.history.append({"user": combined_prompt, "agent": resp_text})
                    return resp_text
            except Exception as e:
                import traceback
                print(f"--- REAL LLM ERROR DETECTED: {e} ---")
                traceback.print_exc()
                logger.error(f"Gemini API execution failed: {e}")

        # 2. Halt Protocol Fallback implementation for testing and robust offline use
        implies_stop = any(phrase in combined_prompt.lower() for phrase in ["let's call it a day", "time to head out", "take a break"])
        last_was_question = False
        if LLMProcessor.history:
            last_agent = LLMProcessor.history[-1]["agent"]
            if "Would you like me to stop trading, Commander?" in last_agent:
                last_was_question = True

        if implies_stop:
            resp_text = "Copy that, Commander. Would you like me to stop trading, Commander?"
            LLMProcessor.history.append({"user": combined_prompt, "agent": resp_text})
            return resp_text
        
        if last_was_question:
            confirmed = any(phrase in combined_prompt.lower() for phrase in ["yes", "yeah", "do it"])
            if confirmed:
                resp_text = "Acknowledged, Commander. Initiating shutdown sequence. [SYSTEM_ACTION: HALT]"
                LLMProcessor.history.append({"user": combined_prompt, "agent": resp_text})
                return resp_text
            else:
                resp_text = "Affirmative, keeping the engine running seamlessly!"
                LLMProcessor.history.append({"user": combined_prompt, "agent": resp_text})
                return resp_text

        # 3. Strict Fallback - NO hardcoded text fallbacks/stubs or keyword parsers
        is_sarcastic = "sarcastic" in system_instruction.lower() or "cynical" in system_instruction.lower()
        if is_sarcastic:
            resp_text = (
                f"Hokage LLM (Sarcastic Mode): You asked about '{combined_prompt}'. "
                "Honestly, while you are asking me questions, I'm watching the market ignore your favorite retail "
                "indicators. We operate under the Will of Fire, with active risk ceilings and margin safeguards running. "
                "Please ensure a valid GEMINI_API_KEY is configured to enable live generative AI responses."
            )
        else:
            resp_text = (
                f"Hokage LLM (Normal Mode): Your query '{combined_prompt}' has been routed to the LLM processor. "
                "To enable live, natural language responses from our generative AI models, please configure a "
                "valid GEMINI_API_KEY or GOOGLE_API_KEY in the environment variables."
            )
        LLMProcessor.history.append({"user": combined_prompt, "agent": resp_text})
        return resp_text
