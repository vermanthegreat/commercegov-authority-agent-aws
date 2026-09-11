# Builder.aws article outlines

Each piece uses only the live `p4c-so-clip-summary` implementation. Do not claim
AgentCore, Shopify writes, Approve, or Apply.

## 1. Agents for Humans: Why AI Can Reason Without Holding Production Authority

- Hook: models classify risk; catalogs still need a human authority lifecycle.
- Problem: treating tool-calling agents as writers collapses “can call Bedrock”
  into “may change Shopify.”
- Live contrast: Bedrock returned `NO_ACTION_REQUIRED`; application code still
  returned `AUTHORITY_AT_RISK` / `HUMAN_AUTHORITY_REQUIRED` / `STOP`.
- Why that is the product: the model is advisory; deterministic policy owns
  production continuation.
- What we did not build: AgentCore, proposal authoring, auto-Apply.
- Close: AI remains probabilistic. Authority does not.

## 2. Agents for Humans: Building a Read-Only Strands Agent for Commerce Authority Triage

- Architecture: HTTP API → Lambda → Strands 1.54.0 + Bedrock Sonnet 4.6.
- Read-only CommerceGov tools: `get_governance_context`, `get_effective_policy`.
- Structured output: one Bedrock invocation, `SemanticAssessmentSchema`, extra
  authority fields forbidden.
- Evidence: DynamoDB ledger, processing-status fence, idempotent EVENT# replay.
- Hosted proof: product/policy SUCCEEDED, semantic COMPLETED, replay 14 ms with
  no second model call.
- Failure honesty: timeout and schema errors still STOP and show PROVIDER ERROR.
- Close: judgment-heavy triage is autonomous; permission is not.

## 3. Agents for Humans: AI Remains Probabilistic. Authority Does Not.

- Demo walkthrough of `/p2/demo` event `judge-demo-v1-20260911-2030`.
- Intelligence layer vs authority layer on one page.
- Quote the mismatch as the teaching moment, not a bug.
- Human impact: operators keep the gate; agents do not quietly write production.
- Originality boundary: CommerceGov is pre-existing; this AWS agent is the
  advisory runtime.
- Call to action for builders: put models behind fail-closed floors, not the
  other way around.
