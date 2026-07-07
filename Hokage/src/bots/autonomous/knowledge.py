"""Knowledge Manager for Hokage permanent institutional knowledge subsystem."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from hokage.memory.resolver import PathResolver

logger = logging.getLogger("Hokage.KnowledgeManager")


class KnowledgeManager:
    """Manages permanent institutional knowledge modules."""

    def __init__(self, brain_root: Path | None = None) -> None:
        """Initialize KnowledgeManager."""
        self._resolver = PathResolver(brain_root)
        self._knowledge_dir = self._resolver.resolve_knowledge_dir()
        self._knowledge_dir.mkdir(parents=True, exist_ok=True)
        self._registry_file = self._knowledge_dir / "knowledge_registry.json"
        self._modules: dict[str, dict[str, Any]] = {}
        self.load_modules()

    def load_modules(self) -> None:
        """Load all registered knowledge modules from the registry."""
        self._modules.clear()
        if not self._registry_file.exists():
            logger.warning(f"Knowledge registry file not found at {self._registry_file}")
            return

        try:
            with self._registry_file.open("r", encoding="utf-8") as f:
                registry = json.load(f)
            
            modules_list = registry.get("modules", [])
            for mod_info in modules_list:
                if not mod_info.get("enabled", True):
                    continue
                
                module_id = mod_info.get("module_id")
                file_name = mod_info.get("file_path")
                if not module_id or not file_name:
                    continue
                
                module_file = self._knowledge_dir / file_name
                if not module_file.exists():
                    logger.error(f"Knowledge module file {file_name} not found for module {module_id}")
                    continue
                
                with module_file.open("r", encoding="utf-8") as f_mod:
                    mod_data = json.load(f_mod)
                
                self._modules[module_id] = mod_data
                logger.info(f"Loaded knowledge module: {module_id}")
                
        except Exception as exc:
            logger.error(f"Failed to load knowledge modules: {exc}")

    def list_modules(self) -> list[dict[str, Any]]:
        """List metadata of all loaded modules."""
        info_list = []
        for mod_id, data in self._modules.items():
            # Sum counts of different rules and frameworks dynamically
            risk_rules_count = len(data.get("risk_rules", [])) + len(data.get("risk_frameworks", []))
            psych_count = len(data.get("psychological_rules", []))
            position_count = len(data.get("position_sizing_frameworks", []))
            trend_count = len(data.get("trend_frameworks", []))
            contra_count = len(data.get("contrarian_frameworks", []))
            recover_count = len(data.get("recovery_frameworks", []))
            perf_count = len(data.get("performance_frameworks", []))
            
            # Peter Lynch specific frameworks
            research_count = len(data.get("research_frameworks", []))
            comp_class_count = len(data.get("company_classification_frameworks", []))
            industry_count = len(data.get("industry_frameworks", []))
            fin_health_count = len(data.get("financial_health_frameworks", []))
            mgt_count = len(data.get("management_assessment_frameworks", []))
            val_count = len(data.get("valuation_frameworks", []))
            opp_count = len(data.get("opportunity_frameworks", []))
            compounding_count = len(data.get("compounding_frameworks", []))

            # Philip Fisher specific frameworks
            scuttlebutt_count = len(data.get("scuttlebutt_frameworks", []))
            mgt_qual_count = len(data.get("management_quality_frameworks", []))
            comp_adv_count = len(data.get("competitive_advantage_frameworks", []))
            innov_count = len(data.get("innovation_frameworks", []))
            growth_sus_count = len(data.get("growth_sustainability_frameworks", []))
            cap_alloc_count = len(data.get("capital_allocation_frameworks", []))

            # Benjamin Graham specific frameworks
            intrinsic_val_count = len(data.get("intrinsic_value_models", []))
            mos_rules_count = len(data.get("margin_of_safety_rules", []))
            investor_doctrines_count = len(data.get("investor_doctrines", []))
            
            info_list.append({
                "module_id": mod_id,
                "name": data.get("name", ""),
                "author": data.get("author", ""),
                "version": data.get("version", ""),
                "description": data.get("description", ""),
                "principles_count": len(data.get("principles", [])),
                "doctrines_count": len(data.get("doctrines", [])) + investor_doctrines_count,
                "mental_models_count": len(data.get("mental_models", [])),
                "risk_rules_count": risk_rules_count,
                "psychological_rules_count": psych_count,
                "position_sizing_frameworks_count": position_count,
                "trend_frameworks_count": trend_count,
                "contrarian_frameworks_count": contra_count,
                "recovery_frameworks_count": recover_count,
                "performance_frameworks_count": perf_count,
                "research_frameworks_count": research_count,
                "company_classification_frameworks_count": comp_class_count,
                "industry_frameworks_count": industry_count,
                "financial_health_frameworks_count": fin_health_count,
                "management_assessment_frameworks_count": mgt_count,
                "valuation_frameworks_count": val_count,
                "opportunity_frameworks_count": opp_count,
                "compounding_frameworks_count": compounding_count,
                "scuttlebutt_frameworks_count": scuttlebutt_count,
                "management_quality_frameworks_count": mgt_qual_count,
                "competitive_advantage_frameworks_count": comp_adv_count,
                "innovation_frameworks_count": innov_count,
                "growth_sustainability_frameworks_count": growth_sus_count,
                "capital_allocation_frameworks_count": cap_alloc_count,
                "intrinsic_value_models_count": intrinsic_val_count,
                "margin_of_safety_rules_count": mos_rules_count,
                "investor_doctrines_count": investor_doctrines_count,
                "anti_patterns_count": len(data.get("anti_patterns", [])),
                "decision_frameworks_count": len(data.get("decision_frameworks", [])),
                "integration_targets_count": len(data.get("integration_targets", []))
            })
        return info_list

    def search_principles(self, query: str) -> list[dict[str, Any]]:
        """Search principles across all loaded modules by query substring (case-insensitive)."""
        results = []
        query_lower = query.lower()
        for mod_id, data in self._modules.items():
            for p in data.get("principles", []):
                name = p.get("name", "").lower()
                desc = p.get("description", "").lower()
                if query_lower in name or query_lower in desc:
                    results.append({
                        "module_id": mod_id,
                        "principle": p
                    })
        return results

    def search_doctrines(self, query: str) -> list[dict[str, Any]]:
        """Search doctrines across all loaded modules by query substring."""
        results = []
        query_lower = query.lower()
        for mod_id, data in self._modules.items():
            doctrines = data.get("doctrines", []) + data.get("investor_doctrines", [])
            for d in doctrines:
                name = d.get("name", "").lower()
                desc = d.get("description", "").lower()
                if query_lower in name or query_lower in desc:
                    results.append({
                        "module_id": mod_id,
                        "doctrine": d
                    })
        return results

    def search_rules(self, query: str) -> list[dict[str, Any]]:
        """Search rules and frameworks across all loaded modules by query substring."""
        results = []
        query_lower = query.lower()
        
        # Define fields to scan dynamically as rules or frameworks
        rule_categories = [
            ("risk", "risk_rules"),
            ("risk_framework", "risk_frameworks"),
            ("psychological", "psychological_rules"),
            ("position_sizing", "position_sizing_frameworks"),
            ("trend", "trend_frameworks"),
            ("contrarian", "contrarian_frameworks"),
            ("recovery", "recovery_frameworks"),
            ("performance", "performance_frameworks"),
            ("research", "research_frameworks"),
            ("company_classification", "company_classification_frameworks"),
            ("industry", "industry_frameworks"),
            ("financial_health", "financial_health_frameworks"),
            ("management_assessment", "management_assessment_frameworks"),
            ("valuation", "valuation_frameworks"),
            ("opportunity", "opportunity_frameworks"),
            ("compounding", "compounding_frameworks"),
            ("scuttlebutt", "scuttlebutt_frameworks"),
            ("management_quality", "management_quality_frameworks"),
            ("competitive_advantage", "competitive_advantage_frameworks"),
            ("innovation", "innovation_frameworks"),
            ("growth_sustainability", "growth_sustainability_frameworks"),
            ("capital_allocation", "capital_allocation_frameworks"),
            ("intrinsic_value_model", "intrinsic_value_models"),
            ("margin_of_safety_rule", "margin_of_safety_rules"),
            ("investor_doctrine", "investor_doctrines")
        ]
        
        for mod_id, data in self._modules.items():
            for category_label, key in rule_categories:
                for item in data.get(key, []):
                    # Item could be dict with name/description/logic/rule or simple strings
                    if isinstance(item, dict):
                        name = item.get("name", "").lower()
                        desc = item.get("description", "").lower()
                        logic = item.get("logic", "").lower()
                        rule = item.get("rule", "").lower()
                        if query_lower in name or query_lower in desc or query_lower in logic or query_lower in rule:
                            results.append({
                                "module_id": mod_id,
                                "rule_type": category_label,
                                "rule": item
                            })
                    elif isinstance(item, str) and query_lower in item.lower():
                        results.append({
                            "module_id": mod_id,
                            "rule_type": category_label,
                            "rule": {"name": item, "description": item}
                        })
        return results

    def search_anti_patterns(self, query: str) -> list[dict[str, Any]]:
        """Search anti-patterns across all loaded modules by query substring."""
        results = []
        query_lower = query.lower()
        for mod_id, data in self._modules.items():
            for ap in data.get("anti_patterns", []):
                name = ap.get("name", "").lower()
                logic = ap.get("detection_logic", "").lower()
                mit = ap.get("mitigation", "").lower()
                det = ap.get("detection", "").lower()
                if query_lower in name or query_lower in logic or query_lower in mit or query_lower in det:
                    results.append({
                        "module_id": mod_id,
                        "anti_pattern": ap
                    })
        return results

    def search_mental_models(self, query: str) -> list[dict[str, Any]]:
        """Search mental models across all loaded modules by query substring."""
        results = []
        query_lower = query.lower()
        for mod_id, data in self._modules.items():
            for mm in data.get("mental_models", []):
                name = mm.get("name", "").lower()
                fw = mm.get("framework", "").lower()
                oe = mm.get("outcome_effect", "").lower()
                if query_lower in name or query_lower in fw or query_lower in oe:
                    results.append({
                        "module_id": mod_id,
                        "mental_model": mm
                    })
        return results
