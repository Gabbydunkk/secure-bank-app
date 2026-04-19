param(
  [switch]$SkipFrontend
)

$ErrorActionPreference = 'Stop'

Write-Host "== Secure Banking Sanity Check ==" -ForegroundColor Cyan
Write-Host "1) Backend tests" -ForegroundColor Yellow
venv\Scripts\python -m pytest -q

if (-not $SkipFrontend) {
  Write-Host "2) Frontend build" -ForegroundColor Yellow
  npm.cmd --prefix secure-bank-frontend run build
}

Write-Host "Sanity check passed." -ForegroundColor Green
