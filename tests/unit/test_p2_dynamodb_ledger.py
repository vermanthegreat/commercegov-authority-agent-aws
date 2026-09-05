from __future__ import annotations

from copy import deepcopy

from botocore.exceptions import ClientError
import pytest

from authority_agent.contracts import ConflictingDuplicateError, EventInProgressError
from authority_agent.dynamodb_ledger import DynamoDbIdempotencyLedger, event_sort_key, tenant_partition_key
from authority_agent.normalization import normalize_commercegov_event
from authority_agent.orchestration import AuthorityProcessor, TenantBindingRegistry


class FakeTable:
    def __init__(self):
        self.items = {}
        self.put_calls = []
        self.update_calls = []

    def put_item(self, **kwargs):
        self.put_calls.append(deepcopy(kwargs))
        item = deepcopy(kwargs["Item"])
        key = (item["PK"], item["SK"])
        if key in self.items:
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException", "Message": "exists"}},
                "PutItem",
            )
        self.items[key] = item
        return {}

    def get_item(self, **kwargs):
        key = (kwargs["Key"]["PK"], kwargs["Key"]["SK"])
        item = self.items.get(key)
        return {"Item": deepcopy(item)} if item else {}

    def update_item(self, **kwargs):
        self.update_calls.append(deepcopy(kwargs))
        key = (kwargs["Key"]["PK"], kwargs["Key"]["SK"])
        item = self.items[key]
        values = kwargs["ExpressionAttributeValues"]
        if item["request_hash"] != values[":request_hash"] or item["processing_status"] != "PROCESSING":
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException", "Message": "condition"}},
                "UpdateItem",
            )
        item.update(
            processing_status="COMPLETE",
            response=deepcopy(values[":response"]),
            evidence=deepcopy(values[":evidence"]),
            response_hash=values[":response_hash"],
            completed_at=values[":completed_at"],
            updated_at=values[":updated_at"],
        )
        return {}


class CountingProvider:
    provider_name = "StrandsSemanticProvider"
    model_id = "global.anthropic.claude-sonnet-4-6"

    def __init__(self):
        self.calls = 0

    def assess(self, _event):
        self.calls += 1
        return {
            "classification": "NO_ACTION_REQUIRED",
            "summary": "Hostile downgrade attempt.",
            "recommended_operator_action": "APPLY",
        }


class FailingProvider(CountingProvider):
    def assess(self, _event):
        self.calls += 1
        raise TimeoutError("synthetic semantic timeout")


def make_durable_processor(table, provider, bindings=None):
    ticks = iter(["2026-09-05T10:00:00Z", "2026-09-05T10:00:01Z"] * 10)
    ids = iter([f"execution-{number}" for number in range(1, 20)])
    ledger = DynamoDbIdempotencyLedger(
        table,
        clock=lambda: next(ticks),
        id_factory=lambda: next(ids),
        build_id="p2-test-build",
    )
    return AuthorityProcessor(
        bindings=TenantBindingRegistry(bindings or [("demo-agency", "demo-shop.myshopify.com")]),
        ledger=ledger,
        semantic_provider=provider,
    ), ledger


def test_atomic_claim_complete_and_evidence(canonical_payload) -> None:
    table = FakeTable()
    provider = CountingProvider()
    processor, _ledger = make_durable_processor(table, provider)
    response = processor.process(canonical_payload)
    event = normalize_commercegov_event(canonical_payload)
    item = table.items[(tenant_partition_key(event), event_sort_key(event))]
    assert table.put_calls[0]["ConditionExpression"] == "attribute_not_exists(PK) AND attribute_not_exists(SK)"
    assert response.body["intelligence_classification"] == "AUTHORITY_AT_RISK"
    assert response.body["status"] == "HUMAN_AUTHORITY_REQUIRED"
    assert item["processing_status"] == "COMPLETE"
    assert item["runtime_build_id"] == "p2-test-build"
    assert item["policy_context_reference"] == canonical_payload["policy_context"]["scope_key"]
    assert item["evidence"]["semantic_provider"] == "StrandsSemanticProvider"
    assert item["evidence"]["semantic_model"] == provider.model_id
    assert item["evidence"]["semantic_classification"] == "NO_ACTION_REQUIRED"
    assert item["evidence"]["deterministic_classification"] == "AUTHORITY_AT_RISK"
    assert item["evidence"]["autonomous_processing"] == "STOP"
    assert item["evidence"]["terminal_status"] == "HUMAN_AUTHORITY_REQUIRED"
    assert item["response_hash"] == item["evidence"]["response_hash"]


def test_exact_duplicate_returns_same_response_without_second_semantic_call(canonical_payload) -> None:
    table = FakeTable()
    provider = CountingProvider()
    processor, _ledger = make_durable_processor(table, provider)
    first = processor.process(canonical_payload)
    item_before = deepcopy(table.items)
    second = processor.process(canonical_payload)
    assert second.cached is True
    assert second.body == first.body
    assert table.items == item_before
    assert len(table.update_calls) == 1
    assert provider.calls == 1


def test_conflicting_duplicate_is_distinct_and_does_not_invoke_model(canonical_payload) -> None:
    table = FakeTable()
    provider = CountingProvider()
    processor, _ledger = make_durable_processor(table, provider)
    processor.process(canonical_payload)
    conflict = deepcopy(canonical_payload)
    conflict["current_value"] = "materially different"
    conflict["policy_context"]["observed_shopify_value"] = "materially different"
    with pytest.raises(ConflictingDuplicateError):
        processor.process(conflict)
    assert provider.calls == 1


def test_processing_duplicate_fails_closed(canonical_payload) -> None:
    table = FakeTable()
    provider = CountingProvider()
    _processor, ledger = make_durable_processor(table, provider)
    event = normalize_commercegov_event(canonical_payload)
    ledger.claim(event, "same-hash")
    with pytest.raises(EventInProgressError, match="event_processing_in_progress"):
        ledger.claim(event, "same-hash")


def test_same_event_id_has_separate_tenant_partition(canonical_payload) -> None:
    table = FakeTable()
    provider = CountingProvider()
    processor, _ledger = make_durable_processor(
        table,
        provider,
        bindings=[
            ("demo-agency", "demo-shop.myshopify.com"),
            ("other-agency", "other-shop.myshopify.com"),
        ],
    )
    processor.process(canonical_payload)
    other = deepcopy(canonical_payload)
    other["agency_id"] = "other-agency"
    other["shop_id"] = "other-shop.myshopify.com"
    processor.process(other)
    assert len(table.items) == 2
    assert {key[0] for key in table.items} == {
        "TENANT#demo-agency#SHOP#demo-shop.myshopify.com",
        "TENANT#other-agency#SHOP#other-shop.myshopify.com",
    }
    assert provider.calls == 2


def test_semantic_failure_is_completed_with_explicit_error_evidence(canonical_payload) -> None:
    table = FakeTable()
    provider = FailingProvider()
    processor, _ledger = make_durable_processor(table, provider)
    response = processor.process(canonical_payload)
    event = normalize_commercegov_event(canonical_payload)
    item = table.items[(tenant_partition_key(event), event_sort_key(event))]
    assert response.body["intelligence_classification"] == "AUTHORITY_AT_RISK"
    assert item["processing_status"] == "COMPLETE"
    assert item["evidence"]["semantic_status"] == "provider_error"
    assert item["evidence"]["error_category"] == "semantic_provider_error"
    assert item["evidence"]["terminal_status"] == "HUMAN_AUTHORITY_REQUIRED"
