# AWS submission freeze (p4c-so-clip-summary)

Read-only freeze. No secrets. The source commit was **not** redeployed.

## Distinguish source vs live Lambda

| Plane | Identifier |
|---|---|
| **SOURCE FREEZE COMMIT** | `18107a9bf7af50702ee31b91f35eee188eb0e55e` |
| Parent | `6318d7c0bd8dc75b5e007f21a0dd1a4222b031bc` |
| Tree | `0807e60b6df3d2692d4b74fdc0a88d5ac0f5007a` |
| Follow-on documentation commit | `f3254886875c779244f34feaaf01d05a1bd7dfae` |
| **CURRENT DEPLOYED LAMBDA** | `$LATEST` build `p4c-so-clip-summary` |
| Lambda CodeSha256 | `F5H5hEB1x/qw8fCFN/wfSe+hku6McyhhdDSYkBVo62I=` |

The freeze commit records the working tree that was packaged into
`.build/lambda` and deployed as `p4c-so-clip-summary`. Every
`src/authority_agent/*.py` file SHA-256-matched that package at freeze time.
This commit does **not** create a new Lambda version.

## Deployed runtime

| Item | Value |
|---|---|
| CloudFormation stack | `commercegov-authority-agent-aws-p2` (`UPDATE_COMPLETE`) |
| Region | `us-east-1` |
| Lambda | `commercegov-authority-agent-p2` `$LATEST` python3.13 timeout 29s / 1024 MB |
| Semantic timeout | 26s |
| HTTP API | `40k4yk7gh2` stage `p2` |
| Demo URL | https://40k4yk7gh2.execute-api.us-east-1.amazonaws.com/p2/demo |
| DynamoDB table | `commercegov-authority-agent-p2` |
| Strands | `1.54.0` |
| Bedrock model | `global.anthropic.claude-sonnet-4-6` |
| CommerceGov origin | `https://app.commercegov.io` |
| Shop | `controlled-demo.myshopify.com` |
| Agency | `shop_controlled-demo_myshopify_com` |
| Demo product | `7887756099661` |
| Focused tests | 75 passed (structured-output, Strands, observability, Lambda, ledger, demo, IAM, evaluation matrix) |

## Primary proven live run

| Item | Value |
|---|---|
| Event ID | `judge-demo-v1-20260911-2030` |
| API Gateway request ID | `DjSz8hQwIAMESrw=` |
| Lambda request ID | `c1328944-d47e-4854-b62c-22a39e84f156` |
| Execution ID | `2cc43b64-7396-426d-9595-ed2c97ed8ea9` |
| Evidence ID | `evidence:2cc43b64-7396-426d-9595-ed2c97ed8ea9` |
| Semantic status | COMPLETED |
| Provider fallback | NO |
| Replay | `DjS8-hzYIAMESwA=` / no second Bedrock call |
