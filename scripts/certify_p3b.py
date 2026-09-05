from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import boto3

from certify_p3a import bearer_post, identity_matches, load_inbound_bearer, require_result
import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assess-endpoint", required=True)
    parser.add_argument("--operational-endpoint", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--inbound-secret-arn", required=True)
    parser.add_argument("--read-secret-arn", required=True)
    parser.add_argument("--commercegov-base-url", default="")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "fixtures" / "external_product_title_change.json",
    )
    args = parser.parse_args()
    base_url = args.commercegov_base_url.strip()
    if not base_url.startswith("https://"):
        print(json.dumps({"p3b_live": "BLOCKED_CREDENTIAL", "reason": "commercegov_base_url_absent"}, indent=2, sort_keys=True))
        return 2

    session = boto3.Session(region_name=args.region)
    inbound = load_inbound_bearer(session, args.inbound_secret_arn)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    canonical = json.loads(args.fixture.read_text(encoding="utf-8"))
    canonical["event_id"] = f"p3b-{stamp}"
    canonical["change_id"] = canonical["event_id"]
    canonical["policy_context"]["external_change_id"] = canonical["event_id"]
    key = {
        "PK": f"TENANT#{canonical['agency_id']}#SHOP#{canonical['shop_id']}",
        "SK": f"EVENT#{canonical['event_id']}",
    }
    table = session.resource("dynamodb").Table(args.table)

    first_response = bearer_post(args.operational_endpoint, canonical, inbound)
    first = require_result(first_response, 200)
    identity_matches(first, canonical)
    if first.get("intelligence_classification") != "AUTHORITY_AT_RISK" or first.get("status") != "HUMAN_AUTHORITY_REQUIRED":
        raise RuntimeError("canonical_authority_floor_failed")
    record = table.get_item(Key=key, ConsistentRead=True).get("Item")
    if not record or record.get("processing_status") != "COMPLETE":
        raise RuntimeError("canonical_evidence_missing")
    evidence = record.get("evidence", {})
    if evidence.get("context_source") != "live_commercegov":
        raise RuntimeError("live_context_source_missing")
    if not str(evidence.get("product_context_hash") or "").startswith("sha256:"):
        raise RuntimeError("product_context_hash_missing")
    if not evidence.get("policy_hash") or evidence.get("policy_hash") == "sha256:p2-synthetic-proof-policy-v1":
        raise RuntimeError("live_policy_hash_missing")
    if evidence.get("semantic_status") != "valid" or evidence.get("semantic_model") != "global.anthropic.claude-sonnet-4-6":
        raise RuntimeError("hosted_bedrock_not_proven")
    if evidence.get("autonomous_processing") != "STOP":
        raise RuntimeError("canonical_stop_missing")
    serialized = json.dumps(record, default=str)
    if "Bearer " in serialized:
        raise RuntimeError("secret_material_in_evidence")

    unsigned_assess = httpx.post(
        args.assess_endpoint,
        content=json.dumps(canonical),
        headers={"content-type": "application/json"},
        timeout=29.5,
    )
    if unsigned_assess.status_code not in {401, 403}:
        raise RuntimeError(f"assess_still_allows_unsigned:{unsigned_assess.status_code}")

    print(
        json.dumps(
            {
                "p3b_live": "PASS",
                "context_source": evidence["context_source"],
                "product_context_hash": evidence["product_context_hash"],
                "policy_hash": evidence["policy_hash"],
                "bedrock": "PASS",
                "durable_evidence": "PASS",
                "execution_id": record["execution_id"],
                "evidence_id": record["evidence_id"],
                "runtime_build_id": record["runtime_build_id"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
