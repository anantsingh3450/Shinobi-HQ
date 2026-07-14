from __future__ import annotations

import json
import pytest
from pathlib import Path
from bots.autonomous.knowledge import KnowledgeManager

# The six real production knowledge modules live in the repo's brain. The
# suite's default brain root is a hermetic sandbox (HOKAGE_BRAIN_ROOT), so
# these READ-ONLY library tests must point at the production root explicitly.
_PRODUCTION_BRAIN = Path(__file__).resolve().parents[4] / "hokage_brain"


@pytest.fixture
def temp_brain(tmp_path):
    """Create a temporary brain directory structure with sample knowledge files."""
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    
    registry = {
        "registry_version": "1.0",
        "modules": [
            {
                "module_id": "test_module",
                "name": "Test Psychological Edges",
                "author": "Test Author",
                "version": "1.0",
                "file_path": "test_module.json",
                "enabled": True
            },
            {
                "module_id": "disabled_module",
                "name": "Disabled Edges",
                "author": "Disabled Author",
                "version": "1.0",
                "file_path": "disabled_module.json",
                "enabled": False
            }
        ]
    }
    
    with open(knowledge_dir / "knowledge_registry.json", "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)
        
    module_data = {
        "module_id": "test_module",
        "name": "Test Psychological Edges",
        "author": "Test Author",
        "version": "1.0",
        "description": "Mock knowledge module for unit testing.",
        "principles": [
            {
                "id": "PR_TEST_01",
                "name": "Probabilistic Execution",
                "description": "Execute without hesitation over a series of independent events."
            }
        ],
        "mental_models": [
            {
                "id": "MM_TEST_01",
                "name": "Biased Coin Flip",
                "framework": "Coin weighted at 55% heads.",
                "outcome_effect": "Neutralizes recency bias."
            }
        ],
        "risk_rules": [
            {
                "id": "RM_TEST_01",
                "name": "Hard Stop Placement",
                "trigger": "pre_entry",
                "logic": "stop_loss_pct <= 2.0",
                "description": "Stop loss must not exceed 2%."
            }
        ],
        "psychological_rules": [
            {
                "name": "FOMO Control",
                "rule": "Do not chase entries."
            }
        ],
        "anti_patterns": [
            {
                "id": "AP_TEST_01",
                "name": "Revenge Trading",
                "detection_logic": "Time since last loss < 60s",
                "mitigation": "Enforce a cooldown period."
            }
        ],
        "decision_frameworks": [
            {
                "id": "DF_TEST_01",
                "name": "7-Gate Engine",
                "description": "Mechanical validation filters."
            }
        ],
        "integration_targets": [
            {
                "target_file": "src/bots/autonomous/capital_preservation.py",
                "target_class": "CapitalPreservationEngine",
                "responsibility": "Manage cooldowns."
            }
        ]
    }
    
    with open(knowledge_dir / "test_module.json", "w", encoding="utf-8") as f:
        json.dump(module_data, f, indent=2)
        
    return tmp_path


def test_knowledge_manager_initialization_and_loading(temp_brain):
    manager = KnowledgeManager(brain_root=temp_brain)
    
    # Check loaded modules list
    modules = manager.list_modules()
    assert len(modules) == 1
    assert modules[0]["module_id"] == "test_module"
    assert modules[0]["name"] == "Test Psychological Edges"
    assert modules[0]["principles_count"] == 1
    assert modules[0]["risk_rules_count"] == 1


def test_knowledge_manager_search_principles(temp_brain):
    manager = KnowledgeManager(brain_root=temp_brain)
    
    # Query match
    res = manager.search_principles("Probabilistic")
    assert len(res) == 1
    assert res[0]["principle"]["id"] == "PR_TEST_01"
    
    # Case-insensitive check
    res_lower = manager.search_principles("probabilistic")
    assert len(res_lower) == 1
    
    # Query no match
    res_none = manager.search_principles("NonExistentPattern")
    assert len(res_none) == 0


def test_knowledge_manager_search_rules(temp_brain):
    manager = KnowledgeManager(brain_root=temp_brain)
    
    # Search risk rules (matches in description)
    res_risk = manager.search_rules("stop loss")
    assert len(res_risk) == 1
    assert res_risk[0]["rule_type"] == "risk"
    assert res_risk[0]["rule"]["id"] == "RM_TEST_01"
    
    # Search psychological rules
    res_psych = manager.search_rules("fomo")
    assert len(res_psych) == 1
    assert res_psych[0]["rule_type"] == "psychological"
    assert res_psych[0]["rule"]["name"] == "FOMO Control"
    
    # No match
    res_none = manager.search_rules("not a rule")
    assert len(res_none) == 0


def test_knowledge_manager_search_anti_patterns(temp_brain):
    manager = KnowledgeManager(brain_root=temp_brain)
    
    # Search matches in name
    res = manager.search_anti_patterns("Revenge")
    assert len(res) == 1
    assert res[0]["anti_pattern"]["id"] == "AP_TEST_01"
    
    # Search matches in mitigation
    res_mit = manager.search_anti_patterns("cooldown")
    assert len(res_mit) == 1
    assert res_mit[0]["anti_pattern"]["id"] == "AP_TEST_01"
    
    # No match
    res_none = manager.search_anti_patterns("perfect execution")
    assert len(res_none) == 0


def test_knowledge_manager_search_mental_models(temp_brain):
    manager = KnowledgeManager(brain_root=temp_brain)
    
    # Search matches in name
    res = manager.search_mental_models("Coin")
    assert len(res) == 1
    assert res[0]["mental_model"]["id"] == "MM_TEST_01"
    
    # Search matches in framework
    res_fw = manager.search_mental_models("heads")
    assert len(res_fw) == 1
    
    # No match
    res_none = manager.search_mental_models("pyramid scheme")
    assert len(res_none) == 0


def test_knowledge_manager_real_production_modules_load():
    """Verify that all six real production modules load successfully."""
    # Instantiating with default paths (resolves to actual hokage_brain root)
    manager = KnowledgeManager(brain_root=_PRODUCTION_BRAIN)
    modules = manager.list_modules()
    
    # Check that all six modules are registered and loaded
    assert len(modules) >= 6
    assert any(m["module_id"] == "trading_in_the_zone" for m in modules)
    assert any(m["module_id"] == "daily_trading_coach" for m in modules)
    assert any(m["module_id"] == "market_wizards" for m in modules)
    assert any(m["module_id"] == "one_up_on_wall_street" for m in modules)
    assert any(m["module_id"] == "common_stocks_and_uncommon_profits" for m in modules)
    assert any(m["module_id"] == "the_intelligent_investor" for m in modules)
    
    # Search within the Steenbarger module
    res_principles = manager.search_principles("Self-Coaching")
    assert len(res_principles) >= 1
    assert any(p["module_id"] == "daily_trading_coach" for p in res_principles)

    res_models = manager.search_mental_models("Behavioral Loop")
    assert len(res_models) >= 1
    assert any(m["module_id"] == "daily_trading_coach" for m in res_models)

    res_anti = manager.search_anti_patterns("Boredom")
    assert len(res_anti) >= 1
    assert any(ap["module_id"] == "daily_trading_coach" for ap in res_anti)


def test_knowledge_manager_market_wizards_search():
    """Verify loading and specific search capabilities of the Market Wizards module."""
    manager = KnowledgeManager(brain_root=_PRODUCTION_BRAIN)
    
    # Search doctrine
    res_doc = manager.search_doctrines("Preserve Capital")
    assert len(res_doc) >= 1
    assert any(d["module_id"] == "market_wizards" for d in res_doc)
    assert res_doc[0]["doctrine"]["name"] == "Preserve Capital First"

    # Search rules and frameworks
    res_rules = manager.search_rules("stop placement")
    assert len(res_rules) >= 1
    assert any(r["module_id"] == "market_wizards" for r in res_rules)
    assert res_rules[0]["rule_type"] == "risk_framework"

    # Search recovery frameworks
    res_recover = manager.search_rules("decelerator")
    assert len(res_recover) >= 1
    assert any(r["module_id"] == "market_wizards" for r in res_recover)
    assert res_recover[0]["rule_type"] == "recovery"


def test_knowledge_manager_one_up_on_wall_street_search():
    """Verify loading and specific search capabilities of the One Up On Wall Street module."""
    manager = KnowledgeManager(brain_root=_PRODUCTION_BRAIN)
    
    # Search investor doctrine
    res_doc = manager.search_doctrines("Invest In What You Understand")
    assert len(res_doc) >= 1
    assert any(d["module_id"] == "one_up_on_wall_street" for d in res_doc)
    assert res_doc[0]["doctrine"]["name"] == "Invest In What You Understand"

    # Search research frameworks
    res_research = manager.search_rules("Scuttlebutt")
    assert len(res_research) >= 1
    assert any(r["module_id"] == "one_up_on_wall_street" for r in res_research)
    assert res_research[0]["rule_type"] == "research"

    # Search opportunity frameworks
    res_opp = manager.search_rules("Insider")
    assert len(res_opp) >= 1
    assert any(r["module_id"] == "one_up_on_wall_street" for r in res_opp)
    assert res_opp[0]["rule_type"] == "opportunity"


def test_knowledge_manager_common_stocks_and_uncommon_profits_search():
    """Verify loading and specific search capabilities of the Philip Fisher module."""
    manager = KnowledgeManager(brain_root=_PRODUCTION_BRAIN)
    
    # Search research doctrine
    res_doc = manager.search_doctrines("Talk To The Ecosystem")
    assert len(res_doc) >= 1
    assert any(d["module_id"] == "common_stocks_and_uncommon_profits" for d in res_doc)
    assert res_doc[0]["doctrine"]["name"] == "Talk To The Ecosystem"

    # Search scuttlebutt frameworks
    res_scuttle = manager.search_rules("Multi-Channel")
    assert len(res_scuttle) >= 1
    assert any(r["module_id"] == "common_stocks_and_uncommon_profits" for r in res_scuttle)
    assert res_scuttle[0]["rule_type"] == "scuttlebutt"

    # Search competitive advantage frameworks
    res_comp = manager.search_rules("Margin Maintenance")
    assert len(res_comp) >= 1
    assert any(r["module_id"] == "common_stocks_and_uncommon_profits" for r in res_comp)
    assert res_comp[0]["rule_type"] == "competitive_advantage"


def test_knowledge_manager_the_intelligent_investor_search():
    """Verify loading and specific search capabilities of the Benjamin Graham module."""
    manager = KnowledgeManager(brain_root=_PRODUCTION_BRAIN)
    
    # Search investor doctrine
    res_doc = manager.search_doctrines("Margin of Safety First")
    assert len(res_doc) >= 1
    assert any(d["module_id"] == "the_intelligent_investor" for d in res_doc)
    assert res_doc[0]["doctrine"]["name"] == "Margin of Safety First"

    # Search valuation frameworks
    res_val = manager.search_rules("Graham PE/PB")
    assert len(res_val) >= 1
    assert any(r["module_id"] == "the_intelligent_investor" for r in res_val)
    assert res_val[0]["rule_type"] == "valuation"

    # Search intrinsic value models
    res_iv = manager.search_rules("5-Year Earnings Capacity")
    assert len(res_iv) >= 1
    assert any(r["module_id"] == "the_intelligent_investor" for r in res_iv)
    assert res_iv[0]["rule_type"] == "intrinsic_value_model"

    # Search margin of safety rules
    res_mos = manager.search_rules("One-Third Value Discount")
    assert len(res_mos) >= 1
    assert any(r["module_id"] == "the_intelligent_investor" for r in res_mos)
    assert res_mos[0]["rule_type"] == "margin_of_safety_rule"




