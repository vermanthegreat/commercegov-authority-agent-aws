# CommerceGov Authority Agent

Local P0 safety spine for the AWS Agents for Humans Hackathon 2026.

The core invariant is: **capability is not authority**. P0 accepts the audited
CommerceGov operational-event payload, validates and tenant-binds it, invokes a
stub semantic provider, applies deterministic authority controls, and emits the
existing CommerceGov response shape. It performs no network or production
actions.

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
- Strands and Bedrock integration in later slices
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

## P0 isolation

P0 has no Strands, Bedrock, AWS, OAuth, CommerceGov HTTP, database, Shopify,
approval, Apply, or production-write implementation. The semantic provider is
an in-process stub behind a protocol. Later slices can replace the protocol and
idempotency adapter without weakening deterministic control.

## KNOWN_EXTERNAL_INTEGRATION_BLOCKER

The real CommerceGov producer places `scope_key` at
`policy_context.scope_key`, while current CommerceGov remediation admission
reads a top-level `handoff_payload["scope_key"]`. P0 fixtures intentionally
match the real producer contract and do not add the artificial top-level field.
CommerceGov is not modified here; that mismatch requires a separately
authorized change after this spine is stable.

