from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import httpx


def signed_post(url: str, payload: dict, session: boto3.Session) -> httpx.Response:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    request = AWSRequest(
        method="POST",
        url=url,
        data=body,
        headers={"content-type": "application/json", "host": httpx.URL(url).host},
    )
    credentials = session.get_credentials()
    if credentials is None:
        raise RuntimeError("aws_credentials_unavailable")
    SigV4Auth(credentials.get_frozen_credentials(), "execute-api", session.region_name).add_auth(request)
    return httpx.post(url, content=body, headers=dict(request.headers), timeout=29.5)


def require_result(response: httpx.Response, status: int) -> dict:
    if response.status_code != status:
        raise RuntimeError(f"unexpected_http_status:{response.status_code}:{response.text[:500]}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("invalid_hosted_response")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--event-id")
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "fixtures" / "external_product_title_change.json",
    )
    args = parser.parse_args()
    session = boto3.Session(region_name=args.region)
    canonical = json.loads(args.fixture.read_text(encoding="utf-8"))
    if args.event_id:
        canonical["event_id"] = args.event_id
        canonical["change_id"] = args.event_id
        canonical["policy_context"]["external_change_id"] = args.event_id
    key = {
        "PK": f"TENANT#{canonical['agency_id']}#SHOP#{canonical['shop_id']}",
        "SK": f"EVENT#{canonical['event_id']}",
    }
    table = session.resource("dynamodb").Table(args.table)

    first_response = signed_post(args.endpoint, canonical, session)
    first = require_result(first_response, 200)
    if first.get("intelligence_classification") != "AUTHORITY_AT_RISK" or first.get("status") != "HUMAN_AUTHORITY_REQUIRED":
        raise RuntimeError("canonical_authority_floor_failed")
    record_after_first = table.get_item(Key=key, ConsistentRead=True).get("Item")
    if not record_after_first or record_after_first.get("processing_status") != "COMPLETE":
        raise RuntimeError("canonical_evidence_missing")
    evidence = record_after_first.get("evidence", {})
    if evidence.get("semantic_status") != "valid" or evidence.get("semantic_model") != "global.anthropic.claude-sonnet-4-6":
        raise RuntimeError("hosted_bedrock_not_proven")
    if evidence.get("autonomous_processing") != "STOP":
        raise RuntimeError("canonical_stop_missing")

    duplicate_response = signed_post(args.endpoint, canonical, session)
    duplicate = require_result(duplicate_response, 200)
    record_after_duplicate = table.get_item(Key=key, ConsistentRead=True).get("Item")
    if duplicate != first or duplicate_response.headers.get("x-commercegov-cache") != "HIT":
        raise RuntimeError("duplicate_cache_failed")
    if record_after_duplicate != record_after_first:
        raise RuntimeError("duplicate_mutated_canonical_evidence")

    conflict = deepcopy(canonical)
    conflict["current_value"] = "Conflicting synthetic value"
    conflict["policy_context"]["observed_shopify_value"] = "Conflicting synthetic value"
    conflict_response = signed_post(args.endpoint, conflict, session)
    conflict_body = require_result(conflict_response, 409)
    record_after_conflict = table.get_item(Key=key, ConsistentRead=True).get("Item")
    if conflict_body != {"error": "conflicting_duplicate", "terminal_status": "FAIL_CLOSED"}:
        raise RuntimeError("conflict_fail_closed_response_missing")
    if record_after_conflict != record_after_first:
        raise RuntimeError("conflict_mutated_canonical_evidence")

    print(
        json.dumps(
            {
                "canonical": "PASS",
                "duplicate": "PASS",
                "conflict": "PASS",
                "bedrock": "PASS",
                "durable_evidence": "PASS",
                "execution_id": record_after_first["execution_id"],
                "evidence_id": record_after_first["evidence_id"],
                "response_hash": record_after_first["response_hash"],
                "runtime_build_id": record_after_first["runtime_build_id"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
