#!/usr/bin/env python
"""Repository Integrity Validator and Hygiene Gate for Hokage.

Scans the codebase to detect:
1. Duplicate class definitions
2. Duplicate methods (excluding overrides)
3. Duplicate enums (keys or values)
4. Duplicate command route handlers
5. Duplicate protocol definitions
6. Dead code and orphan modules
7. Unresolved TODO and FIXME markers
8. Stale documentation and archived-file references
9. Hardcoded data paths outside of PathResolver
10. Hardcoded secrets outside of SecretManager
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote

# Ensure UTF-8 console output on Windows
sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR = Path(__file__).resolve().parent.parent
BRAIN_DIR = ROOT_DIR / "hokage_brain"

# Excluded folders from scan
EXCLUDE_DIRS = {".git", ".pytest_cache", "__pycache__", ".venv", ".agents", ".gemini", "scratch", "docs/archive", "build", "dist"}


# Standard overridden methods that are allowed to repeat across adapters/interfaces
LIFECYCLE_OVERRIDES = {
    "__init__", "execute", "connect", "disconnect", "get_status",
    "get_account_balance", "get_positions", "get_holdings",
    "place_order", "cancel_order", "modify_order", "get_order_status",
    "resolve_instrument", "get_price", "get_quote", "get_historical_candles",
    "health_check", "add_to_watchlist", "remove_from_watchlist", "get_watchlist"
}


def scan_python_files() -> list[Path]:
    py_files = []
    for dirpath, _, filenames in os.walk(ROOT_DIR):
        if any(part in Path(dirpath).parts for part in EXCLUDE_DIRS) or any(".egg-info" in part for part in Path(dirpath).parts):
            continue
        for filename in filenames:
            if filename.endswith(".py"):
                py_files.append(Path(dirpath) / filename)
    return py_files


def scan_doc_files() -> list[Path]:
    doc_files = []
    for dirpath, _, filenames in os.walk(ROOT_DIR):
        if any(part in Path(dirpath).parts for part in EXCLUDE_DIRS) or any(".egg-info" in part for part in Path(dirpath).parts):
            continue
        for filename in filenames:
            if filename.endswith((".md", ".txt")):
                doc_files.append(Path(dirpath) / filename)
    return doc_files


class RepositoryAuditor:
    """Performs repository integrity scans."""

    def __init__(self) -> None:
        self.py_files = scan_python_files()
        self.doc_files = scan_doc_files()
        self.report = {
            "duplicate_classes": [],
            "duplicate_protocols": [],
            "duplicate_methods": [],
            "duplicate_enums": [],
            "duplicate_routes": [],
            "dead_modules": [],
            "todos_fixmes": [],
            "stale_docs": [],
            "hardcoded_paths": [],
            "hardcoded_secrets": []
        }
        self.has_critical_error = False

    def run_all(self) -> bool:
        """Run all audits and write reports. Returns True if clean."""
        self._audit_python_structures()
        self._audit_route_handlers()
        self._audit_todos_fixmes()
        self._audit_documentation()
        self._audit_paths_and_secrets()
        
        self.write_reports()
        return not self.has_critical_error

    def _audit_python_structures(self) -> None:
        classes: dict[str, list[dict]] = {}
        protocols: dict[str, list[dict]] = {}
        functions: dict[str, list[dict]] = {}
        enums: dict[str, dict[str, dict]] = {}
        file_contents: dict[str, str] = {}

        for filepath in self.py_files:
            rel_path = filepath.relative_to(ROOT_DIR).as_posix()
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                file_contents[rel_path] = content
                tree = ast.parse(content, filename=str(filepath))
            except Exception as e:
                self.report["dead_modules"].append({
                    "file": rel_path,
                    "error": f"Failed to parse AST: {e}"
                })
                self.has_critical_error = True
                continue

            class_stack: list[str] = []

            class ASTVisitor(ast.NodeVisitor):
                def visit_ClassDef(self, node):
                    is_protocol = False
                    for base in node.bases:
                        if isinstance(base, ast.Name) and base.id == "Protocol":
                            is_protocol = True
                        elif isinstance(base, ast.Attribute) and base.attr == "Protocol":
                            is_protocol = True

                    loc = {"file": rel_path, "line": node.lineno}
                    if is_protocol:
                        protocols.setdefault(node.name, []).append(loc)
                    else:
                        classes.setdefault(node.name, []).append(loc)

                    # Check for Enum
                    is_enum = False
                    for base in node.bases:
                        if isinstance(base, ast.Name) and "Enum" in base.id:
                            is_enum = True
                        elif isinstance(base, ast.Attribute) and "Enum" in base.attr:
                            is_enum = True

                    if is_enum:
                        vals = {}
                        for item in node.body:
                            if isinstance(item, ast.Assign):
                                for target in item.targets:
                                    if isinstance(target, ast.Name):
                                        val = ast.unparse(item.value).strip().strip('"').strip("'")
                                        vals[target.id] = val
                            elif isinstance(item, ast.AnnAssign) and item.value:
                                if isinstance(item.target, ast.Name):
                                    val = ast.unparse(item.value).strip().strip('"').strip("'")
                                    vals[item.target.id] = val
                        enums.setdefault(node.name, {})[rel_path] = vals

                    class_stack.append(node.name)
                    self.generic_visit(node)
                    class_stack.pop()

                def visit_FunctionDef(self, node):
                    full_name = f"{'.'.join(class_stack)}.{node.name}" if class_stack else node.name
                    functions.setdefault(full_name, []).append({"file": rel_path, "line": node.lineno})
                    self.generic_visit(node)

            ASTVisitor().visit(tree)

        # 1. Duplicate Class Checks
        for name, locs in classes.items():
            if len(locs) > 1:
                self.report["duplicate_classes"].append({"name": name, "locations": locs})
                self.has_critical_error = True

        # 2. Duplicate Protocol Checks
        for name, locs in protocols.items():
            if len(locs) > 1:
                self.report["duplicate_protocols"].append({"name": name, "locations": locs})
                self.has_critical_error = True

        # 3. Duplicate Method Checks
        for name, locs in functions.items():
            if len(locs) > 1:
                method_name = name.split(".")[-1]
                if method_name not in LIFECYCLE_OVERRIDES:
                    self.report["duplicate_methods"].append({"name": name, "locations": locs})

        # 4. Duplicate Enums Check
        for enum_name, file_mappings in enums.items():
            if len(file_mappings) > 1:
                self.report["duplicate_enums"].append({
                    "enum": enum_name,
                    "mismatch": "Enum class defined in multiple files",
                    "details": list(file_mappings.keys())
                })
                self.has_critical_error = True
            for file_path, mappings in file_mappings.items():
                val_list = list(mappings.values())
                dup_vals = [v for v in set(val_list) if val_list.count(v) > 1]
                if dup_vals:
                    self.report["duplicate_enums"].append({
                        "enum": enum_name,
                        "file": file_path,
                        "mismatch": "Duplicate enum values",
                        "values": dup_vals,
                        "mappings": mappings
                    })
                    self.has_critical_error = True

        # 5. Dead / Orphan Modules Check (word boundary scanning)
        all_stems = [f.stem for f in self.py_files if f.name not in ("__init__.py", "conftest.py") and "tests/" not in f.as_posix()]
        entry_points = {"pipeline", "command_router", "api", "service", "bootstrap", "resolver", "fingerprint", "main", "verify_hygiene", "paper_dry_run", "test_conversation", "wake_hokage"}
        
        for stem in all_stems:
            if stem in entry_points:
                continue
            
            is_referenced = False
            for rel_path, content in file_contents.items():
                if stem == Path(rel_path).stem:
                    continue
                # Search for whole word match
                pattern = rf"\b{stem}\b"
                if re.search(pattern, content):
                    is_referenced = True
                    break
                    
            if not is_referenced:
                matching_files = [f.relative_to(ROOT_DIR).as_posix() for f in self.py_files if f.stem == stem]
                self.report["dead_modules"].append({
                    "module": stem,
                    "locations": matching_files,
                    "reason": "Orphan module (no imports or word references found in other python files)"
                })
                self.has_critical_error = True

    def _audit_route_handlers(self) -> None:
        router_file = ROOT_DIR / "src/hokage/router/command_router.py"
        if not router_file.exists():
            return
            
        with open(router_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        routes = []
        for idx, line in enumerate(lines, 1):
            if "if lower_cmd == " in line or "if lower_cmd in " in line or "elif lower_cmd" in line:
                matches = re.findall(r"\"([^\"]+)\"|'([^']+)'", line)
                literals = [m[0] or m[1] for m in matches]
                for lit in literals:
                    if lit not in (", ", "show current price of ", "price "):
                        routes.append((idx, lit))
                        
        dup_map = {}
        for line_num, lit in routes:
            dup_map.setdefault(lit, []).append(line_num)
            
        dup_routes = {k: v for k, v in dup_map.items() if len(v) > 1}
        if dup_routes:
            for route, lines in dup_routes.items():
                self.report["duplicate_routes"].append({
                    "route": route,
                    "lines": lines
                })
                self.has_critical_error = True

    def _audit_todos_fixmes(self) -> None:
        for filepath in self.py_files:
            rel_path = filepath.relative_to(ROOT_DIR).as_posix()
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for idx, line in enumerate(lines, 1):
                clean_line = line.strip()
                if clean_line.startswith("#") or '"""' in clean_line or "'''" in clean_line:
                    if "TODO" in clean_line:
                        self.report["todos_fixmes"].append({
                            "type": "TODO",
                            "file": rel_path,
                            "line": idx,
                            "text": clean_line
                        })
                    if "FIXME" in clean_line:
                        self.report["todos_fixmes"].append({
                            "type": "FIXME",
                            "file": rel_path,
                            "line": idx,
                            "text": clean_line
                        })

    def _audit_documentation(self) -> None:
        deleted_files = {"Mission.md", "Tasks.md", "PROJECT_STATUS.md", "simple_backtest_engine.py"}
        
        for docpath in self.doc_files:
            rel_path = docpath.relative_to(ROOT_DIR).as_posix()
            with open(docpath, "r", encoding="utf-8") as f:
                content = f.read()
                
            # Scan for markdown links e.g. [text](link)
            links = re.findall(r"\[[^\]]*\]\(([^)]+)\)", content)
            for link in links:
                clean_link = unquote(link.split("#")[0].split("?")[0])
                if clean_link.startswith("file:///"):
                    link_path = Path(clean_link.replace("file:///", ""))
                    if not link_path.exists():
                        self.report["stale_docs"].append({
                            "file": rel_path,
                            "reference": link,
                            "reason": f"File does not exist: {link_path}"
                        })
                        self.has_critical_error = True
                elif clean_link.startswith(("http://", "https://", "mailto:")):
                    continue
                else:
                    link_path = (docpath.parent / clean_link).resolve()
                    if not link_path.exists():
                        self.report["stale_docs"].append({
                            "file": rel_path,
                            "reference": link,
                            "reason": f"File does not exist: {link_path}"
                        })
                        self.has_critical_error = True
            
            # Check direct text references to deleted files in root directory
            for df in deleted_files:
                if df in content:
                    matches = re.finditer(rf"\b{re.escape(df)}\b", content)
                    for m in matches:
                        start = max(0, m.start() - 25)
                        end = min(len(content), m.end() + 25)
                        snippet = content[start:end].replace("\n", " ").strip()
                        if "docs/archive" not in snippet and "archive/" not in snippet:
                            self.report["stale_docs"].append({
                                "file": rel_path,
                                "reference": df,
                                "reason": f"Stale reference to deleted file. Found context: '... {snippet} ...'"
                            })
                            self.has_critical_error = True

    def _audit_paths_and_secrets(self) -> None:
        for filepath in self.py_files:
            rel_path = filepath.relative_to(ROOT_DIR).as_posix()
            if "tests/" in rel_path or "verify_hygiene.py" in rel_path:
                continue
                
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                tree = ast.parse(content, filename=str(filepath))
            except Exception:
                continue
                
            # Collect docstrings by reference to their Constant node object
            docstring_nodes = set()
            
            class DocstringCollector(ast.NodeVisitor):
                def visit_Module(self, node):
                    self._collect(node)
                    self.generic_visit(node)
                    
                def visit_ClassDef(self, node):
                    self._collect(node)
                    self.generic_visit(node)
                    
                def visit_FunctionDef(self, node):
                    self._collect(node)
                    self.generic_visit(node)
                    
                def _collect(self, node):
                    if node.body and isinstance(node.body[0], ast.Expr):
                        val_node = node.body[0].value
                        if isinstance(val_node, ast.Constant) and isinstance(val_node.value, str):
                            docstring_nodes.add(val_node)
            
            DocstringCollector().visit(tree)
            
            # Walk and check for secrets and paths
            class PathSecretVisitor(ast.NodeVisitor):
                def __init__(self, auditor: RepositoryAuditor, file_path: str, docs_set: set):
                    self.auditor = auditor
                    self.file_path = file_path
                    self.docstrings = docs_set
                    
                def visit_Assign(self, node):
                    # Check direct assignment right-hand side
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        self._check_secret(node.value, node.targets)
                    self.generic_visit(node)
                    
                def visit_AnnAssign(self, node):
                    # Check annotated assignment right-hand side
                    if node.value and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        self._check_secret(node.value, [node.target])
                    self.generic_visit(node)

                def visit_Constant(self, node):
                    if not isinstance(node.value, str):
                        return
                    if node in self.docstrings:
                        return
                    
                    val = node.value
                    
                    # 1. Hardcoded Paths Audit
                    if "data/" in val and "pipeline.py" not in self.file_path:
                        paths = ["data/paper_trades", "data/portfolio", "data/predictions", "data/tax", "data/research"]
                        if any(p in val for p in paths):
                            self.auditor.report["hardcoded_paths"].append({
                                "file": self.file_path,
                                "line": node.lineno,
                                "match": val
                            })
                            self.auditor.has_critical_error = True

                def _check_secret(self, constant_node, targets):
                    val = constant_node.value
                    sensitive_vars = {"api_key", "api_secret", "access_token", "secret", "password", "token", "credentials"}
                    for target in targets:
                        if isinstance(target, ast.Name) and target.id.lower() in sensitive_vars:
                            if val not in ("YOUR_API_KEY", "YOUR_API_SECRET", "YOUR_ACCESS_TOKEN", "api_key", "access_token"):
                                self.auditor.report["hardcoded_secrets"].append({
                                    "file": self.file_path,
                                    "line": constant_node.lineno,
                                    "match": val[:10] + "...",
                                    "reason": f"Potential hardcoded credentials assigned to '{target.id}'"
                                })
                                self.auditor.has_critical_error = True

            PathSecretVisitor(self, rel_path, docstring_nodes).visit(tree)

    def write_reports(self) -> None:
        """Write reports to stdout and brain/hygiene_report.json."""
        BRAIN_DIR.mkdir(parents=True, exist_ok=True)
        report_path = BRAIN_DIR / "hygiene_report.json"
        
        with report_path.open("w", encoding="utf-8") as fh:
            json.dump(self.report, fh, indent=2)
            
        print("=" * 60)
        print("          HOKAGE REPOSITORY HYGIENE REPORT          ")
        print("=" * 60)
        
        print(f"\n[1] Duplicate Classes: {len(self.report['duplicate_classes'])}")
        for item in self.report['duplicate_classes']:
            print(f"  - Class '{item['name']}' defined in: {', '.join(f'{loc['file']}:{loc['line']}' for loc in item['locations'])}")
            
        print(f"[2] Duplicate Protocols: {len(self.report['duplicate_protocols'])}")
        for item in self.report['duplicate_protocols']:
            print(f"  - Protocol '{item['name']}' defined in: {', '.join(f'{loc['file']}:{loc['line']}' for loc in item['locations'])}")
            
        print(f"[3] Duplicate Methods: {len(self.report['duplicate_methods'])}")
        for item in self.report['duplicate_methods']:
            print(f"  - Method '{item['name']}' defined in: {', '.join(f'{loc['file']}:{loc['line']}' for loc in item['locations'])}")
            
        print(f"[4] Duplicate Enums: {len(self.report['duplicate_enums'])}")
        for item in self.report['duplicate_enums']:
            mismatch = item.get("mismatch")
            if "values" in item:
                print(f"  - Enum '{item['enum']}' in {item['file']} has duplicate values: {item['values']}")
            else:
                print(f"  - Enum '{item['enum']}' defined across files: {', '.join(item['details'])}")
                
        print(f"[5] Duplicate Command Routes: {len(self.report['duplicate_routes'])}")
        for item in self.report['duplicate_routes']:
            print(f"  - Route matching '{item['route']}' duplicated at lines: {item['lines']}")
            
        print(f"[6] Dead Code / Orphan Modules: {len(self.report['dead_modules'])}")
        for item in self.report['dead_modules']:
            if "module" in item:
                print(f"  - Orphan module: '{item['module']}' in {', '.join(item['locations'])}")
            else:
                print(f"  - Dead module error: {item['file']} ({item['error']})")
                
        print(f"[7] Stale Doc References: {len(self.report['stale_docs'])}")
        for item in self.report['stale_docs']:
            print(f"  - File {item['file']}: Stale reference '{item['reference']}' ({item['reason']})")
            
        print(f"[8] Hardcoded Paths: {len(self.report['hardcoded_paths'])}")
        for item in self.report['hardcoded_paths']:
            print(f"  - File {item['file']} (line {item['line']}): Hardcoded path '{item['match']}'")
            
        print(f"[9] Hardcoded Secrets: {len(self.report['hardcoded_secrets'])}")
        for item in self.report['hardcoded_secrets']:
            print(f"  - File {item['file']} (line {item['line']}): Hardcoded secret '{item['match']}'")
            
        print(f"[10] TODO & FIXME Markers: {len(self.report['todos_fixmes'])}")
        for item in self.report['todos_fixmes'][:5]:
            print(f"  - [{item['type']}] {item['file']}:{item['line']}: {item['text']}")
        if len(self.report['todos_fixmes']) > 5:
            print(f"  ... and {len(self.report['todos_fixmes']) - 5} more markers.")
            
        print("\n" + "=" * 60)
        if self.has_critical_error:
            print("Verdict: FAIL (Critical hygiene errors detected. Halt promotion.)")
            print("=" * 60)
        else:
            print("Verdict: PASS (Repository hygiene is clean. Ready to promote.)")
            print("=" * 60)
            
        print(f"Machine-readable JSON report written to: {report_path}")


if __name__ == "__main__":
    success = RepositoryAuditor().run_all()
    sys.exit(0 if success else 1)
