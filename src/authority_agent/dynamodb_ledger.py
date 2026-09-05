"""DynamoDB-backed idempotency and concise evidence for the P2 runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

from botocore.exceptions import ClientError

from authority_agent.contracts import (
    AuthorityEvent,
    ConflictingDuplicateError,
    EventIdentityConflictError,
    EventInProgressError,
)
from authority_agent.orchestration import ClaimResult


class DynamoTable(Protocol):
    def put_item(self, **kwargs: Any) -> Mapping[str, Any]: ...
    def get_item(self, **kwargs: Any) -> Mapping[str, Any]: ...
    def update_item(self, **kwargs: Any) -> Mapping[str, Any]: ...


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def tenant_partition_key(event: AuthorityEvent) -> str:
    return f"TENANT#{event.agency_id}#SHOP#{event.shop_id}"


def event_sort_key(event: AuthorityEvent) -> str:
    return f"EVENT#{event.event_id}"


def response_hash(response: Mapping[str, Any]) -> str:
    encoded = json.dumps(response, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


class DynamoDbIdempotencyLedger:
    """One item per tenant/event; conditional writes are the race boundary."""

    def __init__(
        self,
        table: DynamoTable,
        *,
        clock: Callable[[], str] = _utc_now,
        id_factory: Callable[[], str] = lambda: str(uuid4()),
        build_id: str = "unknown",
        logger: logging.Logger | None = None,
    ) -> None:
        self._table = table
        self._clock = clock
        self._id_factory = id_factory
        self._build_id = build_id
        self._logger = logger or logging.getLogger(__name__)

    @staticmethod
    def _key(event: AuthorityEvent) -> dict[str, str]:
        return {"PK": tenant_partition_key(event), "SK": event_sort_key(event)}

    def claim(self, event: AuthorityEvent, request_hash: str) -> ClaimResult:
        execution_id = self._id_factory()
        evidence_id = f"evidence:{execution_id}"
        now = self._clock()
        item = {
            **self._key(event),
            "entity_type": "AUTHORITY_EXECUTION",
            "processing_status": "PROCESSING",
            "request_hash": request_hash,
            "event_id": event.event_id,
            "agency_id": event.agency_id,
            "shop_id": event.shop_id,
            "target_type": event.target_type,
            "target_id": event.target_id,
            "mutation_class": event.mutation_class,
            "policy_context_reference": event.scope_key,
            "execution_id": execution_id,
            "evidence_id": evidence_id,
            "received_at": now,
            "updated_at": now,
            "runtime_build_id": self._build_id,
        }
        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
            self._log("idempotency_claimed", event, path="canonical")
            return ClaimResult(execution_id=execution_id, evidence_id=evidence_id)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise

        existing = self._table.get_item(Key=self._key(event), ConsistentRead=True).get("Item")
        if not existing:
            raise EventInProgressError("idempotency_claim_race")
        if existing.get("agency_id") != event.agency_id or existing.get("shop_id") != event.shop_id:
            raise EventIdentityConflictError("event_tenant_identity_conflict")
        if existing.get("request_hash") != request_hash:
            self._log("idempotency_conflict", event, path="conflict")
            raise ConflictingDuplicateError("conflicting_duplicate")
        if existing.get("processing_status") == "COMPLETE" and isinstance(existing.get("response"), Mapping):
            self._log("idempotency_duplicate", event, path="duplicate")
            return ClaimResult(
                cached_response=dict(existing["response"]),
                execution_id=existing.get("execution_id"),
                evidence_id=existing.get("evidence_id"),
            )
        raise EventInProgressError("event_processing_in_progress")

    def complete(
        self,
        event: AuthorityEvent,
        request_hash: str,
        response: Mapping[str, Any],
        evidence: Mapping[str, Any] | None = None,
    ) -> None:
        now = self._clock()
        safe_evidence = {key: value for key, value in dict(evidence or {}).items() if value is not None}
        safe_evidence["response_hash"] = response_hash(response)
        safe_evidence["completed_at"] = now
        try:
            self._table.update_item(
                Key=self._key(event),
                UpdateExpression=(
                    "SET processing_status = :complete, #response = :response, "
                    "evidence = :evidence, response_hash = :response_hash, "
                    "completed_at = :completed_at, updated_at = :updated_at"
                ),
                ConditionExpression="request_hash = :request_hash AND processing_status = :processing",
                ExpressionAttributeNames={"#response": "response"},
                ExpressionAttributeValues={
                    ":complete": "COMPLETE",
                    ":processing": "PROCESSING",
                    ":request_hash": request_hash,
                    ":response": dict(response),
                    ":evidence": safe_evidence,
                    ":response_hash": safe_evidence["response_hash"],
                    ":completed_at": now,
                    ":updated_at": now,
                },
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise EventIdentityConflictError("idempotency_completion_conflict") from exc
            raise
        self._log("evidence_persisted", event, path="canonical", terminal_status=safe_evidence.get("terminal_status"))

    def _log(self, message: str, event: AuthorityEvent, **fields: Any) -> None:
        self._logger.info(
            json.dumps(
                {
                    "message": message,
                    "event_id": event.event_id,
                    "agency_id": event.agency_id,
                    "shop_id": event.shop_id,
                    "target_type": event.target_type,
                    "target_id": event.target_id,
                    "mutation_class": event.mutation_class,
                    **fields,
                },
                sort_keys=True,
            )
        )
