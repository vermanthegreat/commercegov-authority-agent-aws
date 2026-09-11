# Final judge claim audit

MODEL = probabilistic intelligence. AUTHORITY LAYER = deterministic control.

| Statement | Classification |
|---|---|
| Amazon Bedrock live structured output on `judge-demo-v1-20260911-2030` | **PROVEN LIVE** |
| Strands Agents SDK 1.54.0 invoked | **PROVEN LIVE** |
| AWS Lambda + HTTP API + DynamoDB ledger | **PROVEN LIVE** |
| Secrets Manager used for inbound/read bearers | **PROVEN LIVE** (values not shown) |
| CommerceGov product + policy GET succeeded | **PROVEN LIVE** |
| Model classification `NO_ACTION_REQUIRED` | **PROVEN LIVE** |
| Model action `COMPARE_WITH_GOVERNED_VALUE` | **PROVEN LIVE** |
| Deterministic `AUTHORITY_AT_RISK` / `PROPOSE_ONLY` / `HUMAN_AUTHORITY_REQUIRED` / `STOP` | **PROVEN LIVE** |
| Provider fallback not used on 2030 | **PROVEN LIVE** |
| Idempotent replay, no second Bedrock call | **PROVEN LIVE** |
| Fail-closed floor on timeout/provider error | **PROVEN LIVE** (secondary events 1945–2025) |
| Structured-output schema clip / one invocation | **PROVEN IN TESTS** |
| Stale complete cannot overwrite PROCESSING fence | **PROVEN IN TESTS** |
| IAM least privilege (no Shopify write, no Approve/Apply) | **PROVEN IN TESTS** + **DOCUMENTED ARCHITECTURE** |
| Read-only tools `get_governance_context`, `get_effective_policy` | **PROVEN IN TESTS** + **DOCUMENTED ARCHITECTURE** |
| AgentCore | **DO NOT CLAIM** |
| AWS agent writes Shopify | **DO NOT CLAIM** |
| AWS agent creates CommerceGov proposals | **DO NOT CLAIM** |
| AWS agent Approves | **DO NOT CLAIM** |
| AWS agent Applies | **DO NOT CLAIM** |
| Autonomous production execution | **DO NOT CLAIM** |
| Deterministic AI/model inference | **DO NOT CLAIM** |
