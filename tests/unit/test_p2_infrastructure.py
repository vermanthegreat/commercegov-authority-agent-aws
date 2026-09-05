from __future__ import annotations

from conftest import ROOT


def test_sam_template_defines_only_minimal_authenticated_runtime() -> None:
    template = (ROOT / "template.yaml").read_text(encoding="utf-8")
    assert "AWS::Serverless::HttpApi" in template
    assert "EnableIamAuthorizer: true" in template
    assert "DefaultAuthorizer: AWS_IAM" in template
    assert "AWS::Serverless::Function" in template
    assert "AWS::DynamoDB::Table" in template
    assert "AWS::Logs::LogGroup" in template
    assert "Timeout: 29" in template
    assert "SEMANTIC_TIMEOUT_SECONDS: '24'" in template
    assert "Action: '*'" not in template
    assert "Resource: '*'" not in template
    assert "dynamodb:Scan" not in template
    assert "secretsmanager:GetSecretValue" in template
    assert "secretsmanager:*" not in template
    assert "Path: /events/operational" in template
    assert "Authorizer: NONE" in template
    assert "Path: /assess" in template
    assert "DefaultAuthorizer: AWS_IAM" in template
    assert "bedrock:InvokeModel" in template
    assert "global.anthropic.claude-sonnet-4-6" in template
    assert "proposals:write" not in template


def test_lambda_build_is_linux_x86_64_and_pinned() -> None:
    build_script = (ROOT / "scripts" / "build_lambda.ps1").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements-lambda.txt").read_text(encoding="utf-8")
    assert "manylinux2014_x86_64" in build_script
    assert "--python-version 3.13" in build_script
    assert "strands-agents==1.54.0" in requirements
    assert "pydantic==2.13.4" in requirements
    deploy_script = (ROOT / "scripts" / "deploy_p2.ps1").read_text(encoding="utf-8")
    assert ".tools\\sam\\Scripts\\sam.exe" in deploy_script
