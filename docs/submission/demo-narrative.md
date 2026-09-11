# Judge demo script (~90–150 seconds)

Canonical ~115s recording script: `docs/submission/video-script.md`.  
Shot list: `docs/submission/video-shot-list.md`.

Public fixture (do not click Run twice while a request is in flight):
https://40k4yk7gh2.execute-api.us-east-1.amazonaws.com/p2/demo

Primary recording: `judge-demo-v1-20260911-2030` (COMPLETED Bedrock). AWS never
writes Shopify. CommerceGov never auto-Applies.

## STEP 1 — Problem (~15s)

AI agents are probabilistic. Production authority cannot be.

An agent can read context and recommend. It must not approve, Apply, or write
Shopify.

## STEP 2 — Event (~15s)

A governed commerce event enters the AWS agent: shop
`controlled-demo.myshopify.com`, product `7887756099661`, mutation
`product.title`. Ingress is API Gateway → Lambda.

## STEP 3 — Intelligence (~20s)

Show live governed context:

- Product read: SUCCEEDED
- Policy read: SUCCEEDED
- Strands Agents SDK + Amazon Bedrock (Claude Sonnet 4.6)
- Semantic status: COMPLETED

The agent reads governance context and effective policy using bounded
read-only tools. It does not write proposals.

## STEP 4 — Model result (~20s)

Show probabilistic intelligence:

- Classification: `NO_ACTION_REQUIRED`
- Recommended action: `COMPARE_WITH_GOVERNED_VALUE`

This is Bedrock structured output. It is advice, not permission.

## STEP 5 — Authority boundary (~20s)

Show deterministic authority:

- `AUTHORITY_AT_RISK`
- `PROPOSE_ONLY`
- `HUMAN_AUTHORITY_REQUIRED`
- `STOP`

Say: the model can recommend. It cannot authorize production.

This mismatch is intentional. Even when the model believes no action is
required, policy still requires a human.

## STEP 6 — Evidence (~15s)

Show execution `2cc43b64-7396-426d-9595-ed2c97ed8ea9` and evidence
`evidence:2cc43b64-7396-426d-9595-ed2c97ed8ea9`. Every assessment is recorded
and replay-safe.

## STEP 7 — Idempotency (~15s)

Replay the same event once. Show: Already assessed — returning the original
authority decision. The same operational event does not trigger a second
Bedrock call.

## STEP 8 — Close (~10s)

AI remains probabilistic. Authority does not.

## Secondary (do not lead with this)

If Bedrock times out or structured output fails, the page shows PROVIDER ERROR
and the same STOP floor. That is honesty, not the primary demo.

Historical operational EVENT#2: `docs/submission/aws-event-2-evidence.md`.
