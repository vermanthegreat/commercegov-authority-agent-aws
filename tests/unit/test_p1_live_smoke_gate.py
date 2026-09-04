from __future__ import annotations

from authority_agent.live_bedrock_smoke import main


def test_live_bedrock_smoke_requires_explicit_opt_in(monkeypatch, capsys) -> None:
    monkeypatch.delenv("RUN_BEDROCK_LIVE_SMOKE", raising=False)
    assert main() == 2
    assert capsys.readouterr().out.startswith("BEDROCK_LIVE_SMOKE: BLOCKED")
