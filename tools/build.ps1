$ErrorActionPreference = 'Stop'
$azureProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $azureProjectRoot
try {
    & (Join-Path $azureProjectRoot '.venv\Scripts\python.exe') -m PyInstaller --noconfirm --distpath release AzureMusicPlayer.spec
    $azureBuildExit = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $azureBuildExit
