# CommerceGov Authority Agent

Local P0 safety spine plus a bounded P1 Strands semantic layer for the AWS
Agents for Humans Hackathon 2026.

The core invariant is: **capability is not authority**. P0 accepts the audited
CommerceGov operational-event payload, validates and tenant-binds it, optionally
invokes a real Strands/Bedrock semantic provider, applies deterministic authority
controls, and emits the existing CommerceGov response shape. The model remains
advisory and cannot approve, apply, mutate production, or grant authority.

## Originality boundary

PRE-EXISTING:

- CommerceGov governance platform
- Shopify integration
- policy model
- review, approval, and Apply workflow
- operational event concept

NEW FOR AWS AGENTS FOR HUMANS:

- this authority-agent repository
- event normalization layer
- deterministic AWS-agent authority boundary
- Strands 1.54.0 semantic adapter with strict structured output
- two tenant-bound, cached, read-only context tools
- AWS deployment/runtime in later slices
- AWS evidence and idempotency implementation in later slices

No pre-existing CommerceGov work is claimed as hackathon-created.

## Run locally

Python 3.11 or newer is required.

```powershell
python -m pip install -e ".[test]"
python -m authority_agent.handler fixtures/external_product_title_change.json
pytest -q
```

The runner has one explicit demo binding:
`demo-agency + demo-shop.myshopify.com`. Override it with `--agency-id` and
`--shop-id` when exercising another non-production fixture.

Expected terminal result:

```text
AUTHORITY_AT_RISK / HUMAN_AUTHORITY_REQUIRED / STOP
```

## P1 semantic layer

`StrandsSemanticProvider` uses the current Strands `Agent` structured-output API
and the native `BedrockModel` adapter. Its default model ID is
`global.anthropic.claude-sonnet-4-6`. The response schema accepts only an
advisory classification, summary, allowlisted operator recommendation, and
optional confidence. Extra authority, approval, or Apply fields are rejected.

Before invocation, a fixed-endpoint CommerceGov read client fetches the exact
product content and effective policy. It validates the returned shop and product
identity, then builds a minimized context. The Strands tool registry exposes
exactly `get_governance_context` and `get_effective_policy`; both return cached
data and require the event's exact agency, shop, target type, and target ID.
There is no arbitrary HTTP, write, approval, Apply, credential, or infrastructure
tool.

Malformed context, cross-tenant identity, model errors, tool errors, timeouts,
and invalid structured output all become provider failures. P0 catches those
failures and deterministically returns `AUTHORITY_AT_RISK`,
`HUMAN_AUTHORITY_REQUIRED`, and `STOP` semantics.

Normal tests use fake transports and fake agents and make no AWS or network
calls. A real Bedrock smoke is deliberately opt-in and uses the standard AWS
credential chain without creating or storing credentials:

```powershell
$env:RUN_BEDROCK_LIVE_SMOKE = "1"
python -m authority_agent.live_bedrock_smoke
```

Without that exact flag, the smoke reports `BEDROCK_LIVE_SMOKE: BLOCKED` and
does not construct an AWS client.

## P0/P1 isolation

The default local runner still uses the P0 in-process stub. P1 adds only the
replaceable semantic adapter and GET-only CommerceGov context client. This
repository has no AWS deployment, OAuth flow, database, Shopify mutation,
approval, Apply, or production-write implementation, and stores no credentials.
Later slices can wire runtime and durable idempotency without weakening
deterministic control.

## KNOWN_EXTERNAL_INTEGRATION_BLOCKER

The real CommerceGov producer places `scope_key` at
`policy_context.scope_key`, while current CommerceGov remediation admission
reads a top-level `handoff_payload["scope_key"]`. P0 fixtures intentionally
match the real producer contract and do not add the artificial top-level field.
CommerceGov is not modified here; that mismatch requires a separately
authorized change after this spine is stable.
