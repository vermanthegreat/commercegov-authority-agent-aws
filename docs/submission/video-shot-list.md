# Video shot list (~115 seconds)

Prefer the already proven result. Do **not** click Run for a new event unless
explicitly authorized. Show `judge-demo-v1-20260911-2030` / cached replay.

Do not expose: secrets, OAuth tokens, AWS account IDs, CloudWatch full logs,
product/policy JSON bodies, IAM keys.

| Shot | Seconds | Visible screen | Narration | Do not show |
|---|---|---|---|---|
| 1 | 0–15 | Title + architecture diagram (`docs/submission/architecture.md` or README planes) | “AI agents are probabilistic. Production authority cannot be. CommerceGov Authority Agent uses Strands and Amazon Bedrock to autonomously triage authority risk, while deterministic controls remain outside the model.” | Account IDs, ARNs with account |
| 2 | 15–25 | Public `/p2/demo` landing, **before** Run | “A commerce operational event enters AWS through API Gateway into Lambda.” | Do not click Run yet |
| 3 | 25–40 | Same page: Live Governed Context (use proven COMPLETED page or screenshot of 2030) | “Strands reads live CommerceGov product and policy context with two read-only tools, then asks Claude Sonnet 4.6 for one structured assessment.” | Raw API JSON |
| 4 | 40–50 | Product read SUCCEEDED / Policy read SUCCEEDED | “On the public demo, product read succeeded. Policy read succeeded.” | Policy body, product HTML |
| 5 | 50–70 | Strands / Amazon Bedrock: COMPLETED, NO_ACTION_REQUIRED, model assessment, COMPARE_WITH_GOVERNED_VALUE | “Semantic status is completed. Bedrock classifies this event as NO_ACTION_REQUIRED. But that recommendation is advisory.” | Full unclipped model dump if it fills the screen with PII |
| 6 | 70–90 | Deterministic Authority: AUTHORITY_AT_RISK, PROPOSE_ONLY, HUMAN AUTHORITY REQUIRED, STOPPED | “The deterministic authority layer classifies the event as AUTHORITY_AT_RISK, requires human authority, and stops autonomous processing. The model can recommend. It cannot authorize production.” | Approve/Apply UI (none exists; do not imply it) |
| 7 | 90–100 | Evidence ID `evidence:2cc43b64-7396-426d-9595-ed2c97ed8ea9` | “Every assessment is written to a DynamoDB evidence ledger.” | Table scan of other tenants |
| 8 | 100–110 | Replay: CACHED — IDEMPOTENT REPLAY / Already assessed | “Replaying the same event returns the original decision. It does not call Bedrock again.” | A second fresh Run that would start a new bucket |
| 9 | 110–115 | Architecture + thesis card | “AI remains probabilistic. Authority does not.” | AgentCore logos |

If a fresh recording event is later authorized, still click Run **once**, wait,
then replay the **same** event once.
