# Runs the automated test suites on Windows. Start the stack first:  .\scripts\start.ps1 -NoFrontend
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Py = Join-Path $Root ".venv\Scripts\python.exe"
& $Py -m pip install -q -r requirements-dev.txt
New-Item -ItemType Directory -Force -Path tests\results | Out-Null
& $Py -m pytest tests\test_crypto_suite.py tests\test_cifar_prepare.py -q
Push-Location blockchain; node scripts\test_contract.js; Pop-Location
& $Py -m pytest tests\test_integration.py -q
Write-Host "Restart the backend (stop.ps1 / start.ps1 -NoFrontend), then run:  $Py -m pytest tests\test_persistence.py -q"
Write-Host "Browser test (needs Firefox + geckodriver + the frontend running):  $Py -m pytest tests\test_browser_e2e.py -q"
