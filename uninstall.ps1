# dsh-eye uninstaller (Windows / PowerShell 5+)
#   powershell -ExecutionPolicy Bypass -File uninstall.ps1
#   powershell -ExecutionPolicy Bypass -File uninstall.ps1 -KeepFiles -RemoveConfig
# Removes the plugin from every DSH profile and unlinks node_modules.
# By default the capture scripts under .dsh\plugins\dsh-eye are kept; pass -KeepFiles to keep them too.

param(
  [switch]$KeepFiles,
  [switch]$RemoveConfig
)

$ErrorActionPreference = 'Stop'
$DshHome = if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $HOME '.dsh' }
$Dest = Join-Path $DshHome 'plugins\dsh-eye'
$EyeJson = Join-Path $DshHome 'eye.json'

function Say($m) { Write-Host "[dsh-eye] $m" }

$profilesRoot = Join-Path $DshHome 'profiles'
if (Test-Path $profilesRoot) {
  Get-ChildItem -Path $profilesRoot -Directory | ForEach-Object {
    $prof = $_.FullName
    $pkgPath = Join-Path $prof 'package.json'
    if (Test-Path $pkgPath) {
      $pkg = Get-Content -Raw -Path $pkgPath | ConvertFrom-Json
      $changed = $false
      if ($pkg.PSObject.Properties['dependencies'] -and $pkg.dependencies.PSObject.Properties['dsh-eye']) {
        $pkg.dependencies.PSObject.Properties.Remove('dsh-eye'); $changed = $true
      }
      if ($pkg.PSObject.Properties['dsh'] -and $pkg.dsh.PSObject.Properties['profile'] -and $pkg.dsh.profile.PSObject.Properties['bundles']) {
        $old = @($pkg.dsh.profile.bundles)
        $new = @($old | Where-Object { $_ -ne 'dsh-eye' })
        if ($new.Count -ne $old.Count) { $pkg.dsh.profile.bundles = $new; $changed = $true }
      }
      if ($changed) {
        Copy-Item -Force $pkgPath "$pkgPath.dsh-eye-uninstall.bak"
        ($pkg | ConvertTo-Json -Depth 100) | Set-Content -Encoding UTF8 -Path $pkgPath
        Say "cleaned profile $prof"
      }
    }
    $link = Join-Path $prof 'node_modules\dsh-eye'
    if (Test-Path $link) { Remove-Item $link -Force -Recurse -ErrorAction SilentlyContinue; Say "removed link $link" }
  }
}

if (-not $KeepFiles -and (Test-Path $Dest)) { Remove-Item $Dest -Force -Recurse; Say "removed $Dest" }
if ($RemoveConfig -and (Test-Path $EyeJson)) { Remove-Item $EyeJson -Force; Say "removed $EyeJson" }

Say "done. restart DSH."
