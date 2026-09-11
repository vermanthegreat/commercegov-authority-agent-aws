# Devpost / submission copy

AWS Agents for Humans. CommerceGov is pre-existing infrastructure, not the
hackathon deliverable. Do not claim AgentCore, Shopify writes, Approve, or Apply.

## PROJECT NAME

CommerceGov Authority Agent

## TAGLINE

AI remains probabilistic. Authority does not.

## PROJECT DESCRIPTION

A hosted AWS Lambda agent uses Strands and Amazon Bedrock to triage
commerce-authority risk from a live CommerceGov read, then a deterministic
control plane forces `PROPOSE_ONLY` / `HUMAN_AUTHORITY_REQUIRED` / `STOP`.
The model can recommend. It cannot authorize production.

## PROBLEM

AI agents are probabilistic. Production catalog authority cannot be. Tool use
and a good Bedrock answer are not a grant to mutate Shopify.

## HOW IT WORKS

A Commerce operational event hits API Gateway → Lambda. Strands invokes Claude
Sonnet 4.6 once for structured advisory output while two read-only tools supply
governance context and effective policy. Application code then applies a
fail-closed authority floor and writes an idempotent DynamoDB evidence record.
Replay returns the original decision without a second model call.

## AWS SERVICES USED

AWS Lambda, Amazon API Gateway (HTTP API), Amazon DynamoDB, AWS IAM, AWS
Secrets Manager, Amazon CloudWatch, Amazon Bedrock (via Strands Agents SDK
1.54.0). Not used: Amazon Bedrock AgentCore.

## STRANDS USAGE

Strands 1.54.0 `Agent` + native `BedrockModel`. One structured semantic
assessment per new event. Tools: `get_governance_context`,
`get_effective_policy` only. Extra authority/Apply fields in model output are
rejected.

## HUMAN IMPACT

Operators keep production authority. The agent does judgment-heavy triage
autonomously and stops. Humans remediate in CommerceGov. Shoppers are not
exposed to an unsupervised catalog write from this agent.

## ORIGINALITY

New for this hackathon: the AWS authority-agent runtime, event adapter,
deterministic floor, Strands structured-output path, DynamoDB evidence, and
public demo. Pre-existing: CommerceGov, Shopify integration, policy, Review /
approve / Apply, operational events. No pre-existing CommerceGov work is
claimed as hackathon-created.

## TECHNICAL IMPLEMENTATION

Python 3.13 Lambda, HTTP API stage `p2`, table `commercegov-authority-agent-p2`,
model `global.anthropic.claude-sonnet-4-6`, timeouts 29s / 26s / 30s HTTP API.
Live build `p4c-so-clip-summary`. Proven run `judge-demo-v1-20260911-2030`.

## AUTHORITY / SAFETY MODEL

Bedrock is advisory. Deterministic code always returns `AUTHORITY_AT_RISK` for
this external-change class, `PROPOSE_ONLY`, `HUMAN_AUTHORITY_REQUIRED`, `STOP`.
Provider errors fail closed to the same floor and are labeled PROVIDER ERROR,
never as model success. No proposals:write, Approve, Apply, or Shopify client.

## DEMO INSTRUCTIONS

Open https://40k4yk7gh2.execute-api.us-east-1.amazonaws.com/p2/demo  
Click **Run Authority Assessment** once. Wait for COMPLETED. Note model
`NO_ACTION_REQUIRED` versus authority `AUTHORITY_AT_RISK` / STOP. Click once
more: cached idempotent replay, no second Bedrock call. Spoken script:
`docs/submission/demo-narrative.md`.

## PRE-EXISTING COMMERCEGOV DISCLOSURE

CommerceGov (https://app.commercegov.io) already owned governance, policy,
human Review, approval, Apply, and Shopify writeback. This repository is the
AWS agent that reasons about authority risk without possessing production
authority.

## INSPIRATION

Agents got better at tools. Production still needed a hard line between
calling Bedrock and changing a live catalog.

## CHALLENGES

Keeping Bedrock strictly advisory under HTTP API’s 30s cap; proving live
CommerceGov reads without adding write scopes; failing closed when structured
output was long or the provider timed out.

## ACCOMPLISHMENTS

Live COMPLETED structured Bedrock on `judge-demo-v1-20260911-2030` with
read-only CommerceGov context, then a deterministic STOP even though the model
said `NO_ACTION_REQUIRED`. Idempotent replay in 14 ms. Honest PROVIDER ERROR
on earlier failures.

## WHAT WE LEARNED

Reasoning quality and authority are different planes. A model “all clear” is
still not a production grant.

## WHAT'S NEXT

Keep the AWS agent advisory. Any later mutation remains a CommerceGov Apply
with a human — never a Bedrock grant.
