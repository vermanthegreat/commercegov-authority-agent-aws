# AWS submission freeze (p4c-so-clip-summary)

Read-only freeze of the proven hosted hackathon runtime. No secrets.

This freeze records **what is live**, not git cleanliness. Workspace `main`
HEAD is behind the deployed build: proven Lambda code is uncommitted relative
to `6318d7c`.

## Identifiers

| Item | Value |
|---|---|
| Git HEAD (committed) | `6318d7c0bd8dc75b5e007f21a0dd1a4222b031bc` |
| Git branch | `main` |
| Working tree | **DIRTY** (runtime + tests that match the live build; not in HEAD) |
| Deployed build ID | `p4c-so-clip-summary` |
| CloudFormation stack | `commercegov-authority-agent-aws-p2` |
| Stack status | `UPDATE_COMPLETE` (2026-09-11T20:27:11Z) |
| Region | `us-east-1` |
| Lambda | `commercegov-authority-agent-p2` |
| Lambda version | `$LATEST` |
| Lambda runtime | `python3.13` |
| Lambda timeout | 29s |
| Lambda memory | 1024 MB |
| Lambda last modified | 2026-09-11T20:27:23Z |
| Lambda CodeSha256 | `F5H5hEB1x/qw8fCFN/wfSe+hku6McyhhdDSYkBVo62I=` |
| Semantic timeout | 26s |
| HTTP API | `40k4yk7gh2` stage `p2` |
| Demo URL | https://40k4yk7gh2.execute-api.us-east-1.amazonaws.com/p2/demo |
| DynamoDB table | `commercegov-authority-agent-p2` |
| Strands | `1.54.0` |
| Bedrock model | `global.anthropic.claude-sonnet-4-6` |
| CommerceGov origin | `https://app.commercegov.io` |
| Shop | `controlled-demo.myshopify.com` |
| Agency | `shop_controlled-demo_myshopify_com` |
| Demo product | `7887756099661` (Gift Card) |
| OAuth scopes (unchanged) | `shops:read products:read policy:read` |

## Primary proven live run

| Item | Value |
|---|---|
| Event ID | `judge-demo-v1-20260911-2030` |
| API Gateway request ID | `DjSz8hQwIAMESrw=` |
| Lambda request ID | `c1328944-d47e-4854-b62c-22a39e84f156` |
| Execution ID | `2cc43b64-7396-426d-9595-ed2c97ed8ea9` |
| Evidence ID | `evidence:2cc43b64-7396-426d-9595-ed2c97ed8ea9` |
| Lambda duration | 8686 ms (init 2105 ms) |
| Model duration | 5765 ms |
| Semantic status | `COMPLETED` / `valid` |
| Provider fallback | **NO** |

## Replay

| Item | Value |
|---|---|
| API Gateway request ID | `DjS8-hzYIAMESwA=` |
| Lambda request ID | `9467fe75-7d5c-4eb6-bb50-1e00ac131a5a` |
| Result | `CACHED — IDEMPOTENT REPLAY` |
| Duration | 14 ms |
| Second `semantic_assessment_started` | **NO** |
| Evidence reused | `evidence:2cc43b64-7396-426d-9595-ed2c97ed8ea9` |
