$ErrorActionPreference = 'Stop'
$azureProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $azureProjectRoot
try {
    & (Join-Path $azureProjectRoot '.venv\Scripts\python.exe') -m unittest discover -s tests -v
    $azureTestExit = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $azureTestExit
