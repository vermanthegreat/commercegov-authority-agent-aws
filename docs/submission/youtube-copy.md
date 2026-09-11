# YouTube packaging (do not publish from this task)

## TITLE

CommerceGov Authority Agent — AI Remains Probabilistic. Authority Does Not.

## TITLE CARD

Model: NO_ACTION_REQUIRED. Authority: STOP.

## DESCRIPTION

AWS Agents for Humans Hackathon 2026.

CommerceGov Authority Agent is a Strands Agents + Amazon Bedrock service on
AWS Lambda. It reads live CommerceGov product and policy context with two
read-only tools, returns one structured advisory assessment, then a
deterministic layer forces PROPOSE_ONLY / HUMAN_AUTHORITY_REQUIRED / STOP.

In the proven run (event judge-demo-v1-20260911-2030), Bedrock classified
NO_ACTION_REQUIRED. Deterministic authority still required a human and stopped
autonomous processing. That contrast is intentional. The AWS agent does not
approve, apply, or write Shopify.

Public demo:
https://40k4yk7gh2.execute-api.us-east-1.amazonaws.com/p2/demo

Source:
https://github.com/vermanthegreat/commercegov-authority-agent-aws

Not used: Amazon Bedrock AgentCore. No production writes from this agent.
