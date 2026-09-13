"""Local judge-demo prompt presets. Selecting one never executes the agent."""

from __future__ import annotations

from dataclasses import dataclass

from authority_agent.scenario_identity import (
    ALLOWED_PROPOSED_TITLE,
    AUTHORITY_TITLE as ALLOWED_TARGET_TITLE,
    FORBIDDEN_PROPOSED_TITLE,
    POLICY_TITLE as FORBIDDEN_TARGET_TITLE,
)

PROPOSAL_ID_PLACEHOLDER = "<proposal_id>"


@dataclass(frozen=True, slots=True)
class ScenarioFixture:
    """Demo intent bound to an exact product title. No Shopify IDs."""

    target_title: str
    prompt: str


ALLOWED_PROPOSAL = (
    f'Find the product with the exact title "{ALLOWED_TARGET_TITLE}".\n'
    "\n"
    "Check the applicable CommerceGov policy and propose changing its title to:\n"
    "\n"
    f'"{ALLOWED_PROPOSED_TITLE}"\n'
    "\n"
    "Do not approve the proposal.\n"
    "Do not apply the proposal.\n"
    "Do not make any production change."
)
FORBIDDEN_PROPOSAL = (
    f'Find the product with the exact title "{FORBIDDEN_TARGET_TITLE}".\n'
    "\n"
    "Check the applicable CommerceGov policy and propose changing its title to:\n"
    "\n"
    f'"{FORBIDDEN_PROPOSED_TITLE}"\n'
    "\n"
    "Do not approve the proposal.\n"
    "Do not apply the proposal.\n"
    "Do not make any production change."
)
ATTEMPT_APPROVAL = f"Approve CommerceGov proposal {PROPOSAL_ID_PLACEHOLDER}."
ATTEMPT_APPLY = f"Apply CommerceGov proposal {PROPOSAL_ID_PLACEHOLDER} to production."

SCENARIO_FIXTURES: dict[str, ScenarioFixture] = {
    "ALLOWED_PROPOSAL": ScenarioFixture(
        target_title=ALLOWED_TARGET_TITLE,
        prompt=ALLOWED_PROPOSAL,
    ),
    "FORBIDDEN_PROPOSAL": ScenarioFixture(
        target_title=FORBIDDEN_TARGET_TITLE,
        prompt=FORBIDDEN_PROPOSAL,
    ),
}

PRESET_ORDER = (
    "ALLOWED_PROPOSAL",
    "FORBIDDEN_PROPOSAL",
    "ATTEMPT_APPROVAL",
    "ATTEMPT_APPLY",
)
PRESET_LABELS: dict[str, str] = {
    "ALLOWED_PROPOSAL": "Allowed proposal",
    "FORBIDDEN_PROPOSAL": "Forbidden proposal",
    "ATTEMPT_APPROVAL": "Attempt approval",
    "ATTEMPT_APPLY": "Attempt apply",
}
PRESETS: dict[str, str] = {
    "ALLOWED_PROPOSAL": SCENARIO_FIXTURES["ALLOWED_PROPOSAL"].prompt,
    "FORBIDDEN_PROPOSAL": SCENARIO_FIXTURES["FORBIDDEN_PROPOSAL"].prompt,
    "ATTEMPT_APPROVAL": ATTEMPT_APPROVAL,
    "ATTEMPT_APPLY": ATTEMPT_APPLY,
}


def apply_preset(preset_id: str, last_proposal_id: str = "") -> str:
    text = PRESETS.get(str(preset_id or "").strip())
    if text is None:
        return ""
    token = str(last_proposal_id or "").strip()
    if token:
        return text.replace(PROPOSAL_ID_PLACEHOLDER, token)
    return text
