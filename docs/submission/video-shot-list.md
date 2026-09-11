# Shot-by-shot recording plan (~118 seconds)

**Do not POST `/demo/run` on the live site.** Event 2030’s five-minute bucket has
expired; a live click would create a new event. Use local captures in
`docs/submission/recording/`. Never use event `2055`.

Recommended operator action `COMPARE_WITH_GOVERNED_VALUE` is proven in the
ledger; the public HTML labels model class as **Assessment**. Narrate the
recommendation while Assessment shows `NO_ACTION_REQUIRED`.

---

### SHOT 1 — 0:00–0:12 — Title / architecture

- **Screen:** `docs/submission/architecture.md` ASCII diagram, zoomed so the
  Strands + Bedrock split and STOP are readable. Optional title card:
  “CommerceGov Authority Agent — AI Remains Probabilistic. Authority Does Not.”
- **Action:** No click. Hold.
- **Narration:** “AI agents are probabilistic. Production authority cannot be.
  CommerceGov Authority Agent uses Strands and Amazon Bedrock to autonomously
  triage authority risk, while deterministic production authority remains
  outside the model.”
- **Cursor:** Off or parked in a corner.
- **Must see:** API Gateway → Lambda → Strands Agent + Amazon Bedrock;
  read-only context/policy; PROPOSE_ONLY / HUMAN_AUTHORITY_REQUIRED / STOP.
- **Must not see:** AWS account IDs, ARNs, AgentCore logos, Shopify admin.

### SHOT 2 — 0:12–0:28 — Public demo landing

- **Screen:** `docs/submission/recording/demo-landing.html` (or live **GET**
  only: `https://40k4yk7gh2.execute-api.us-east-1.amazonaws.com/p2/demo`).
- **Action:** Do **not** click Run. Optionally hover the button without clicking.
- **Narration:** “A commerce event enters AWS through API Gateway, into Lambda.
  Strands Agents reads live product and policy context with two read-only tools.
  Amazon Bedrock then returns one structured assessment.”
- **Cursor:** Slow hover on shop / Gift Card / product ID; never click the button.
- **Must see:** URL bar with `/p2/demo`; shop `controlled-demo.myshopify.com`;
  Gift Card `7887756099661`; “AI remains probabilistic. Authority does not.”;
  note that the page cannot approve, apply, or write Shopify.
- **Must not see:** bookmarks bar clutter, other tabs (Shopify admin, control
  plane, Render), `.env`, DevTools.

### SHOT 3 — 0:28–0:43 — Live governed context

- **Screen:** `docs/submission/recording/demo-2030-live.html`, scrolled to
  **Live Governed Context**.
- **Action:** Scroll only. Confirm Event is `judge-demo-v1-20260911-2030`.
- **Narration:** “Product read succeeded. Policy read succeeded.
  Semantic status: completed.”
- **Cursor:** Point at Product read / Policy read.
- **Must see:** Product read SUCCEEDED; Policy read SUCCEEDED; Source LIVE
  COMMERCEGOV; Event `judge-demo-v1-20260911-2030`; Execution LIVE ASSESSMENT.
- **Must not see:** PROVIDER ERROR; event 2055; raw hashes as the focus
  (hashes may remain in frame).

### SHOT 4 — 0:43–1:00 — Strands / Amazon Bedrock

- **Screen:** Same file, **Strands / Amazon Bedrock** section.
- **Action:** Hold. Do not scroll away until after the pause.
- **Narration:** “Bedrock classifies this event as NO_ACTION_REQUIRED.
  Its recommended operator action is COMPARE_WITH_GOVERNED_VALUE.
  [pause] But that result is advisory.”
- **Cursor:** Circle **Assessment: NO_ACTION_REQUIRED** and **Semantic status:
  COMPLETED**.
- **Must see:** Provider Strands Agents SDK; Model Claude Sonnet 4.6; Semantic
  status COMPLETED; Assessment NO_ACTION_REQUIRED; note “advisory intelligence”.
- **Must not see:** PROVIDER ERROR; fallback copy; AgentCore.

### SHOT 5 — 1:00–1:22 — Deterministic authority (hold the contrast)

- **Screen:** Same file, **Deterministic Authority**. Keep shot 4’s Bedrock
  heading visible above if the viewport allows; otherwise cut cleanly to this
  section and hold.
- **Action:** No click. Hold ≥8 seconds on HUMAN_AUTHORITY_REQUIRED / STOPPED.
- **Narration:** “The deterministic authority layer classifies the event as
  AUTHORITY_AT_RISK, requires human authority, and stops autonomous processing.
  This is intentional. The model can reason. It cannot authorize production.
  The AWS agent does not approve, apply, or write Shopify.
  Humans keep consequential production authority.”
- **Cursor:** Point Classification AUTHORITY_AT_RISK, then Human authority
  REQUIRED, then Autonomous processing STOPPED.
- **Must see:** Authority mode PROPOSE_ONLY; Classification AUTHORITY_AT_RISK;
  Human authority REQUIRED; Autonomous processing STOPPED; Terminal
  HUMAN_AUTHORITY_REQUIRED.
- **Must not see:** Approve/Apply controls (none exist); Shopify admin.

### SHOT 6 — 1:22–1:38 — Evidence

- **Screen:** Same file, **Evidence**.
- **Action:** Scroll to Evidence ID.
- **Narration:** “The decision is stored as durable evidence.”
- **Cursor:** Point Evidence ID.
- **Must see:** `evidence:2cc43b64-7396-426d-9595-ed2c97ed8ea9` (execution ID is
  the same UUID without the `evidence:` prefix; say it if needed, it is not a
  separate on-page field).
- **Must not see:** DynamoDB console, other tenant items.

### SHOT 7 — 1:38–1:50 — Idempotent replay

- **Screen:** `docs/submission/recording/demo-2030-replay.html`.
- **Action:** Switch tab/file. Do **not** click Run on live `/demo`.
- **Narration:** “Replaying the same event returns the original decision.
  Bedrock is not called again.”
- **Cursor:** Point Execution `CACHED — IDEMPOTENT REPLAY` and
  “Already assessed — returning the original authority decision.”
- **Must see:** Same Event `judge-demo-v1-20260911-2030`; same Evidence ID;
  COMPLETED still; cache note.
- **Must not see:** LIVE ASSESSMENT on this shot; event 2055.

### SHOT 8 — 1:50–2:00 — Close

- **Screen:** Architecture diagram again, or landing thesis line.
- **Action:** Hold.
- **Narration:** “AI remains probabilistic. Authority does not.”
- **Cursor:** Off.
- **Must see:** Closing thesis.
- **Must not see:** AgentCore, secrets, other products.

---

## Recording quality

- Browser: Chrome, one window, bookmarks bar hidden, sidebar hidden.
- Viewport: 1440×900 or 1280×800; zoom **110–125%** so section headings and
  `NO_ACTION_REQUIRED` / `STOPPED` are readable on a 1080p export.
- Crop: browser content + URL bar only (URL proves public `/p2/demo` on landing).
- Cursor: slow; no frantic circling; hide on title and close shots.
- Full-screen vs crop: cropped browser, not OS desktop.
- Pace: ~145 wpm; 0.5–0.8s pauses as marked; extra 0.8s after
  NO_ACTION_REQUIRED before the authority section.
- Mic: peak around -12 dBFS; no music; no AGC pumping.
- Tabs: close Shopify admin, CommerceGov control plane, terminals, `.env` editors.
