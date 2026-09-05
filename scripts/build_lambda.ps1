param(
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$buildRoot = [System.IO.Path]::GetFullPath((Join-Path $projectRoot ".build"))
$lambdaRoot = [System.IO.Path]::GetFullPath((Join-Path $buildRoot "lambda"))
if (-not $lambdaRoot.StartsWith($projectRoot + [System.IO.Path]::DirectorySeparatorChar)) {
    throw "Build directory resolved outside the project"
}
if (Test-Path -LiteralPath $lambdaRoot) {
    Remove-Item -LiteralPath $lambdaRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $lambdaRoot -Force | Out-Null

& $PythonExe -m pip install `
    --requirement (Join-Path $projectRoot "requirements-lambda.txt") `
    --target $lambdaRoot `
    --platform manylinux2014_x86_64 `
    --implementation cp `
    --python-version 3.13 `
    --abi cp313 `
    --only-binary=:all: `
    --no-deps `
    --upgrade
if ($LASTEXITCODE -ne 0) { throw "Lambda dependency build failed" }

Copy-Item -LiteralPath (Join-Path $projectRoot "src\authority_agent") -Destination $lambdaRoot -Recurse
Get-ChildItem -LiteralPath $lambdaRoot -Directory -Filter "__pycache__" -Recurse |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
Write-Output "LAMBDA_BUILD: PASS ($lambdaRoot)"
