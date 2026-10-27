"""Tests for Module D: YAML rule-pack structural validation and loading."""
import textwrap

import pytest

from services.rule_pack_loader import (
    load_rule_pack, register_rule_pack, RulePackValidationError, SUPPORTED_RULE_TYPES,
)

REAL_RULE_PACK_PATH = "rules/eoa_illustrative_v1.yaml"

ADMIN_ACTOR = {"username": "admin", "role": "admin"}


def test_load_real_rule_pack_file():
    rule_pack = load_rule_pack(REAL_RULE_PACK_PATH)
    assert rule_pack["name"] == "eoa_illustrative"
    assert rule_pack["version"] == "0.1.0"
    assert len(rule_pack["rules"]) == 10
    rule_ids = {r["rule_id"] for r in rule_pack["rules"]}
    assert "RULE-001" in rule_ids
    assert "RULE-010" in rule_ids


def test_all_real_rule_types_are_supported():
    rule_pack = load_rule_pack(REAL_RULE_PACK_PATH)
    for rule in rule_pack["rules"]:
        assert rule["rule_type"] in SUPPORTED_RULE_TYPES


def test_rejects_unsupported_rule_type(tmp_path):
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(textwrap.dedent("""
        rule_pack:
          name: "bad_pack"
          version: "0.0.1"
          description: "test"
        rules:
          - rule_id: "RULE-X"
            name: "Dangerous rule"
            rule_type: "execute_arbitrary_python"
            severity: "high"
            enabled: true
    """), encoding="utf-8")

    with pytest.raises(RulePackValidationError, match="unsupported rule_type"):
        load_rule_pack(bad_yaml)


def test_rejects_missing_required_keys(tmp_path):
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(textwrap.dedent("""
        rule_pack:
          name: "bad_pack"
          version: "0.0.1"
          description: "test"
        rules:
          - rule_id: "RULE-X"
            name: "Incomplete rule"
    """), encoding="utf-8")

    with pytest.raises(RulePackValidationError, match="missing required keys"):
        load_rule_pack(bad_yaml)


def test_rejects_duplicate_rule_ids(tmp_path):
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(textwrap.dedent("""
        rule_pack:
          name: "bad_pack"
          version: "0.0.1"
          description: "test"
        rules:
          - rule_id: "RULE-DUP"
            name: "First"
            rule_type: "missing_required_document"
            severity: "high"
            enabled: true
          - rule_id: "RULE-DUP"
            name: "Second"
            rule_type: "missing_required_document"
            severity: "high"
            enabled: true
    """), encoding="utf-8")

    with pytest.raises(RulePackValidationError, match="duplicate rule_id"):
        load_rule_pack(bad_yaml)


def test_rejects_invalid_severity(tmp_path):
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(textwrap.dedent("""
        rule_pack:
          name: "bad_pack"
          version: "0.0.1"
          description: "test"
        rules:
          - rule_id: "RULE-X"
            name: "Bad severity"
            rule_type: "missing_required_document"
            severity: "catastrophic"
            enabled: true
    """), encoding="utf-8")

    with pytest.raises(RulePackValidationError, match="invalid severity"):
        load_rule_pack(bad_yaml)


def test_rejects_missing_rules_file():
    with pytest.raises(RulePackValidationError, match="not found"):
        load_rule_pack("rules/does_not_exist.yaml")


def test_register_rule_pack_is_idempotent(temp_db, monkeypatch):
    import services.rule_pack_loader as loader_module
    monkeypatch.setattr(loader_module, "get_connection", temp_db.get_connection)

    rule_pack = load_rule_pack(REAL_RULE_PACK_PATH)

    first_id = register_rule_pack(ADMIN_ACTOR, rule_pack)
    second_id = register_rule_pack(ADMIN_ACTOR, rule_pack)
    assert first_id == second_id

    conn = temp_db.get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) c FROM rule_packs").fetchone()["c"]
        changes = conn.execute("SELECT COUNT(*) c FROM rule_pack_changes").fetchone()["c"]
    finally:
        conn.close()
    assert count == 1
    assert changes == 1