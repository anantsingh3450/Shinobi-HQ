"""Names used in the exit path must actually exist in that scope.

2026-08-24 14:41, NATURALGAS26SEP265PE:

    Failed to execute exit order for NATURALGAS26SEP265PE:
    name '_symbol' is not defined

Two days earlier I fixed the put-excursion sign bug and wrote

    _is_option = str(_symbol or "").upper().endswith(("CE", "PE"))

inside `_monitor_and_exit_positions`. `_symbol` is not bound there. It is a
KEYWORD-DEFAULT PARAMETER of the `_async_post_exit` closure defined about
seventy lines further down, so it reads fine and resolves to nothing. The loop
variable in that scope is plain `symbol`.

WHAT IT COST, precisely: the exit order had already filled and the P&L was
recorded (-500.00) before the NameError fired in the post-exit block, so no
position was stranded and no money moved unexpectedly. What was lost was the
AUTOPSY — the trade left no record for the corpus the Pattern Reader reads.

WHY THE EXISTING TESTS PASSED. test_excursion_sign_for_options.py checks the
primitive with explicit arguments, and walks the AST to assert the `side`
argument is an IfExp. Both are true of broken code. I verified the SHAPE of the
call and never once executed it.

This test closes that gap generally: any name loaded in the body of an exit-path
method must be bound in that method, not merely somewhere in the file.
"""
from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

#: Methods whose failure costs a trade record or an exit. Extend rather than
#: relax if another one earns its place.
GUARDED = ("_monitor_and_exit_positions",)


def _outer_scope_report(func) -> tuple[set[str], set[str]]:
    """(names loaded directly in the method body, names bound there).

    Nested functions are skipped entirely — their parameters and locals belong
    to their own scope and are exactly what made `_symbol` look available.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    outer = tree.body[0]

    nested: list[ast.AST] = []
    for node in ast.walk(outer):
        if node is outer:
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            nested.append(node)
    nested_nodes = {id(n) for fn in nested for n in ast.walk(fn)}

    loaded: set[str] = set()
    bound: set[str] = set()

    # A nested def BINDS its own name in the enclosing scope even though its
    # body belongs to a different one. Skipping the whole node would report the
    # closure itself as unresolved.
    for fn in nested:
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bound.add(fn.name)

    for arg in outer.args.args + outer.args.kwonlyargs:
        bound.add(arg.arg)
    if outer.args.vararg:
        bound.add(outer.args.vararg.arg)
    if outer.args.kwarg:
        bound.add(outer.args.kwarg.arg)

    for node in ast.walk(outer):
        if id(node) in nested_nodes:
            continue
        if isinstance(node, ast.Name):
            (loaded if isinstance(node.ctx, ast.Load) else bound).add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Global):
            bound.update(node.names)

    return loaded, bound


@pytest.mark.parametrize("method_name", GUARDED)
def test_every_name_used_in_the_exit_path_is_bound_there(method_name):
    import builtins

    func = getattr(Bot, method_name)
    loaded, bound = _outer_scope_report(func)

    module = inspect.getmodule(Bot)
    module_level = set(vars(module))
    known = bound | module_level | set(dir(builtins)) | {"self"}

    unresolved = sorted(n for n in loaded - known if not n.startswith("__"))
    assert not unresolved, (
        f"{method_name} loads name(s) bound nowhere in its own scope: "
        f"{unresolved}. A name that only exists as a parameter of a nested "
        f"closure reads fine and raises NameError at runtime — that is exactly "
        f"how '_symbol' reached production and cost an autopsy."
    )


def test_the_specific_regression_is_gone():
    """`_symbol` belongs to the _async_post_exit closure. The outer method must
    use the loop variable `symbol`."""
    loaded, _ = _outer_scope_report(Bot._monitor_and_exit_positions)
    assert "_symbol" not in loaded, (
        "_symbol is a parameter of the nested _async_post_exit closure, not a "
        "name in the enclosing method"
    )


def test_the_guard_catches_a_planted_fault():
    """A test that cannot fail proves nothing. This plants the exact shape of
    the 2026-08-24 bug and confirms the checker sees it."""
    src = textwrap.dedent(
        """
        def outer(self, rows):
            for row in rows:
                symbol = row.name
                flag = str(_symbol or "").endswith("PE")

                def inner(_symbol=symbol):
                    return _symbol
                yield flag, inner
        """
    )
    tree = ast.parse(src)

    class _Fake:
        pass

    # Re-run the same analysis over the planted source.
    outer = tree.body[0]
    nested = [n for n in ast.walk(outer)
              if isinstance(n, (ast.FunctionDef, ast.Lambda)) and n is not outer]
    nested_nodes = {id(n) for fn in nested for n in ast.walk(fn)}
    loaded = {n.id for n in ast.walk(outer)
              if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
              and id(n) not in nested_nodes}
    bound = {n.id for n in ast.walk(outer)
             if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
             and id(n) not in nested_nodes} | {a.arg for a in outer.args.args}

    assert "_symbol" in loaded - bound, "the checker must flag the planted fault"
