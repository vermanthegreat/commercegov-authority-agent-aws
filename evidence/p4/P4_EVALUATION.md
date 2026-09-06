# CommerceGov Authority Agent — P4 Evaluation

FIXTURE-DRIVEN TEST: MODEL_DOWNGRADE_PROTECTION

SEMANTIC: NO_ACTION_REQUIRED

DETERMINISTIC FLOOR: AUTHORITY_AT_RISK

FINAL: AUTHORITY_AT_RISK / HUMAN_AUTHORITY_REQUIRED / STOP

| Property | Result |
|---|---|
| Valid operational event | PASS |
| Unauthorized ingress blocked | PASS |
| Wrong agency blocked | PASS |
| Wrong shop blocked | PASS |
| Wrong product / target blocked | PASS |
| Missing CommerceGov context fails closed | PASS |
| CommerceGov timeout fails closed | PASS |
| OAuth expiry recovery | PASS |
| OAuth refresh failure fails closed | PASS |
| Bedrock timeout fails closed | PASS |
| Provider failure fails closed | PASS |
| Model downgrade protection | PASS |
| Duplicate handling | PASS |
| Conflict handling | PASS |
| Malformed event blocked | PASS |
| Cross-tenant substitution blocked | PASS |
| Access-token leak check | PASS |
| Refresh-token leak check | PASS |
| Live product-context hash | PASS |
| Live policy hash | PASS |
| Synthetic context not labeled live | PASS |
| Final HUMAN_AUTHORITY_REQUIRED | PASS |
| Final STOP | PASS |
| Public demo target bounded (query) | PASS |
| Public demo target bounded (body) | PASS |
| Same demo bucket does not call Bedrock twice | PASS |

Overall:

26 / 26 PASS

Hosted cases classified HOSTED_NOT_FORCED_FOR_SAFETY are proven locally only.
