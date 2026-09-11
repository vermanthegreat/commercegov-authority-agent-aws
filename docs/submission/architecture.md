# Reasoning, authority, and execution planes

Submission architecture for the frozen live runtime `p4c-so-clip-summary`.

```text
Commerce operational event
        ↓
AWS API Gateway
        ↓
Lambda
        ↓
Strands Agent + Amazon Bedrock
       ↙                     ↘
CommerceGov governance      Effective policy
context (read-only)         (read-only)
        ↓
probabilistic authority-risk assessment
        ↓
deterministic authority control
        ↓
PROPOSE_ONLY
HUMAN_AUTHORITY_REQUIRED
STOP
        ↓
human remediation
```

Core statement: **AI remains probabilistic. Authority does not.**

Secondary: the agent performs judgment-heavy authority triage autonomously.
Deterministic controls decide what the system is actually allowed to do.

## Planes

```text
REASONING PLANE (this AWS repo)
  event → API Gateway → Lambda
  Strands 1.54.0 + Bedrock (advisory only)
  two cached read-only CommerceGov tools
  deterministic floor
  DynamoDB EVENT# evidence

AUTHORITY PLANE (CommerceGov, separate repo)
  exact-scope decisions, human Review / approve
  no agent self-grant

EXECUTION PLANE (CommerceGov worker, separate repo)
  Apply → Shopify writeback → verified write → audit
```

| Plane | May | Must not |
|---|---|---|
| Reasoning (AWS) | Classify risk, recommend an operator action, persist evidence | Approve, Apply, write Shopify, grant authority |
| Authority (CommerceGov) | Bind exact scope, require a human | Treat Bedrock as approval |
| Execution (CommerceGov worker) | Mutate Shopify only after Apply | Accept AWS/model output as a write grant |

Intentional live contrast (primary demo `judge-demo-v1-20260911-2030`):

- Model: `NO_ACTION_REQUIRED` / `COMPARE_WITH_GOVERNED_VALUE`
- Deterministic authority: `AUTHORITY_AT_RISK` / `HUMAN_AUTHORITY_REQUIRED` / `STOP`

The model's recommendation is advisory. Even when the model believes no action
is required, deterministic policy can still require a human decision.

Certified historical kernel SHA (separate repo):
`5390ea66d5286284fa1fc1f021920530c786bf69`.

Live AWS freeze: `docs/submission/freeze-manifest.md`.
