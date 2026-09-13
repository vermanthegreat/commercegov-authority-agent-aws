"""Durable judge-prompt run records. Transport only; no authority decisions."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Mapping, Protocol

from botocore.exceptions import ClientError

from authority_agent.prompt_runtime import AGENT_AUTHORITY, PRODUCTION_MUTATION_NONE

RUN_STATUS_RUNNING = "RUNNING"
ENTITY_TYPE = "AGENT_PROMPT_RUN"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def running_evidence(run_id: str) -> dict[str, str]:
    token = str(run_id or "").strip()
    return {
        "aws_run_id": token,
        "agent_authority": AGENT_AUTHORITY,
        "production_mutation": PRODUCTION_MUTATION_NONE,
        "status": RUN_STATUS_RUNNING,
    }


def run_key(run_id: str) -> dict[str, str]:
    token = str(run_id or "").strip()
    return {"PK": f"AGENT_RUN#{token}", "SK": "PROMPT"}


class PromptRunRecord(dict[str, Any]):
    pass


class PromptRunStore(Protocol):
    def create_running(self, run_id: str, prompt: str) -> dict[str, Any]:
        ...

    def get(self, run_id: str) -> dict[str, Any] | None:
        ...

    def complete(
        self,
        run_id: str,
        *,
        state: str,
        agent_response: str,
        evidence: Mapping[str, str],
    ) -> dict[str, Any] | None:
        ...


class PromptRunInvoker(Protocol):
    def start(self, *, run_id: str, prompt: str) -> None:
        ...


class MemoryPromptRunStore:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}

    def create_running(self, run_id: str, prompt: str) -> dict[str, Any]:
        token = str(run_id or "").strip()
        if token in self.items:
            return self.items[token]
        record = {
            "run_id": token,
            "prompt": str(prompt or ""),
            "status": RUN_STATUS_RUNNING,
            "agent_response": "",
            "evidence": running_evidence(token),
        }
        self.items[token] = record
        return record

    def get(self, run_id: str) -> dict[str, Any] | None:
        record = self.items.get(str(run_id or "").strip())
        return dict(record) if record is not None else None

    def complete(
        self,
        run_id: str,
        *,
        state: str,
        agent_response: str,
        evidence: Mapping[str, str],
    ) -> dict[str, Any] | None:
        token = str(run_id or "").strip()
        record = self.items.get(token)
        if record is None:
            return None
        if record.get("status") != RUN_STATUS_RUNNING:
            return dict(record)
        record["status"] = str(state)
        record["agent_response"] = str(agent_response or "")
        merged = dict(record.get("evidence") or {})
        merged.update({key: str(value) for key, value in dict(evidence).items() if value})
        merged["status"] = str(state)
        record["evidence"] = merged
        return dict(record)


class DynamoPromptRunStore:
    def __init__(self, table: Any) -> None:
        self._table = table

    def create_running(self, run_id: str, prompt: str) -> dict[str, Any]:
        token = str(run_id or "").strip()
        now = utc_now()
        item = {
            **run_key(token),
            "entity_type": ENTITY_TYPE,
            "run_id": token,
            "prompt": str(prompt or ""),
            "status": RUN_STATUS_RUNNING,
            "agent_response": "",
            "evidence": running_evidence(token),
            "created_at": now,
            "updated_at": now,
        }
        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
            return _public_record(item)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            existing = self.get(token)
            if existing is None:
                raise
            return existing

    def get(self, run_id: str) -> dict[str, Any] | None:
        token = str(run_id or "").strip()
        if not token:
            return None
        item = self._table.get_item(Key=run_key(token), ConsistentRead=True).get("Item")
        if not isinstance(item, Mapping):
            return None
        return _public_record(item)

    def complete(
        self,
        run_id: str,
        *,
        state: str,
        agent_response: str,
        evidence: Mapping[str, str],
    ) -> dict[str, Any] | None:
        token = str(run_id or "").strip()
        merged = running_evidence(token)
        merged.update({key: str(value) for key, value in dict(evidence).items() if value})
        merged["status"] = str(state)
        try:
            self._table.update_item(
                Key=run_key(token),
                UpdateExpression=(
                    "SET #status = :status, agent_response = :agent_response, "
                    "evidence = :evidence, updated_at = :updated_at"
                ),
                ConditionExpression="#status = :running",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":status": str(state),
                    ":running": RUN_STATUS_RUNNING,
                    ":agent_response": str(agent_response or ""),
                    ":evidence": merged,
                    ":updated_at": utc_now(),
                },
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
        return self.get(token)


class LambdaEventPromptRunInvoker:
    def __init__(self, client: Any, function_name: str) -> None:
        self._client = client
        self._function_name = function_name

    def start(self, *, run_id: str, prompt: str) -> None:
        payload = json.dumps(
            {"agent_prompt_run": True, "run_id": run_id, "prompt": prompt},
            separators=(",", ":"),
            ensure_ascii=False,
        )
        self._client.invoke(
            FunctionName=self._function_name,
            InvocationType="Event",
            Payload=payload.encode("utf-8"),
        )


def _public_record(item: Mapping[str, Any]) -> dict[str, Any]:
    evidence = item.get("evidence")
    return {
        "run_id": str(item.get("run_id") or ""),
        "prompt": str(item.get("prompt") or ""),
        "status": str(item.get("status") or ""),
        "agent_response": str(item.get("agent_response") or ""),
        "evidence": dict(evidence) if isinstance(evidence, Mapping) else {},
    }
