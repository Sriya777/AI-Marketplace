# Stops every process started by start.ps1 (uses the PID files in .run\) including child processes.
$Root = Split-Path -Parent $PSScriptRoot
foreach ($name in @("frontend", "backend", "hardhat", "mongod")) {
  $f = Join-Path $Root ".run\$name.pid"
  if (Test-Path $f) {
    $procId = [int](Get-Content $f)
    if (Get-Process -Id $procId -ErrorAction SilentlyContinue) {
      taskkill /PID $procId /T /F | Out-Null
      Write-Host "stopped $name ($procId)"
    }
    Remove-Item $f -Force
  }
}
