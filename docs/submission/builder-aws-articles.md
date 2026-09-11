# Builder.aws article drafts

Live evidence only. Do not invent AgentCore, Shopify writes, Approve, or Apply.

## 1. Agents for Humans: Why AI Can Reason Without Holding Production Authority

**Thesis:** A model can classify authority risk. It must not become the writer.

**Sections**

1. The category error — capability vs authority.
2. Live mismatch — Bedrock `NO_ACTION_REQUIRED` vs deterministic `AUTHORITY_AT_RISK` / `STOP` on `judge-demo-v1-20260911-2030`.
3. Why the mismatch is the product — advisory intelligence vs fail-closed policy.
4. What stays human — Review, approve, Apply, Shopify writeback in CommerceGov.
5. What we refused — AgentCore, proposal authoring, auto-Apply.

**Evidence to show:** demo URL, COMPLETED semantic status, evidence ID
`evidence:2cc43b64-7396-426d-9595-ed2c97ed8ea9`, replay 14 ms.

**Code/architecture:** `docs/submission/architecture.md` planes; quote
`PROPOSE_ONLY` / `HUMAN_AUTHORITY_REQUIRED` / `STOP` from deterministic control.

**Ending:** AI remains probabilistic. Authority does not.

**Avoid:** “the AI decided production,” “autonomous remediation,” AgentCore.

## 2. Agents for Humans: Building a Read-Only Strands Agent for Commerce Authority Triage

**Thesis:** Host a Strands agent on Lambda that can think about commerce
governance without write tools.

**Sections**

1. HTTP API → Lambda → Strands 1.54.0 + Bedrock Sonnet 4.6.
2. Two tools only: `get_governance_context`, `get_effective_policy`.
3. One structured invocation; `SemanticAssessmentSchema` forbids extra authority fields.
4. DynamoDB EVENT# ledger, PROCESSING fence, idempotent replay.
5. Hosted timeouts (29/26/30) and honest PROVIDER ERROR.
6. Least privilege: no Shopify, no Approve/Apply IAM.

**Evidence:** product/policy SUCCEEDED; `p4c-so-clip-summary`; 75 focused tests.

**Code:** `strands_provider.py` system instruction; tool registry in
`semantic_context.py`; template IAM notes in README P2 section.

**Ending:** Judgment-heavy triage can be autonomous. Permission cannot.

**Avoid:** claiming the tools fetch arbitrary HTTP; claiming a second format call.

## 3. Agents for Humans: AI Remains Probabilistic. Authority Does Not.

**Thesis:** The demo’s teaching moment is disagreement between model and floor.

**Sections**

1. Open on the sentence.
2. Walk `/p2/demo` shots 4–8 (reads, COMPLETED, NO_ACTION_REQUIRED, STOP, evidence, replay).
3. Explain advisory vs authorization.
4. Originality boundary — CommerceGov pre-existed; this AWS agent is new.
5. Invitation to builders — put models behind floors.

**Evidence:** video-script.md; freeze-manifest.md; claim-audit.md.

**Code:** none required; architecture ASCII is enough.

**Ending:** Repeat the thesis. Do not apologize for the model’s NO_ACTION_REQUIRED.

**Avoid:** “the model was wrong so we overrode it” as a bug story. It is policy.
