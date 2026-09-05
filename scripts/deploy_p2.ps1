param(
    [string]$StackName = "commercegov-authority-agent-aws-p2",
    [string]$Region = "us-east-1",
    [string]$BuildId = "p2-candidate"
)

$ErrorActionPreference = "Stop"
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$localSam = Join-Path $projectRoot ".tools\sam\Scripts\sam.exe"
if (Test-Path -LiteralPath $localSam) {
    $samExe = $localSam
} else {
    $samExe = (Get-Command sam -ErrorAction Stop).Source
}
& (Join-Path $PSScriptRoot "build_lambda.ps1")
if ($LASTEXITCODE -ne 0) { throw "Build failed" }

& $samExe validate --template-file (Join-Path $projectRoot "template.yaml") --region $Region --lint
if ($LASTEXITCODE -ne 0) { throw "SAM validation failed" }
& $samExe deploy `
    --template-file (Join-Path $projectRoot "template.yaml") `
    --stack-name $StackName `
    --region $Region `
    --resolve-s3 `
    --capabilities CAPABILITY_NAMED_IAM `
    --no-confirm-changeset `
    --no-fail-on-empty-changeset `
    --parameter-overrides "RuntimeBuildId=$BuildId"
if ($LASTEXITCODE -ne 0) { throw "SAM deployment failed" }

aws cloudformation describe-stacks --stack-name $StackName --region $Region `
    --query "Stacks[0].Outputs" --output table
