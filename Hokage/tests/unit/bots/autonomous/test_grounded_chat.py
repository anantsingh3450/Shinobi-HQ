"""Chat must answer from Hokage's real state, or admit it cannot.

The old path was `generate_response(query, system_instruction="")` — a bare
language model with no data attached, reached whenever the 16-branch keyword
cascade missed. That is where the phantom narratives in the logs came from.

These tests never touch the network: the model factory is injected.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bots.autonomous import hokage_tools
from bots.autonomous.grounded_chat import GroundedChat, GroundedAnswer


class _FakeChat:
    def __init__(self, reply: str, boom: bool = False):
        self._reply, self._boom = reply, boom
        self.asked: list[str] = []
        self.history: list = []

    def send_message(self, text):
        self.asked.append(text)
        if self._boom:
            raise RuntimeError("gemini unreachable")
        return type("R", (), {"text": self._reply})()


class _FakeModel:
    def __init__(self, reply="Nothing is open.", boom=False):
        self.reply, self.boom = reply, boom
        self.system_instruction = ""
        self.tools: list = []
        self.chat: _FakeChat | None = None

    def start_chat(self, enable_automatic_function_calling=False):
        self.chat = _FakeChat(self.reply, self.boom)
        return self.chat


def _factory(model):
    def _make(system_instruction, tools):
        if model is not None:
            model.system_instruction = system_instruction
            model.tools = tools
        return model
    return _make


# ------------------------------------------------------------- the hard rules
def test_the_grounding_rules_reach_the_model():
    model = _FakeModel()
    GroundedChat(model_factory=_factory(model)).ask("what's open?")
    si = model.system_instruction
    assert "NEVER state a number" in si
    assert "READ-ONLY" in si
    assert "I don't have that" in si or "do not have that information" in si


def test_live_state_is_injected_before_the_model_decides_anything():
    """The most common questions must be grounded even if the model skips the
    tools entirely."""
    model = _FakeModel()
    GroundedChat(model_factory=_factory(model)).ask("how much money do we have?")
    assert "LIVE STATE" in model.system_instruction
    assert "Index Dojo" in model.system_instruction


def test_every_tool_is_handed_to_the_model():
    model = _FakeModel()
    GroundedChat(model_factory=_factory(model)).ask("anything")
    assert len(model.tools) == len(hokage_tools.READ_ONLY_TOOLS)


# ------------------------------------------------------------------ degrading
def test_no_model_configured_degrades_to_FACTS_not_an_apology():
    """A silent assistant is useless; a guessing one is dangerous. Facts."""
    answer = GroundedChat(model_factory=_factory(None)).ask("what's open?")
    assert answer.degraded is True
    assert "Index Dojo" in answer.text          # real balances present
    assert "not configured" in answer.text


def test_a_model_failure_degrades_to_facts_rather_than_raising():
    answer = GroundedChat(model_factory=_factory(_FakeModel(boom=True))).ask("hi")
    assert answer.degraded is True
    assert "Index Dojo" in answer.text
    assert "RuntimeError" in answer.text


def test_an_empty_model_reply_degrades_rather_than_returning_blank():
    answer = GroundedChat(model_factory=_factory(_FakeModel(reply="  "))).ask("hi")
    assert answer.degraded is True
    assert answer.text.strip()


def test_a_factory_that_explodes_is_contained():
    def _boom(_si, _tools):
        raise ValueError("bad key")

    answer = GroundedChat(model_factory=_boom).ask("hi")
    assert answer.degraded is True
    assert "Index Dojo" in answer.text


def test_an_empty_question_returns_state_without_calling_the_model():
    model = _FakeModel()
    answer = GroundedChat(model_factory=_factory(model)).ask("   ")
    assert model.chat is None
    assert answer.degraded is True


# --------------------------------------------------------------- happy path
def test_a_normal_answer_is_returned_verbatim_and_not_marked_degraded():
    answer = GroundedChat(
        model_factory=_factory(_FakeModel(reply="Nothing is open right now."))
    ).ask("anything open?")
    assert answer.text == "Nothing is open right now."
    assert answer.degraded is False


def test_tool_usage_is_reported_for_transparency():
    model = _FakeModel(reply="Two trades today.")
    chat = GroundedChat(model_factory=_factory(model))
    answer = chat.ask("how did we do?")

    call = type("C", (), {"name": "get_trades"})()
    part = type("P", (), {"function_call": call})()
    model.chat.history = [type("M", (), {"parts": [part]})()]
    assert chat._tools_called(model.chat) == ["get_trades"]
    assert isinstance(answer, GroundedAnswer)


def test_broken_history_does_not_break_the_answer():
    class _Bad:
        @property
        def history(self):
            raise RuntimeError("nope")

    assert GroundedChat()._tools_called(_Bad()) == []


# ------------------------------------------------------------------ read-only
def _executable_strings_and_calls(module) -> tuple[list[str], list[str]]:
    """String literals and called names in a module, EXCLUDING docstrings.

    A first version of this check scanned raw source text and failed on the
    module's own docstring, which describes the invariant in prose. Scanning
    text cannot tell a rule from its description; the AST can.
    """
    import ast

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))

    strings, calls = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                strings.append(node.value)
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute):
                calls.append(fn.attr)
            elif isinstance(fn, ast.Name):
                calls.append(fn.id)
    return strings, calls


def test_no_tool_can_write():
    """Invariant, checked against executable code rather than prose. The chat
    surface must not be able to move money — the plain-English trade path
    already skips every risk check, which is why it is pinned to paper."""
    strings, calls = _executable_strings_and_calls(hokage_tools)

    for sql in strings:
        upper = sql.upper()
        for verb in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "REPLACE INTO", "ALTER "):
            assert verb not in upper, f"a write statement leaked in: {sql[:60]}"

    for forbidden in ("commit", "write_text", "write_bytes", "place_order",
                      "execute_trade", "mkdir", "unlink"):
        assert forbidden not in calls, f"a write call leaked in: {forbidden}()"


def test_the_sqlite_handle_is_opened_read_only():
    """Structural, not a promise: mode=ro makes a stray write raise."""
    source = Path(hokage_tools.__file__).read_text(encoding="utf-8")
    assert "mode=ro" in source


def test_no_tool_raises_even_when_the_database_is_missing(monkeypatch):
    """A throwing tool would either crash the reply or tempt the model to fill
    the gap itself. Every failure must come back as data."""
    monkeypatch.setattr(hokage_tools, "DB_PATH", Path("no/such/hokage.db"))
    for tool in hokage_tools.READ_ONLY_TOOLS:
        result = tool()
        assert isinstance(result, dict)


def test_the_digest_survives_a_missing_database(monkeypatch):
    monkeypatch.setattr(hokage_tools, "DB_PATH", Path("no/such/hokage.db"))
    assert isinstance(hokage_tools.current_state_digest(), str)


def test_every_tool_has_a_docstring_the_model_can_route_on():
    """Gemini picks tools by their docstrings. One without a description is a
    tool the model will never call."""
    for tool in hokage_tools.READ_ONLY_TOOLS:
        assert (tool.__doc__ or "").strip(), f"{tool.__name__} has no docstring"
        assert "Use for" in tool.__doc__, f"{tool.__name__} lacks routing hints"
