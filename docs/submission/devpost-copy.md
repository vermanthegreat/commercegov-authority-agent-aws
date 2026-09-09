# Devpost / submission copy

AWS Agents for Humans framing. CommerceGov is pre-existing infrastructure, not
the hackathon deliverable.

## PROJECT NAME

CommerceGov Authority Agent

## TAGLINE

Capability is not authority: a Strands/Bedrock agent that assesses production
risk and cannot grant itself the right to write.

## INSPIRATION

Agents are getting better at tools and models. Production commerce still needs
a hard line between *being able to call an API* and *having authority to change
a live catalog*. We wanted an AWS agent that can reason about that line without
quietly becoming the writer.

## WHAT IT DOES

The agent accepts a tenant-bound CommerceGov operational event, reads bounded
product/policy context, asks Amazon Bedrock (via Strands) for an advisory
classification, then applies a deterministic floor: `AUTHORITY_AT_RISK`,
`HUMAN_AUTHORITY_REQUIRED`, `PROPOSE_ONLY`, `STOP`. Evidence is stored in
DynamoDB. CommerceGov — a separate system — owns Review, approval, Apply, and
Shopify writeback. The agent does not approve, Apply, or write Shopify.

## HOW WE BUILT IT

P0 is a deterministic authority kernel. P1 adds Strands 1.54.0 structured
output on `global.anthropic.claude-sonnet-4-6` with two cached read-only
context tools. P2–P4 host that kernel on Lambda + HTTP API + DynamoDB
idempotency/evidence, CommerceGov operational ingress, optional live read-only
context/OAuth refresh, and a bounded public demo. CommerceGov’s authority
kernel remains in its own repository
(`5390ea66d5286284fa1fc1f021920530c786bf69`). This runtime is
`8ce11a1f18984743c8a11f9ad098a03c8448aabc` (`p4c-8ce11a1`).

## AWS TECHNOLOGIES USED

- AWS Lambda
- Amazon API Gateway (HTTP API)
- Amazon DynamoDB
- AWS IAM
- AWS Secrets Manager
- Amazon CloudWatch
- Amazon Bedrock (Anthropic Claude Sonnet 4.6 via Strands)

## CHALLENGES

Keeping Bedrock strictly advisory: extra authority/Apply fields are rejected,
and provider failures still fail closed to human-required STOP. Proving a live
external TITLE change without letting the agent write production. Not claiming
CommerceGov’s pre-existing governance platform as hackathon-created AWS work.

## ACCOMPLISHMENTS

A hosted agent that assessed live EVENT#2 (`DcaINiQzIAMEbhA=`) as
`AUTHORITY_AT_RISK` / `PROPOSE_ONLY` and stopped. CommerceGov opened human
Review (`external-remediation:2`) and stayed in `review`. No AWS production
write, no automatic remediation, no new Apply. The model reasoned. It did not
grant itself authority.

## WHAT WE LEARNED

Reasoning quality and authority are different planes. Durable evidence and
idempotent EVENT# items matter as much as the model call. A human Review is a
gate, not an Apply.

## WHAT'S NEXT

Keep the AWS agent advisory. Any later production mutation remains a
CommerceGov Apply with human approval, exact-scope authority, and verified
writeback — never a Bedrock grant.
