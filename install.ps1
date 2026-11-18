# dsh-eye installer (Windows / PowerShell 5+)
# Usage:
#   powershell -ExecutionPolicy Bypass -File install.ps1
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Profile desktop -Python C:\path\python.exe
#   powershell -ExecutionPolicy Bypass -File install.ps1 -SkipDeps
#
# What it does:
#   1. copies plugin + python runtime into %USERPROFILE%\.dsh\plugins\dsh-eye
#   2. finds Python, installs numpy + pillow (unless -SkipDeps)
#   3. writes %USERPROFILE%\.dsh\eye.json (paths.dir / paths.python)
#   4. links the plugin into every DSH profile (or just -Profile) and registers the bundle
#   5. checks ffmpeg and prints what to do when it is missing
# Nothing is deleted; existing files are backed up next to themselves (*.dsh-eye.bak).

param(
  [string]$Profile = "",
  [string]$Python = "",
  [switch]$SkipDeps
)

$ErrorActionPreference = 'Stop'

# PS5 的 Set-Content -Encoding UTF8 会写 BOM；DSH 启动时 JSON.parse 遇到 BOM 会直接崩，所以自己写
function WriteUtf8NoBom($Path, $Text) {
  $enc = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($Path, $Text, $enc)
}

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$DshHome = if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $HOME '.dsh' }
$Dest = Join-Path $DshHome 'plugins\dsh-eye'
$PyDest = Join-Path $Dest 'python'
$EyeJson = Join-Path $DshHome 'eye.json'

function Say($msg) { Write-Host "[dsh-eye] $msg" }
function Warn($msg) { Write-Host "[dsh-eye] WARN: $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "[dsh-eye] ERROR: $msg" -ForegroundColor Red; exit 1 }

if (-not (Test-Path (Join-Path $Root 'package.json'))) { Fail "run this script from the dsh-eye repo folder (package.json not found next to it)" }
if (-not (Test-Path $DshHome)) { Fail "DSH home not found: $DshHome (is DSH installed for this user?)" }

# ---------- 1. copy files ----------
Say "installing to $Dest"
New-Item -ItemType Directory -Force -Path $Dest, $PyDest | Out-Null
Copy-Item -Force -Recurse (Join-Path $Root 'lib') (Join-Path $Dest 'lib')
foreach ($f in @('package.json','cordis.patch.yml','README.md','LICENSE')) {
  $src = Join-Path $Root $f
  if (Test-Path $src) { Copy-Item -Force $src (Join-Path $Dest $f) }
}
Get-ChildItem -Path (Join-Path $Root 'python') -Filter *.py | ForEach-Object { Copy-Item -Force $_.FullName (Join-Path $PyDest $_.Name) }
Copy-Item -Force (Join-Path $Root 'python\requirements.txt') (Join-Path $PyDest 'requirements.txt')
Get-ChildItem -Path $PyDest -Filter '__pycache__' -Recurse -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# ---------- 2. python ----------
function Find-Python {
  param([string]$Hint)
  $cand = @()
  if ($Hint) { $cand += $Hint }
  if ($env:DSH_EYE_PYTHON) { $cand += $env:DSH_EYE_PYTHON }
  foreach ($v in @('312','311','313')) { $cand += (Join-Path $HOME "AppData\Local\Programs\Python\Python$v\python.exe") }
  $cand += 'C:\Python312\python.exe'
  $cand += 'C:\Python311\python.exe'
  foreach ($c in $cand) { if ($c -and (Test-Path $c)) { return (Resolve-Path $c).Path } }
  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) {
    try {
      $out = & $py.Source -3 -c "import sys;print(sys.executable)" 2>$null
      if ($out -and (Test-Path $out)) { return $out }
    } catch { }
  }
  return ""
}

$Py = Find-Python -Hint $Python
if (-not $Py) { Fail "Python 3 not found. Install from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run this script again with -Python C:\path\to\python.exe" }
Say "python: $Py"
try { $ver = & $Py -c "import sys;print('%d.%d' % sys.version_info[:2])" } catch { $ver = "?" }
Say "python version: $ver"

if (-not $SkipDeps) {
  Say "installing numpy + pillow + mss (python -m pip install -r requirements.txt)"
  & $Py -m pip install --disable-pip-version-check --quiet -r (Join-Path $PyDest 'requirements.txt')
  if ($LASTEXITCODE -ne 0) { Warn "pip install failed (exit $LASTEXITCODE). Eye will not capture until numpy/pillow are available." }
}

# ---------- 3. eye.json ----------
$cfg = [ordered]@{}
if (Test-Path $EyeJson) {
  Copy-Item -Force $EyeJson "$EyeJson.dsh-eye.bak"
  try {
    $raw = Get-Content -Raw -Path $EyeJson | ConvertFrom-Json
    foreach ($p in $raw.PSObject.Properties) { $cfg[$p.Name] = $p.Value }
  } catch { Warn "existing eye.json is not valid JSON, rewriting it (backup kept at eye.json.dsh-eye.bak)" }
}
if (-not $cfg.Contains('watch')) { $cfg['watch'] = $true }
if (-not $cfg.Contains('mode')) { $cfg['mode'] = 'toast' }
if (-not $cfg.Contains('gapSec')) { $cfg['gapSec'] = 25 }
if (-not $cfg.Contains('threshold')) { $cfg['threshold'] = 20 }
if (-not $cfg.Contains('maxWakes')) { $cfg['maxWakes'] = 3 }
if (-not $cfg.Contains('maxPerHour')) { $cfg['maxPerHour'] = 12 }
if (-not $cfg.Contains('autostart')) { $cfg['autostart'] = $true }
$paths = [ordered]@{ dir = $PyDest; python = $Py }
$cfg['paths'] = $paths
WriteUtf8NoBom -Path $EyeJson -Text ($cfg | ConvertTo-Json -Depth 20)
Say "wrote $EyeJson (paths.dir = $PyDest)"

# ---------- 4. profiles ----------
$profilesRoot = Join-Path $DshHome 'profiles'
if (-not (Test-Path $profilesRoot)) { Fail "profiles folder not found: $profilesRoot" }
$targets = @()
if ($Profile) {
  $p = Join-Path $profilesRoot $Profile
  if (-not (Test-Path $p)) { Fail "profile not found: $p" }
  $targets += $p
} else {
  Get-ChildItem -Path $profilesRoot -Directory | ForEach-Object { $targets += $_.FullName }
}

$linkSpec = 'link:' + ($Dest -replace '\\','/')
foreach ($prof in $targets) {
  $pkgPath = Join-Path $prof 'package.json'
  if (-not (Test-Path $pkgPath)) { Warn "skip $prof (no package.json)"; continue }
  Copy-Item -Force $pkgPath "$pkgPath.dsh-eye.bak"
  $pkg = Get-Content -Raw -Path $pkgPath | ConvertFrom-Json
  if (-not $pkg.PSObject.Properties['dependencies']) { $pkg | Add-Member -NotePropertyName dependencies -NotePropertyValue ([pscustomobject]@{}) }
  $deps = $pkg.dependencies
  if (-not $deps.PSObject.Properties['dsh-eye']) {
    $deps | Add-Member -NotePropertyName 'dsh-eye' -NotePropertyValue $linkSpec
    Say "added dependency dsh-eye -> $linkSpec in $prof"
  } elseif ($deps.'dsh-eye' -ne $linkSpec) {
    $deps.'dsh-eye' = $linkSpec
    Say "updated dependency dsh-eye in $prof"
  }
  if (-not $pkg.PSObject.Properties['dsh']) {
    $pkg | Add-Member -NotePropertyName dsh -NotePropertyValue ([pscustomobject]@{ profile = [pscustomobject]@{ bundles = @() } })
  }
  if (-not $pkg.dsh.PSObject.Properties['profile']) {
    $pkg.dsh | Add-Member -NotePropertyName profile -NotePropertyValue ([pscustomobject]@{ bundles = @() })
  }
  if (-not $pkg.dsh.profile.PSObject.Properties['bundles']) {
    $pkg.dsh.profile | Add-Member -NotePropertyName bundles -NotePropertyValue @()
  }
  $bundles = @($pkg.dsh.profile.bundles)
  if ($bundles -notcontains 'dsh-eye') {
    $pkg.dsh.profile.bundles = @($bundles + 'dsh-eye')
    Say "registered bundle dsh-eye in $prof"
  }
  WriteUtf8NoBom -Path $pkgPath -Text ($pkg | ConvertTo-Json -Depth 100)

  $nm = Join-Path $prof 'node_modules'
  New-Item -ItemType Directory -Force -Path $nm | Out-Null
  $link = Join-Path $nm 'dsh-eye'
  $ok = $false
  if (Test-Path $link) {
    $item = Get-Item $link -Force
    if ($item.LinkType) {
      if ($item.Target -and ((Resolve-Path $item.Target -ErrorAction SilentlyContinue).Path -eq (Resolve-Path $Dest).Path)) { $ok = $true }
      else { Remove-Item $link -Force -Recurse -ErrorAction SilentlyContinue }
    } else {
      Remove-Item $link -Force -Recurse -ErrorAction SilentlyContinue
    }
  }
  if (-not $ok) {
    try { New-Item -ItemType Junction -Path $link -Target $Dest | Out-Null; Say "linked $link -> $Dest" }
    catch { Warn "could not create junction $link (copy it manually or run as admin)" }
  }
}

# ---------- 5. ffmpeg ----------
$ff = ""
foreach ($c in @($env:EYE_FFMPEG, $env:DSH_EYE_FFMPEG)) { if ($c -and (Test-Path $c)) { $ff = $c; break } }
if (-not $ff) { $cmd = Get-Command ffmpeg -ErrorAction SilentlyContinue; if ($cmd) { $ff = $cmd.Source } }
if (-not $ff) {
  $we = Join-Path $HOME '.dsh\.dsh-wallpaper-engine\ffmpeg\ffmpeg.exe'
  if (Test-Path $we) { $ff = $we }
}
if ($ff) { Say "ffmpeg: $ff" }
else { Warn "ffmpeg not found. Install it (winget install Gyan.FFmpeg) or set EYE_FFMPEG=C:\path\ffmpeg.exe, or point eye.json paths.ffmpeg at it." }

Say ""
Say "done. restart DSH, open the sidebar item 'Eye', press Start."
Say "config: $EyeJson   runtime:  http://127.0.0.1:13201"
