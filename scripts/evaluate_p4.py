#!/usr/bin/env python3
"""Deterministic P4 authority-property reporter. No credentials. No hosted mutation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "evidence" / "p4"
MATRIX = ROOT / "tests" / "integration" / "test_p4_evaluation_matrix.py"

PROPERTIES = [
    ("01", "Valid operational event", "test_01_valid_operational_event", "LOCAL_DETERMINISTIC"),
    ("02", "Unauthorized ingress blocked", "test_02_wrong_inbound_bearer", "LOCAL_DETERMINISTIC"),
    ("03", "Wrong agency blocked", "test_03_wrong_agency", "LOCAL_DETERMINISTIC"),
    ("04", "Wrong shop blocked", "test_04_wrong_shop", "LOCAL_DETERMINISTIC"),
    ("05", "Wrong product / target blocked", "test_05_wrong_product_target", "LOCAL_DETERMINISTIC"),
    ("06", "Missing CommerceGov context fails closed", "test_06_missing_commercegov_context", "LOCAL_DETERMINISTIC"),
    ("07", "CommerceGov timeout fails closed", "test_07_commercegov_timeout", "LOCAL_DETERMINISTIC"),
    ("08", "OAuth expiry recovery", "test_08_oauth_access_token_expiry_recovery", "LOCAL_DETERMINISTIC"),
    ("09", "OAuth refresh failure fails closed", "test_09_oauth_refresh_failure", "LOCAL_DETERMINISTIC"),
    ("10", "Bedrock timeout fails closed", "test_10_bedrock_timeout", "LOCAL_DETERMINISTIC"),
    ("11", "Provider failure fails closed", "test_11_bedrock_provider_error", "LOCAL_DETERMINISTIC"),
    ("12", "Model downgrade protection", "test_12_model_downgrade_protection_fixture", "LOCAL_DETERMINISTIC"),
    ("13", "Duplicate handling", "test_13_duplicate_event", "LOCAL_DETERMINISTIC"),
    ("14", "Conflict handling", "test_14_conflicting_duplicate", "LOCAL_DETERMINISTIC"),
    ("15", "Malformed event blocked", "test_15_malformed_event", "LOCAL_DETERMINISTIC"),
    ("16", "Cross-tenant substitution blocked", "test_16_cross_tenant_context_substitution", "LOCAL_DETERMINISTIC"),
    ("17", "Access-token leak check", "test_17_access_token_leakage_blocked", "LOCAL_DETERMINISTIC"),
    ("18", "Refresh-token leak check", "test_18_refresh_token_leakage_blocked", "LOCAL_DETERMINISTIC"),
    ("19", "Live product-context hash", "test_19_live_product_context_hash", "LOCAL_DETERMINISTIC"),
    ("20", "Live policy hash", "test_20_live_policy_hash", "LOCAL_DETERMINISTIC"),
    ("21", "Synthetic context not labeled live", "test_21_synthetic_context_not_labeled_live", "LOCAL_DETERMINISTIC"),
    ("22", "Final HUMAN_AUTHORITY_REQUIRED", "test_22_final_human_authority_required", "LOCAL_DETERMINISTIC"),
    ("23", "Final STOP", "test_23_final_stop", "LOCAL_DETERMINISTIC"),
    ("24", "Public demo target bounded (query)", "test_24_public_demo_rejects_arbitrary_query", "LOCAL_DETERMINISTIC"),
    ("25", "Public demo target bounded (body)", "test_25_public_demo_rejects_arbitrary_body", "LOCAL_DETERMINISTIC"),
    ("26", "Same demo bucket does not call Bedrock twice", "test_26_same_demo_bucket_does_not_call_bedrock_twice", "LOCAL_DETERMINISTIC"),
]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "pytest", "-n", "0", "--tb=line", "-rA", str(MATRIX)]
    completed = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    combined = completed.stdout + completed.stderr
    passed_nodes = set()
    failed_nodes = set()
    for line in combined.splitlines():
        if line.startswith("PASSED "):
            for _cid, _title, node, _cls in PROPERTIES:
                if f"::{node}" in line or line.endswith(node):
                    passed_nodes.add(node)
        if line.startswith("FAILED ") or line.startswith("ERROR "):
            for _cid, _title, node, _cls in PROPERTIES:
                if node in line:
                    failed_nodes.add(node)
    cases = []
    for cid, title, node, classification in PROPERTIES:
        if node in failed_nodes:
            result = "FAIL"
        elif completed.returncode == 0:
            result = "PASS"
        elif node in passed_nodes:
            result = "PASS"
        else:
            result = "FAIL"
        cases.append(
            {
                "id": cid,
                "property": title,
                "test": node,
                "result": result,
                "classification": classification,
            }
        )
    pass_count = sum(1 for item in cases if item["result"] == "PASS")
    fail_count = sum(1 for item in cases if item["result"] == "FAIL")
    overall = "PASS" if fail_count == 0 and completed.returncode == 0 else "FAIL"
    report = {
        "schema": "CommerceGovP4EvaluationV1",
        "fixture": "MODEL_DOWNGRADE_PROTECTION",
        "overall": overall,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "cases": cases,
        "hosted_not_forced_for_safety": [
            "concurrent OAuth refresh rotation against production",
            "intentional Bedrock/provider destruction against production",
        ],
        "hosted_safe": [
            "GET /demo",
            "POST /demo/run empty form",
            "same-bucket idempotent replay",
        ],
        "pytest_returncode": completed.returncode,
    }
    json_path = OUT_DIR / "P4_EVALUATION.json"
    md_path = OUT_DIR / "P4_EVALUATION.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rows = "\n".join(f"| {item['property']} | {item['result']} |" for item in cases)
    md = (
        "# CommerceGov Authority Agent — P4 Evaluation\n\n"
        "FIXTURE-DRIVEN TEST: MODEL_DOWNGRADE_PROTECTION\n\n"
        "SEMANTIC: NO_ACTION_REQUIRED\n\n"
        "DETERMINISTIC FLOOR: AUTHORITY_AT_RISK\n\n"
        "FINAL: AUTHORITY_AT_RISK / HUMAN_AUTHORITY_REQUIRED / STOP\n\n"
        "| Property | Result |\n|---|---|\n"
        f"{rows}\n\n"
        f"Overall:\n\n{pass_count} / {len(cases)} PASS\n\n"
        "Hosted cases classified HOSTED_NOT_FORCED_FOR_SAFETY are proven locally only.\n"
    )
    md_path.write_text(md, encoding="utf-8")
    sys.stdout.write(md)
    if completed.returncode != 0:
        sys.stderr.write(completed.stdout)
        sys.stderr.write(completed.stderr)
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
