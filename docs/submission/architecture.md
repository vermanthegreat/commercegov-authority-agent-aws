# Reasoning, authority, and execution planes

CommerceGov owns production authority and controlled execution. This AWS
repository is the agent runtime and advisory assessment wrapper.

```text
REASONING PLANE (this AWS repo)
  Shopify / CommerceGov operational event
          ↓
  AWS adapter / POST /events/operational (or IAM POST /assess, or /demo)
          ↓
  Strands 1.54.0 + Amazon Bedrock  (advisory classification only)
          ↓
  Deterministic authority floor    (AUTHORITY_AT_RISK / STOP)
          ↓
  DynamoDB evidence                (idempotent EVENT# item)

AUTHORITY PLANE (CommerceGov, separate repo)
  exact-scope TITLE decision, human Review / approve
  persisted command identity, no agent self-grant

EXECUTION PLANE (CommerceGov worker, separate repo)
  Apply → outbox → Shopify writeback → durable provider success
  → canonical verification → verified_write → audit
```

Human Review sits on the authority plane after AWS assessment:

```text
Shopify / CommerceGov event
        ↓
AWS adapter / operational API
        ↓
Strands + Bedrock advisory reasoning
        ↓
deterministic authority assessment
        ↓
DynamoDB evidence
        ↓
CommerceGov human Review
```

## What each plane may do

| Plane | May | Must not |
|---|---|---|
| Reasoning (AWS) | Classify risk, recommend `REVIEW_EXTERNAL_CHANGE`, persist evidence | Approve, Apply, write Shopify, grant authority |
| Authority (CommerceGov) | Bind exact scope, require human approval, admit Review | Treat Bedrock output as approval |
| Execution (CommerceGov worker) | Mutate Shopify only after Apply and durable evidence | Accept AWS or model output as a write grant |

**Capability is not authority.** The AWS agent reasons about authority risk but
does not possess production authority. The model can reason. It cannot grant
itself authority.

CommerceGov does not merely stop an agent at a human gate. It governs the
production authority lifecycle before, during, and after the mutation.

Certified SHAs: AWS `8ce11a1f18984743c8a11f9ad098a03c8448aabc` (build
`p4c-8ce11a1`); CommerceGov kernel
`5390ea66d5286284fa1fc1f021920530c786bf69`.
