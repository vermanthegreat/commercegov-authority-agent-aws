from __future__ import annotations

from authority_agent.demo_surface import render_result
from authority_agent.evidence_view import SUMMARY_MAX_CHARS, bound_semantic_summary, project_assessment_evidence
from conftest import make_processor


def _body(**changes):
    payload = {
        "event_id": "judge-demo-v1-20260906-1200",
        "shop_id": "controlled-demo.myshopify.com",
        "target_id": "7887756099661",
        "mutation_class": "product.title",
        "intelligence_classification": "AUTHORITY_AT_RISK",
        "status": "HUMAN_AUTHORITY_REQUIRED",
        "summary": "Deterministic floor summary",
    }
    payload.update(changes)
    return payload


def test_projects_only_supported_public_fields() -> None:
    view = project_assessment_evidence(
        body=_body(),
        cached=False,
        ledger_evidence={
            "context_source": "live_commercegov",
            "read_status": "ok",
            "product_context_hash": "sha256:" + ("a" * 64),
            "policy_hash": "sha256:" + ("b" * 64),
            "semantic_provider": "StrandsSemanticProvider",
            "semantic_model": "global.anthropic.claude-sonnet-4-6",
            "semantic_status": "valid",
            "semantic_classification": "NO_ACTION_REQUIRED",
            "semantic_summary": "Model says no action.",
            "deterministic_classification": "AUTHORITY_AT_RISK",
            "autonomous_processing": "STOP",
            "terminal_status": "HUMAN_AUTHORITY_REQUIRED",
            "completed_at": "2026-09-06T12:00:00Z",
            "access_token": "must-not-project",
            "unknown_internal_field": "noise",
            "SecretString": "nope",
        },
        evidence_id="evidence:abc",
        execution_id="exec-1",
        product_title="Gift Card",
    )
    assert view["schema_version"] == "AuthorityAssessmentEvidenceV1"
    assert view["event"]["source"] == "judge_demo_fixture"
    assert view["execution"]["source"] == "live_assessment"
    assert view["execution"]["recorded_at"] == "2026-09-06T12:00:00Z"
    assert view["live_context"]["source"] == "live_commercegov"
    assert view["live_context"]["product_context_hash"].startswith("sha256:aaaaaaaaaaaa")
    assert view["semantic"]["provider"] == "Strands"
    assert view["semantic"]["classification"] == "NO_ACTION_REQUIRED"
    assert view["authority"]["classification"] == "AUTHORITY_AT_RISK"
    encoded = str(view)
    assert "must-not-project" not in encoded
    assert "unknown_internal_field" not in encoded
    assert "SecretString" not in encoded
    assert "noise" not in encoded
    assert view["evidence"]["evidence_id"] == "evidence:abc"


def test_unknown_fields_and_secrets_are_ignored() -> None:
    view = project_assessment_evidence(
        body=_body(),
        cached=True,
        ledger_evidence={
            "refresh_token": "cgrfr_secret",
            "Authorization": "Bearer inbound",
            "arn:aws:secretsmanager": "arn:aws:secretsmanager:us-east-1:1:secret:x",
        },
    )
    assert view["execution"]["source"] == "cached_idempotent_replay"
    assert "live_context" not in view
    blob = str(view)
    assert "cgrfr_secret" not in blob
    assert "Bearer inbound" not in blob
    assert "secretsmanager" not in blob


def test_bound_summary_escapes_via_html_and_truncates() -> None:
    long_text = "risk " * 200
    bounded = bound_semantic_summary(long_text)
    assert bounded is not None
    assert bounded.endswith("[truncated]")
    assert len(bounded) <= SUMMARY_MAX_CHARS + len(" [truncated]")
    assert bound_semantic_summary("token access_token leaked") == "[redacted]"
    processor, _provider = make_processor({})
    processor.last_evidence = {
        "semantic_status": "valid",
        "semantic_classification": "REVIEW_REQUIRED",
        "semantic_summary": "<script>alert(1)</script> review the title change.",
    }
    html = render_result(body=_body(), cached=False, processor=processor)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_does_not_rewrite_semantic_classification() -> None:
    view = project_assessment_evidence(
        body=_body(),
        cached=False,
        ledger_evidence={
            "semantic_status": "valid",
            "semantic_classification": "NO_ACTION_REQUIRED",
            "semantic_summary": "Looks harmless.",
            "deterministic_classification": "AUTHORITY_AT_RISK",
        },
    )
    assert view["semantic"]["classification"] == "NO_ACTION_REQUIRED"
    assert view["authority"]["classification"] == "AUTHORITY_AT_RISK"


def test_kernel_summary_is_not_fabricated_as_model_assessment() -> None:
    view = project_assessment_evidence(body=_body(), cached=False, ledger_evidence={"semantic_status": "provider_error"})
    assert view["semantic"]["status"] == "provider_error"
    assert "summary" not in view["semantic"]
