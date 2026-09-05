from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import boto3
from botocore.awsrequest import AWSRequest
from botocore.auth import SigV4Auth
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


def bearer_post(url: str, payload: dict, token: str) -> httpx.Response:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return httpx.post(
        url,
        content=body,
        headers={"content-type": "application/json", "authorization": f"Bearer {token}"},
        timeout=29.5,
    )


def require_result(response: httpx.Response, status: int) -> dict:
    if response.status_code != status:
        raise RuntimeError(f"unexpected_http_status:{response.status_code}:{response.text[:500]}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("invalid_hosted_response")
    return payload


def load_inbound_bearer(session: boto3.Session, secret_arn: str) -> str:
    response = session.client("secretsmanager").get_secret_value(SecretId=secret_arn)
    secret_string = response.get("SecretString")
    if not isinstance(secret_string, str) or not secret_string.strip():
        raise RuntimeError("inbound_bearer_unavailable")
    text = secret_string.strip()
    if text.startswith("{"):
        parsed = json.loads(text)
        token = parsed.get("token") if isinstance(parsed, dict) else None
        if not token:
            raise RuntimeError("inbound_bearer_unavailable")
        return str(token)
    return text


def identity_matches(body: dict, payload: dict) -> None:
    for field in ("event_id", "agency_id", "shop_id", "target_type", "target_id", "mutation_class"):
        if body.get(field) != payload.get(field):
            raise RuntimeError(f"identity_echo_failed:{field}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assess-endpoint", required=True)
    parser.add_argument("--operational-endpoint", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--secret-arn", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "fixtures" / "external_product_title_change.json",
    )
    args = parser.parse_args()
    session = boto3.Session(region_name=args.region)
    token = load_inbound_bearer(session, args.secret_arn)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    canonical = json.loads(args.fixture.read_text(encoding="utf-8"))
    canonical["event_id"] = f"p3a-{stamp}"
    canonical["change_id"] = canonical["event_id"]
    canonical["policy_context"]["external_change_id"] = canonical["event_id"]
    key = {
        "PK": f"TENANT#{canonical['agency_id']}#SHOP#{canonical['shop_id']}",
        "SK": f"EVENT#{canonical['event_id']}",
    }
    table = session.resource("dynamodb").Table(args.table)

    unsigned_assess = httpx.post(
        args.assess_endpoint,
        content=json.dumps(canonical),
        headers={"content-type": "application/json"},
        timeout=29.5,
    )
    if unsigned_assess.status_code not in {401, 403}:
        raise RuntimeError(f"assess_still_allows_unsigned:{unsigned_assess.status_code}")

    missing = httpx.post(
        args.operational_endpoint,
        content=json.dumps(canonical),
        headers={"content-type": "application/json"},
        timeout=29.5,
    )
    missing_body = require_result(missing, 401)
    if missing_body.get("error") != "bearer_authorization_required":
        raise RuntimeError("missing_bearer_not_rejected")
    if table.get_item(Key=key, ConsistentRead=True).get("Item"):
        raise RuntimeError("unauthenticated_wrote_evidence")

    wrong = bearer_post(args.operational_endpoint, canonical, "intentionally-wrong-token")
    wrong_body = require_result(wrong, 401)
    if wrong_body.get("error") != "bearer_authorization_invalid":
        raise RuntimeError("wrong_bearer_not_rejected")
    if table.get_item(Key=key, ConsistentRead=True).get("Item"):
        raise RuntimeError("wrong_secret_wrote_evidence")

    first_response = bearer_post(args.operational_endpoint, canonical, token)
    first = require_result(first_response, 200)
    identity_matches(first, canonical)
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

    duplicate_response = bearer_post(args.operational_endpoint, canonical, token)
    duplicate = require_result(duplicate_response, 200)
    record_after_duplicate = table.get_item(Key=key, ConsistentRead=True).get("Item")
    if duplicate != first or duplicate_response.headers.get("x-commercegov-cache") != "HIT":
        raise RuntimeError("duplicate_cache_failed")
    if record_after_duplicate != record_after_first:
        raise RuntimeError("duplicate_mutated_canonical_evidence")

    conflict = deepcopy(canonical)
    conflict["current_value"] = "Conflicting synthetic value"
    conflict["policy_context"]["observed_shopify_value"] = "Conflicting synthetic value"
    conflict_response = bearer_post(args.operational_endpoint, conflict, token)
    conflict_body = require_result(conflict_response, 409)
    record_after_conflict = table.get_item(Key=key, ConsistentRead=True).get("Item")
    if conflict_body != {"error": "conflicting_duplicate", "terminal_status": "FAIL_CLOSED"}:
        raise RuntimeError("conflict_fail_closed_response_missing")
    if record_after_conflict != record_after_first:
        raise RuntimeError("conflict_mutated_canonical_evidence")

    print(
        json.dumps(
            {
                "assess_unsigned": "PASS",
                "operational_unauthenticated": "PASS",
                "operational_wrong_secret": "PASS",
                "operational_canonical": "PASS",
                "operational_duplicate": "PASS",
                "operational_conflict": "PASS",
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
