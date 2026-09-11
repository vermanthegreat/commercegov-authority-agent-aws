# Compact evidence index

Primary demo is the successful COMPLETED Bedrock run. Failure paths are secondary.

## Primary success

| Field | Value |
|---|---|
| Build ID | `p4c-so-clip-summary` |
| Event ID | `judge-demo-v1-20260911-2030` |
| API Gateway request ID | `DjSz8hQwIAMESrw=` |
| Lambda request ID | `c1328944-d47e-4854-b62c-22a39e84f156` |
| Execution ID | `2cc43b64-7396-426d-9595-ed2c97ed8ea9` |
| Evidence ID | `evidence:2cc43b64-7396-426d-9595-ed2c97ed8ea9` |
| Model ID | `global.anthropic.claude-sonnet-4-6` |
| Strands version | `1.54.0` |
| Product / policy read | SUCCEEDED / SUCCEEDED |
| Semantic status | COMPLETED |
| Model classification | `NO_ACTION_REQUIRED` |
| Model recommended action | `COMPARE_WITH_GOVERNED_VALUE` |
| Deterministic classification | `AUTHORITY_AT_RISK` |
| Authority result | `PROPOSE_ONLY` / `HUMAN_AUTHORITY_REQUIRED` / `STOP` |
| Provider fallback | NO |
| Replay request ID | `DjS8-hzYIAMESwA=` |
| Second Bedrock invocation | NO |

## Secondary failure-path (still fail-closed)

| Event | Shape | Authority floor |
|---|---|---|
| `judge-demo-v1-20260911-1945` | Semantic timeout (~24s), no `model_completed` | PROPOSE_ONLY / HUMAN_AUTHORITY_REQUIRED / STOP |
| `judge-demo-v1-20260911-1955` | Timeout during third Bedrock turn; client 503 | same |
| `judge-demo-v1-20260911-2005` | Structured-output processing error after ~15.6s | same |
| `judge-demo-v1-20260911-2025` | `tool_use` + `ValidationError` on `summary` length | same |

Public UI showed PROVIDER ERROR honestly. Fallback was never presented as model success.

## Tests (focused, last freeze)

```text
py -3.13 -m pytest tests/unit/test_strands_structured_output_shapes.py tests/integration/test_p1_strands_provider.py tests/unit/test_strands_observability.py tests/integration/test_p4_evaluation_matrix.py tests/unit/test_p2_dynamodb_ledger.py tests/unit/test_demo_surface.py tests/integration/test_p4_demo_runtime.py tests/unit/test_p2_infrastructure.py tests/integration/test_p2_lambda_runtime.py -q
```

Result: **75 passed** (timeout fencing, schema clip, demo honesty, IAM/least-privilege assertions in the infrastructure suite).
