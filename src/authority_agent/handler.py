"""P0 local handler and fixture runner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from authority_agent.contracts import ContractError, IdempotencyError, TenantBindingError
from authority_agent.orchestration import (
    AuthorityProcessor,
    InMemoryIdempotencyLedger,
    StaticSemanticProvider,
    TenantBindingRegistry,
)


def handle_payload(processor: AuthorityProcessor, payload: Mapping[str, Any]) -> dict[str, Any]:
    try:
        result = processor.process(payload)
    except ContractError as exc:
        return {
            "status_code": 400,
            "body": {"error": exc.code, "terminal_status": "FAIL_CLOSED"},
            "cached": False,
        }
    except TenantBindingError as exc:
        return {
            "status_code": 403,
            "body": {"error": exc.code, "terminal_status": "FAIL_CLOSED"},
            "cached": False,
        }
    except IdempotencyError as exc:
        return {
            "status_code": 409,
            "body": {"error": exc.code, "terminal_status": "FAIL_CLOSED"},
            "cached": False,
        }
    return {
        "status_code": result.status_code,
        "body": result.body,
        "cached": result.cached,
    }


def build_demo_processor(agency_id: str, shop_id: str) -> AuthorityProcessor:
    return AuthorityProcessor(
        bindings=TenantBindingRegistry([(agency_id, shop_id)]),
        ledger=InMemoryIdempotencyLedger(),
        semantic_provider=StaticSemanticProvider(
            {
                "classification": "NO_ACTION_REQUIRED",
                "summary": "Semantic analysis attempted a harmless classification.",
                "recommended_operator_action": "REVIEW_EXTERNAL_CHANGE",
            }
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Process one local CommerceGov fixture")
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--agency-id", default="demo-agency")
    parser.add_argument("--shop-id", default="demo-shop.myshopify.com")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.fixture.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status_code": 400, "error": type(exc).__name__}))
        return 1
    response = handle_payload(
        build_demo_processor(args.agency_id, args.shop_id), payload
    )
    print(json.dumps(response, indent=2, sort_keys=True))
    return 0 if response["status_code"] == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())

