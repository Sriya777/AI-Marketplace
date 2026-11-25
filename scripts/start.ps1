<#
 One-command start for Windows (PowerShell 5.1+ or PowerShell 7).
   .\scripts\start.ps1                  start MongoDB (if found), Hardhat, contract, backend, frontend
   .\scripts\start.ps1 -NoFrontend      skip the Next.js frontend
   .\scripts\start.ps1 -ProdFrontend    build + serve the optimised frontend instead of `next dev`
 Environment: $env:MONGOD_BIN = "C:\path\to\mongod.exe"   $env:DB_MODE = "file" | "mongo" | "auto"
 Or simply double-click start.bat in the project root.
#>
param([switch]$NoFrontend, [switch]$ProdFrontend, [switch]$Wait)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Run  = Join-Path $Root ".run"
$Logs = Join-Path $Run "logs"
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Run "mongodata") | Out-Null

function Say($m)  { Write-Host "[start] $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[warn]  $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "[error] $m" -ForegroundColor Red; exit 1 }
function Test-Port([int]$port) {
  try { $c = New-Object System.Net.Sockets.TcpClient; $c.Connect("127.0.0.1", $port); $c.Close(); return $true } catch { return $false }
}
function Test-Http([string]$url) {
  try { $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3; return ($r.StatusCode -eq 200) } catch { return $false }
}
function Wait-For([string]$name, [scriptblock]$test, [int]$seconds) {
  for ($i = 1; $i -le $seconds; $i++) {
    if (& $test) { Say "$name is up (${i}s)"; return $true }
    Start-Sleep -Seconds 1
  }
  Warn "$name did not become ready within $seconds s - see $Logs"
  return $false
}
function Start-Bg([string]$name, [string]$file, [string]$argLine, [string]$workDir) {
  $p = Start-Process -FilePath $file -ArgumentList $argLine -WorkingDirectory $workDir -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $Logs "$name.log") -RedirectStandardError (Join-Path $Logs "$name.err.log")
  Set-Content -Path (Join-Path $Run "$name.pid") -Value $p.Id
}

# ---- prerequisites
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Die "Node.js 18+ is required (https://nodejs.org)" }
if (-not (Get-Command npm  -ErrorAction SilentlyContinue)) { Die "npm is required" }
$PyExe = Join-Path $Root ".venv\Scripts\python.exe"
$PyCmd = $null
if (Test-Path $PyExe) {
  $PyCmd = $PyExe
} else {
  foreach ($c in @("python", "py")) {
    try {
      $testVer = & $c --version 2>$null
      if ($LASTEXITCODE -eq 0) { $PyCmd = $c; break }
    } catch {}
  }
}
if (-not $PyCmd) { Die "Python 3.10+ is required (https://www.python.org/downloads/ - tick 'Add to PATH')" }

# ---- .env (generated once; holds the operator master passphrase)
if (-not (Test-Path ".env")) {
  Say "creating .env with a freshly generated master passphrase"
  $pass = & $PyCmd -c "import secrets; print(secrets.token_urlsafe(32))"
  (Get-Content ".env.example") -replace "^MARKETPLACE_MASTER_PASSPHRASE=.*", "MARKETPLACE_MASTER_PASSPHRASE=$pass" | Set-Content ".env" -Encoding ASCII
}

# ---- Python virtual environment + dependencies
if (-not (Test-Path ".venv")) { Say "creating Python virtual environment (.venv)"; & $PyCmd -m venv .venv; if ($LASTEXITCODE -ne 0) { Die "could not create venv" } }
$PyExe = Join-Path $Root ".venv\Scripts\python.exe"
$Stamp = Join-Path $Root ".venv\.deps_installed"
if (-not (Test-Path $Stamp) -or ((Get-Item "requirements.txt").LastWriteTime -gt (Get-Item $Stamp).LastWriteTime)) {
  Say "installing Python dependencies"
  & $PyExe -m pip install -q -r requirements.txt
  if ($LASTEXITCODE -ne 0) { Die "pip install failed" }
  New-Item -ItemType File -Force -Path $Stamp | Out-Null
}

# ---- Node dependencies
if (-not (Test-Path "blockchain\node_modules")) {
  Say "installing blockchain dependencies"; Push-Location blockchain; cmd /c "npm install --no-audit --no-fund"; $rc = $LASTEXITCODE; Pop-Location
  if ($rc -ne 0) { Die "npm install (blockchain) failed" }
}
if (-not $NoFrontend -and -not (Test-Path "frontend\node_modules")) {
  Say "installing frontend dependencies (first run takes a few minutes)"; Push-Location frontend; cmd /c "npm install --no-audit --no-fund"; $rc = $LASTEXITCODE; Pop-Location
  if ($rc -ne 0) { Die "npm install (frontend) failed" }
}

# ---- MongoDB
$Mongod = $env:MONGOD_BIN
if (-not $Mongod) { $cmd = Get-Command mongod -ErrorAction SilentlyContinue; if ($cmd) { $Mongod = $cmd.Source } }
if (-not $Mongod) {
  $found = Get-ChildItem "C:\Program Files\MongoDB\Server\*\bin\mongod.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
  if ($found) { $Mongod = $found.FullName }
}
if (Test-Port 27017) { Say "MongoDB already running on :27017" }
elseif ($Mongod) {
  Say "starting MongoDB ($Mongod)"
  Start-Bg "mongod" $Mongod "--dbpath `"$(Join-Path $Run 'mongodata')`" --bind_ip 127.0.0.1 --port 27017" $Root
  [void](Wait-For "MongoDB" { Test-Port 27017 } 30)
} else { Warn "MongoDB not found. The backend will use the FILE-BACKED DEVELOPMENT FALLBACK (see README: MongoDB setup)." }

# ---- local blockchain + contract
if (Test-Port 8545) { Say "blockchain node already running on :8545" }
else {
  Say "starting Hardhat local blockchain"
  Start-Bg "hardhat" "cmd.exe" "/c node_modules\.bin\hardhat.cmd node" (Join-Path $Root "blockchain")
  if (-not (Wait-For "Hardhat node" { Test-Port 8545 } 90)) { Die "Hardhat node failed to start (see .run\logs\hardhat.log)" }
}
Say "compiling / deploying ModelRegistry"
Push-Location blockchain; node scripts\ensure_deployed.js; $rc = $LASTEXITCODE; Pop-Location
if ($rc -ne 0) { Die "contract deployment failed" }

# ---- backend
if (Test-Port 8000) { Say "backend already running on :8000" }
else {
  Say "starting FastAPI backend"
  Start-Bg "backend" $PyExe "-m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000" $Root
  if (-not (Wait-For "backend" { Test-Http "http://127.0.0.1:8000/api/health" } 60)) {
    Get-Content (Join-Path $Logs "backend.err.log") -Tail 20 -ErrorAction SilentlyContinue
    Die "backend failed to start"
  }
}

# ---- frontend
if (-not $NoFrontend) {
  if (Test-Port 3000) { Say "frontend already running on :3000" }
  elseif ($ProdFrontend -or (Test-Path "frontend\.next\BUILD_ID")) {
    Start-Bg "frontend" "cmd.exe" "/c npm run start" (Join-Path $Root "frontend")
    [void](Wait-For "frontend" { Test-Http "http://127.0.0.1:3000" } 60)
  } else {
    Start-Bg "frontend" "cmd.exe" "/c npm run dev" (Join-Path $Root "frontend")
    [void](Wait-For "frontend" { Test-Http "http://127.0.0.1:3000" } 120)
  }
}

Write-Host ""
Say "ready:"
if (-not $NoFrontend) { Write-Host "   Frontend   http://localhost:3000" }
Write-Host "   API docs   http://127.0.0.1:8000/docs"
Write-Host "   Health     http://127.0.0.1:8000/api/health"
Write-Host "   Logs       $Logs     (stop everything with .\scripts\stop.ps1)"

if ($Wait) {
  Say "Services running. Press Ctrl+C to stop..."
  try {
    while ($true) { Start-Sleep -Seconds 3600 }
  } finally {
    & (Join-Path $PSScriptRoot "stop.ps1")
  }
}
