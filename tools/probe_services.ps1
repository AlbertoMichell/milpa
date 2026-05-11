$ErrorActionPreference = 'SilentlyContinue'
function Probe($name, $url) {
  try {
    $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri $url
    Write-Host "${name}: UP ($($r.StatusCode))"
  } catch {
    Write-Host "${name}: DOWN"
  }
}
Probe 'backend(8000)'  'http://localhost:8000/health'
Probe 'frontend(4000)' 'http://localhost:4000/login.html'
Probe 'presenter(3001)' 'http://localhost:3001/'
