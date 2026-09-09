# Frozen EVENT#2 evidence (public-safe)

Read-only freeze of the original AWS operational assessment. This is not a
rerun. No secrets, tokens, or account identifiers.

## Implementation anchors

| System | Identifier |
|---|---|
| AWS runtime SHA | `8ce11a1f18984743c8a11f9ad098a03c8448aabc` |
| AWS runtime build | `p4c-8ce11a1` |
| CommerceGov kernel SHA | `5390ea66d5286284fa1fc1f021920530c786bf69` |
| Model | `global.anthropic.claude-sonnet-4-6` |

## Event lineage

| Field | Value |
|---|---|
| CommerceGov event | `2` |
| Shop | `controlled-demo.myshopify.com` |
| Tenant | `shop_controlled-demo_myshopify_com` |
| Mutation | `product.title` |
| Before | `The Draft Snowboard` |
| After | `The Draft Snowboard — External Change` |
| DynamoDB PK | `TENANT#shop_controlled-demo_myshopify_com#SHOP#controlled-demo.myshopify.com` |
| DynamoDB SK | `EVENT#2` |
| Received | `2026-09-09T18:22:08.823042Z` |
| Completed | `2026-09-09T18:22:35.065697Z` |
| API Gateway request | `DcaINiQzIAMEbhA=` (`POST /events/operational`, HTTP 200, `cached=false`) |
| Execution id | `1cdb9423-6f0d-4d35-9cb5-e5115c924771` |
| Evidence id | `evidence:1cdb9423-6f0d-4d35-9cb5-e5115c924771` |

## AWS result (advisory)

| Field | Value |
|---|---|
| Assessment | `AUTHORITY_AT_RISK` |
| Authority mode | `PROPOSE_ONLY` |
| Terminal result | `HUMAN_AUTHORITY_REQUIRED` |
| Recommended action | `REVIEW_EXTERNAL_CHANGE` |
| Allowed actions | **NOT_PRESENT** (not persisted) |

This is an AWS advisory assessment. It is not CommerceGov approval and not an
Apply.

## CommerceGov Review handoff

| Field | Value |
|---|---|
| Review cycle | `external-remediation:2` |
| Review decision | `3435c400c1325c78ce0f6d79f1541eb9ac8c621c371fa473b50f868b0f08250c` |
| Final state | `review` |
| Auto-remediation | NO |
| New Apply | NO |

Human Review is an authority-plane admission, not an approved production write.

## Negative-authority evidence

- `PROPOSE_ONLY` / `autonomous_processing=STOP` / `human_authority_required=true`
- no persisted `allowed_actions`
- AWS production write: **NO**
- CommerceGov automatic production write: **NO**
- new Apply: **NO**

## Supported claims

- The AWS agent reasons about authority risk but does not possess production
  authority. The model can reason. It cannot grant itself authority.
- CommerceGov does not merely stop an agent at a human gate. It governs the
  production authority lifecycle before, during, and after the mutation.
- EVENT#2 is the original invocation (`DcaINiQzIAMEbhA=`, `cached=false`).
- Runtime build `p4c-8ce11a1` matches AWS SHA prefix `8ce11a1`.

## Unsupported claims

- Bedrock granted authority, AWS approved, AWS Applied, or AWS wrote Shopify.
- EVENT#2 auto-remediated production TITLE.
- `review` means approved or applied.
- `allowed_actions` were stored or granted.
- The CommerceGov kernel lives in this AWS repository.
