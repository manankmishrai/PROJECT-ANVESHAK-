"""Module D: YAML rule-pack loading and structural validation.

Rule packs are loaded with yaml.safe_load only -- never yaml.load with
the full loader -- so a malformed or malicious rule-pack file can never
execute arbitrary Python code. Rule *logic* is never taken from the
YAML itself; each rule only selects a rule_type string that must
already exist in services.validation_engine.RULE_HANDLERS (backed by
models.enums.RuleType). Unsupported rule types are rejected at load
time, not silently ignored or executed.
"""
import yaml
from pathlib import Path

from models.enums import RuleType
from database.db import get_connection
from services.auth_service import require_role
from utils import audit

REQUIRED_RULE_PACK_KEYS = {"name", "version", "description"}
REQUIRED_RULE_KEYS = {"rule_id", "name", "rule_type", "severity", "enabled"}
VALID_SEVERITIES = {"low", "medium", "high", "critical"}
SUPPORTED_RULE_TYPES = {rt.value for rt in RuleType}


class RulePackValidationError(ValueError):
    pass


def load_rule_pack(path) -> dict:
    """Loads and structurally validates a YAML rule pack. Raises
    RulePackValidationError listing every problem found, rather than
    failing on the first one, so a rule-pack author can fix everything
    in one pass."""
    path = Path(path)
    if not path.exists():
        raise RulePackValidationError(f"Rule pack file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)  # safe_load: never executes arbitrary YAML tags/code

    if not isinstance(raw, dict):
        raise RulePackValidationError("Rule pack file must contain a YAML mapping at the top level.")

    errors = []

    meta = raw.get("rule_pack")
    if not isinstance(meta, dict):
        errors.append("Missing or invalid top-level 'rule_pack' section.")
        meta = {}
    else:
        missing_meta = REQUIRED_RULE_PACK_KEYS - meta.keys()
        if missing_meta:
            errors.append(f"'rule_pack' section is missing keys: {sorted(missing_meta)}")

    rules = raw.get("rules")
    if not isinstance(rules, list) or not rules:
        errors.append("Top-level 'rules' must be a non-empty list.")
        rules = []

    validated_rules = []
    seen_ids = set()
    for i, rule in enumerate(rules):
        prefix = f"rules[{i}]"
        if not isinstance(rule, dict):
            errors.append(f"{prefix}: must be a mapping.")
            continue

        missing = REQUIRED_RULE_KEYS - rule.keys()
        if missing:
            errors.append(f"{prefix}: missing required keys {sorted(missing)}")
            continue

        rule_id = rule["rule_id"]
        if rule_id in seen_ids:
            errors.append(f"{prefix}: duplicate rule_id '{rule_id}'.")
        seen_ids.add(rule_id)

        if rule["rule_type"] not in SUPPORTED_RULE_TYPES:
            errors.append(
                f"{prefix} ({rule_id}): unsupported rule_type '{rule['rule_type']}'. "
                f"Supported types: {sorted(SUPPORTED_RULE_TYPES)}"
            )
            continue

        if rule["severity"] not in VALID_SEVERITIES:
            errors.append(
                f"{prefix} ({rule_id}): invalid severity '{rule['severity']}'. "
                f"Must be one of {sorted(VALID_SEVERITIES)}"
            )

        if not isinstance(rule["enabled"], bool):
            errors.append(f"{prefix} ({rule_id}): 'enabled' must be true/false.")

        rule.setdefault("applicable_doc_types", [])
        rule.setdefault("required_fields", [])
        rule.setdefault("clause_ref", None)
        rule.setdefault("params", {})
        rule.setdefault("description", "")

        if not isinstance(rule["applicable_doc_types"], list):
            errors.append(f"{prefix} ({rule_id}): 'applicable_doc_types' must be a list.")
        if not isinstance(rule["required_fields"], list):
            errors.append(f"{prefix} ({rule_id}): 'required_fields' must be a list.")
        if not isinstance(rule["params"], dict):
            errors.append(f"{prefix} ({rule_id}): 'params' must be a mapping.")

        validated_rules.append(rule)

    if errors:
        raise RulePackValidationError("Rule pack failed validation:\n- " + "\n- ".join(errors))

    return {
        "name": meta["name"],
        "version": meta["version"],
        "description": meta.get("description", ""),
        "file_path": str(path),
        "rules": validated_rules,
    }


def register_rule_pack(actor, rule_pack: dict):
    """Idempotently registers a loaded rule pack's (name, version) in
    the rule_packs table and logs a rule_pack_changes entry the first
    time each version is registered. Safe to call on every validation
    run -- a no-op after the first registration of a given version.

    SECURITY FIX (Phase 6): this function now enforces
    require_role(actor, ("officer", "admin")) itself, as defense in
    depth. Previously this check existed only in this function's one
    current caller (services.validation_engine.run_validation) -- if any
    future code path ever called register_rule_pack directly, nothing
    would have stopped an applicant from registering/activating a rule
    pack. Preventing unauthorised rule changes is an explicit security
    requirement for this prototype.
    """
    require_role(actor, ("officer", "admin"))

    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM rule_packs WHERE name = ? AND version = ?",
            (rule_pack["name"], rule_pack["version"]),
        ).fetchone()
        if existing:
            return existing["id"]

        cur = conn.execute(
            """INSERT INTO rule_packs (name, version, file_path, is_active, created_by)
               VALUES (?,?,?,1,?)""",
            (rule_pack["name"], rule_pack["version"], rule_pack["file_path"], actor.get("id")),
        )
        rule_pack_id = cur.lastrowid

        conn.execute(
            """INSERT INTO rule_pack_changes (rule_pack_id, changed_by, change_summary)
               VALUES (?,?,?)""",
            (rule_pack_id, actor.get("id"),
             f"Initial registration of rule pack '{rule_pack['name']}' version "
             f"'{rule_pack['version']}' with {len(rule_pack['rules'])} rules."),
        )
        conn.commit()
        audit.append_entry(
            conn, actor=actor["username"], action="RULE_PACK_REGISTERED",
            record_type="rule_pack", record_id=f"{rule_pack['name']}:{rule_pack['version']}",
            payload={"rule_count": len(rule_pack["rules"])},
        )
        return rule_pack_id
    finally:
        conn.close()