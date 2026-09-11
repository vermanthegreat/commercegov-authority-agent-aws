# Devpost / submission copy (final)

## PROJECT TITLE

CommerceGov Authority Agent

## TAGLINE

AI remains probabilistic. Authority does not.

## SHORT DESCRIPTION

CommerceGov Authority Agent is a Strands-powered AWS agent that autonomously
triages authority risk in commerce operations using Amazon Bedrock and
read-only governance context.

The AI assesses. Deterministic controls decide what is allowed. Humans retain
production authority. A separate layer always returns `PROPOSE_ONLY` /
`HUMAN_AUTHORITY_REQUIRED` / `STOP`. The model can recommend. It cannot
authorize production.

## PROBLEM

Operators cannot scale-review every production change from humans, apps,
automations, and AI agents. The AWS agent gathers bounded context and performs
judgment-heavy authority triage, then surfaces a human decision. It does not
eliminate human review.

## SOLUTION

Keep judgment in the model and permission in deterministic application code.
The AWS agent reads, assesses, explains, and stops. Humans remediate in
CommerceGov. Being able to call Bedrock is not a grant to mutate Shopify.

## HOW IT WORKS

Operational event → API Gateway → Lambda → Strands/Bedrock (one structured
call) with two cached read-only tools (governance context, effective policy) →
deterministic authority floor → DynamoDB evidence. Replay of the same event
returns the original decision without a second model call.

## WHAT THE AGENT DOES AUTONOMOUSLY

- Accept a tenant-bound operational event
- Read product and policy context
- Produce a structured Bedrock assessment
- Persist evidence
- Stop autonomous processing

## WHAT REMAINS HUMAN AUTHORITY

Approval, Apply, Shopify writeback, and any production mutation. Authority
mode is `PROPOSE_ONLY`. Human authority is required.

## AWS SERVICES USED

AWS Lambda, Amazon API Gateway (HTTP API), Amazon DynamoDB, AWS IAM, AWS
Secrets Manager, Amazon CloudWatch, Amazon Bedrock. Strands Agents SDK 1.54.0.
Not used: Amazon Bedrock AgentCore.

## HOW STRANDS IS USED

Strands `Agent` + native `BedrockModel` (`global.anthropic.claude-sonnet-4-6`).
One structured semantic assessment per new event. Tools:
`get_governance_context`, `get_effective_policy`. Extra authority fields in
model output are rejected.

## TECHNICAL IMPLEMENTATION

Python 3.13 Lambda, HTTP API `40k4yk7gh2` stage `p2`, table
`commercegov-authority-agent-p2`, timeouts 29s / 26s / 30s HTTP API. Source
freeze `18107a9`. Deployed build `p4c-so-clip-summary` (not redeployed after
the freeze commit). Proven run `judge-demo-v1-20260911-2030`.

## SAFETY / AUTHORITY MODEL

Bedrock is advisory intelligence. Deterministic code classifies this
external-change class as `AUTHORITY_AT_RISK` and stops. Provider errors fail
closed and display PROVIDER ERROR, never as model success. No
proposals:write, Approve, Apply, or Shopify client.

Live contrast (intentional): model `NO_ACTION_REQUIRED`; authority
`AUTHORITY_AT_RISK` / `STOP`.

## ORIGINALITY

Hackathon-built: this AWS authority-agent runtime, Strands/Bedrock triage,
deployment, evidence path, and demo. Pre-existing: CommerceGov governance
control plane, Shopify integration, policy, Review / approve / Apply,
operational events.

## POTENTIAL IMPACT

Operators keep production authority while still using a model for
judgment-heavy triage. The pattern generalizes: probabilistic intelligence
behind a fail-closed floor.

## DEMO INSTRUCTIONS

1. Open https://40k4yk7gh2.execute-api.us-east-1.amazonaws.com/p2/demo
2. Click **Run Authority Assessment** once; wait for COMPLETED.
3. Note Bedrock `NO_ACTION_REQUIRED` vs authority `AUTHORITY_AT_RISK` / STOP.
4. Click once more: cached idempotent replay; no second Bedrock call.
5. Spoken script: `docs/submission/video-script.md`.

Proven recording event: `judge-demo-v1-20260911-2030`.

## PRE-EXISTING TECHNOLOGY DISCLOSURE

CommerceGov’s governance/control-plane foundation existed before the
hackathon (policy, human Review, approval, Apply, Shopify writeback,
https://app.commercegov.io).

The AWS Authority Agent, its Strands/Bedrock authority-triage implementation,
AWS deployment, evidence path, and submission-specific integration were built
for the hackathon.

No AgentCore. No AWS Shopify writes. No AWS Approve/Apply.
