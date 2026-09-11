# Final spoken script (~118 seconds)

Record from this text. Short sentences. Pause where marked.

Do not name AgentCore. Do not say the agent approves, applies, or writes Shopify.
Primary evidence is event `judge-demo-v1-20260911-2030` only.

---

AI agents are probabilistic. Production authority cannot be.

[pause 0.7s]

CommerceGov Authority Agent uses Strands and Amazon Bedrock to autonomously
triage authority risk, while deterministic production authority remains
outside the model.

[pause 0.5s]

A commerce event enters AWS through API Gateway, into Lambda.
Strands Agents reads live product and policy context with two read-only tools.
Amazon Bedrock then returns one structured assessment.

[pause 0.5s]

Product read succeeded. Policy read succeeded.
Semantic status: completed.

[pause 0.5s]

Bedrock classifies this event as NO_ACTION_REQUIRED.
Its recommended operator action is COMPARE_WITH_GOVERNED_VALUE.

[pause 0.8s]

But that result is advisory.

[pause 0.8s]

The deterministic authority layer classifies the event as AUTHORITY_AT_RISK,
requires human authority, and stops autonomous processing.

This is intentional. The model can reason. It cannot authorize production.
The AWS agent does not approve, apply, or write Shopify.
Humans keep consequential production authority.

[pause 0.5s]

The decision is stored as durable evidence.
Replaying the same event returns the original decision. Bedrock is not called again.

[pause 0.5s]

AI remains probabilistic. Authority does not.

---

Pace: ~145 words. Hold the NO_ACTION_REQUIRED → HUMAN_AUTHORITY_REQUIRED cut.
