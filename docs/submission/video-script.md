# Final 2-minute spoken script (~115 seconds)

Do not say the agent approves, applies, or writes Shopify.
Do not open secrets, CloudWatch raw payloads, or account IDs.

---

AI agents are probabilistic. Production authority cannot be.

CommerceGov Authority Agent uses Strands and Amazon Bedrock to autonomously
triage authority risk, while deterministic controls remain outside the model.

A commerce operational event enters AWS through API Gateway into Lambda.
Strands reads live CommerceGov product and policy context with two read-only
tools, then asks Claude Sonnet 4.6 for one structured assessment.

On the public demo, product read succeeded. Policy read succeeded. Semantic
status is completed.

Bedrock classifies this event as NO_ACTION_REQUIRED.
But that recommendation is advisory.
The deterministic authority layer classifies the event as AUTHORITY_AT_RISK,
requires human authority, and stops autonomous processing.

The model can recommend. It cannot authorize production.

Every assessment is written to a DynamoDB evidence ledger. Replaying the same
event returns the original decision. It does not call Bedrock again.

AI remains probabilistic. Authority does not.

---

Timing guide: problem 15s, architecture 20s, live reads 15s, Bedrock 20s,
boundary 20s, evidence/replay 15s, close 10s.
