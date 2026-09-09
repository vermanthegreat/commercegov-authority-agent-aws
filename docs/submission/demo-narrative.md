# Judge demo narrative (~60–90 seconds)

Spoken sequence. AWS never writes Shopify. CommerceGov never auto-Applies.

1. **Baseline.** A governed product TITLE already has a verified CommerceGov
   production baseline (`The Draft Snowboard`). Capability is not authority:
   only CommerceGov Apply may write Shopify.

2. **External change.** Shopify TITLE is changed outside CommerceGov to
   `The Draft Snowboard — External Change`.

3. **Exact-scope observation.** CommerceGov records external event `2` on the
   exact TITLE scope for `controlled-demo.myshopify.com`.

4. **AWS ingress.** The operational event reaches
   `POST /events/operational` (request `DcaINiQzIAMEbhA=`).

5. **Advisory reasoning.** Strands + Bedrock
   (`global.anthropic.claude-sonnet-4-6`) classify authority risk. The model
   recommends; it cannot approve.

6. **Deterministic floor.** Application code returns `AUTHORITY_AT_RISK`.
   Provider error still fails closed to human-required STOP.

7. **Stop.** Authority mode stays `PROPOSE_ONLY`. Terminal result:
   `HUMAN_AUTHORITY_REQUIRED` / `REVIEW_EXTERNAL_CHANGE`. DynamoDB stores
   `EVENT#2` evidence. No production write.

8. **Human Review.** CommerceGov opens cycle `external-remediation:2` and
   remains in `review`. That is a human gate, not an Apply.

9. **Close.** No AWS Shopify write. No automatic CommerceGov remediation. No
   new Apply. The agent reasoned. It did not grant itself authority.

Public fixture (not EVENT#2 itself):
https://40k4yk7gh2.execute-api.us-east-1.amazonaws.com/p2/demo

Evidence: `docs/submission/aws-event-2-evidence.md`.
