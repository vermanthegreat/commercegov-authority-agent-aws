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

## P2 AWS hosted runtime

P2 adds a synthetic-only hosted proof while leaving CommerceGov and its
production integrations untouched:

```text
IAM-signed API Gateway HTTP API /assess
  -> Lambda transport adapter
  -> tenant-bound DynamoDB atomic claim
  -> Strands 1.54.0 / Bedrock semantic assessment
  -> P0 deterministic authority kernel
  -> DynamoDB exact response + concise evidence
  -> CommerceGov-compatible HTTP response
```

The API uses `AWS_IAM`; unsigned callers cannot invoke the route. This is a
replaceable P2 proof boundary, not the final CommerceGov OAuth design. The
Lambda role can write only its one table, invoke only
`global.anthropic.claude-sonnet-4-6` through its exact inference profile/model
ARNs, write only its own CloudWatch logs, and read only the inbound CommerceGov
bearer secret used by `POST /events/operational`. It has no CommerceGov write,
Shopify, database, approval, Apply, or unrelated DynamoDB permission.

The single DynamoDB item uses:

- `PK = TENANT#{agency_id}#SHOP#{shop_id}`
- `SK = EVENT#{event_id}`

The first request atomically creates `PROCESSING` with a canonical SHA-256
request fingerprint. Successful processing conditionally transitions it to
`COMPLETE` and stores the exact response plus bounded evidence. An exact
duplicate returns that response without a second model call. A different hash
for the same tenant/event fails closed as a conflict. No TTL is configured, so
the P2 evidence remains available; encryption and point-in-time recovery are
enabled.

Evidence includes safe identities, timestamps, execution/evidence IDs, request
and response hashes, the supplied policy context reference, provider/model,
semantic status/classification/summary, deterministic authority result, and
runtime build identity. It excludes raw headers, credentials, unrestricted
model input/output, and chain-of-thought.

The synchronous budget is API Gateway/Lambda 29 seconds with the semantic
provider capped at 24 seconds. Any semantic timeout is still processed by the
P0 fail-safe authority floor. Structured logs record safe event identity,
canonical/duplicate/conflict path, semantic outcome, persistence, terminal
status, cache status, and latency.

Build and deploy the reproducible SAM stack:

```powershell
./scripts/deploy_p2.ps1 -BuildId p2-candidate
```

The build script installs an explicit Linux x86_64 Python 3.13 runtime lock
into `.build/lambda`. The unused MCP transport dependency is excluded because
P2 loads only local decorated tools; this also avoids incorrectly resolving
MCP's Windows-only `pywin32` marker on the Windows build host. The deployed
artifact imports no MCP module. Normal tests and build artifacts do not require
live AWS.
Hosted certification
uses SigV4 and the canonical synthetic fixture:

```powershell
python ./scripts/certify_hosted.py --endpoint <stack-output> --table <stack-output>
```

## P3A live ingress compatibility

P3A is not a new agent. It adds CommerceGov's existing operational ingress
route to the certified P2 runtime:

```text
POST /events/operational
  Authorization: Bearer <inbound secret>
  -> same Lambda / P0 kernel / DynamoDB ledger as POST /assess
```

`POST /assess` remains AWS_IAM authenticated and behaviorally unchanged. The
operational route disables API Gateway IAM (`Authorizer: NONE`) and validates
the CommerceGov bearer in Lambda before any model, tool, or ledger write.
Missing or wrong bearer requests fail closed and do not create a successful
assessment record. Both routes share the same idempotency key and response
adapter. Hosted operational certification:

```powershell
python ./scripts/certify_p3a.py --assess-endpoint <stack-output> --operational-endpoint <stack-output> --table <stack-output> --secret-arn <stack-output>
```

P3A does not add live CommerceGov read tools, OAuth, Review creation, or a
Shopify-to-Review claim.

## P3B live read-only CommerceGov context

P3B is opt-in and does not change `/assess`. When `COMMERCEGOV_BASE_URL` is an
HTTPS origin and `COMMERCEGOV_READ_SECRET_ARN` is set, `POST /events/operational`
reuses `CommerceGovReadClient` to fetch product content and effective policy
before Bedrock. Incomplete live config keeps the certified synthetic context
builder. The outbound read secret is separate from the inbound operational
bearer. Context is information only; the P0 floor remains
`AUTHORITY_AT_RISK / HUMAN_AUTHORITY_REQUIRED / STOP`. Evidence records
`context_source=live_commercegov` plus bounded product/policy hashes, never
tokens or full CommerceGov bodies.

```powershell
python ./scripts/certify_p3b.py --assess-endpoint <stack-output> --operational-endpoint <stack-output> --table <stack-output> --inbound-secret-arn <stack-output> --read-secret-arn <stack-output> --commercegov-base-url <https-origin>
```

If no valid CommerceGov read credential is available, hosted live proof is
blocked and P2/P3A certification remains the deployed baseline.

### Originality by phase

PRE-EXISTING: CommerceGov governance platform, Shopify integration, policy
model, Review/approval/Apply workflow, and operational event concept.

AWS HACKATHON WORK: P0 deterministic authority kernel; P1 Strands/Bedrock
semantic assessment and bounded tools; P2 AWS Lambda/API runtime with durable
DynamoDB idempotency and evidence; P3A CommerceGov `POST /events/operational`
ingress compatibility; P3B optional live read-only CommerceGov context. The
`scope_key` producer/consumer mismatch remains unfixed.

## KNOWN_EXTERNAL_INTEGRATION_BLOCKER

The real CommerceGov producer places `scope_key` at
`policy_context.scope_key`, while current CommerceGov remediation admission
reads a top-level `handoff_payload["scope_key"]`. P0 fixtures intentionally
match the real producer contract and do not add the artificial top-level field.
CommerceGov is not modified here; that mismatch requires a separately
authorized change after this spine is stable. P2 neither fixes nor works around
it and does not fabricate a top-level `scope_key`. P3A also leaves that
mismatch unfixed and does not claim a live Shopify-to-Review demonstration.
P3B also leaves that mismatch unfixed.
