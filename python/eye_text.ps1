# dsh-eye UIA: read what the foreground (or given) window actually shows - control names, values, document text.
# usage: powershell -NoProfile -ExecutionPolicy Bypass -File eye_text.ps1 <hwnd or 0> <max nodes> <out json path>
param([long]$Hwnd = 0, [int]$MaxNodes = 200, [string]$OutPath = '')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
if ($Hwnd -eq 0) {
  Add-Type -TypeDefinition 'using System;using System.Runtime.InteropServices;public class Fgw { [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow(); }'
  $Hwnd = [Fgw]::GetForegroundWindow().ToInt64()
}
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$el = [System.Windows.Automation.AutomationElement]::FromHandle([System.IntPtr]$Hwnd)
if ($el -eq $null) { $j = '{"ok":false,"err":"no element for hwnd"}'; if ($OutPath -ne '') { [System.IO.File]::WriteAllText($OutPath, $j) } else { $j }; exit 0 }
$nodes = New-Object System.Collections.ArrayList
$walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
function Walk($e, $depth) {
  if ($depth -gt 8 -or $script:nodes.Count -ge $script:maxN) { return }
  $child = $walker.GetFirstChild($e)
  while ($child -ne $null -and $script:nodes.Count -lt $script:maxN) {
    $n = $child.Current.Name
    $pw = $false
    try { $pw = [bool]$child.Current.IsPassword } catch {}
    $v = ''
    try { if (-not $pw) { $vp = $child.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern); if ($vp -ne $null) { $v = $vp.Current.Value } } } catch {}
    $t = ''
    try { $tp = $child.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern); if ($tp -ne $null) { $t = $tp.DocumentRange.GetText(4000) } } catch {}
    if (($n -ne '') -or ($v -ne '') -or ($t -ne '') -or $pw) {
      $r = $child.Current.BoundingRectangle
      $role = $child.Current.ControlType.ProgrammaticName.Replace('ControlType.','')
      $null = $script:nodes.Add([pscustomobject]@{ r = $role; n = $n; v = $v; t = $t; p = $pw; x = [int]$r.X; y = [int]$r.Y; w = [int]$r.Width; h = [int]$r.Height })
    }
    Walk $child ($depth + 1)
    $child = $walker.GetNextSibling($child)
  }
}
$script:nodes = $nodes
$script:maxN = $MaxNodes
Walk $el 0
# 密码框单独扫一遍：ControlView 的树很浅，Chromium 的输入框常常不在里面。
$pwds = @()
$pwdEdits = 0
try {
  $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Edit)
  $eds = $el.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
  $pwdEdits = $eds.Count
  foreach ($e2 in $eds) {
    try {
      if ($e2.Current.IsPassword) {
        $r2 = $e2.Current.BoundingRectangle
        if ([int]$r2.Width -ge 6 -and [int]$r2.Height -ge 6) {
          $pwds += [pscustomobject]@{ x = [int]$r2.X; y = [int]$r2.Y; w = [int]$r2.Width; h = [int]$r2.Height }
        }
      }
    } catch {}
  }
} catch {}
$sw.Stop()
$out = [pscustomobject]@{ ok = $true; ms = [int]$sw.ElapsedMilliseconds; hwnd = $Hwnd; title = $el.Current.Name; cls = $el.Current.ClassName; n = $nodes.Count; nodes = $nodes; pwds = $pwds; edits = $pwdEdits }
$json = $out | ConvertTo-Json -Compress -Depth 5
if ($OutPath -ne '') { [System.IO.File]::WriteAllText($OutPath, $json, (New-Object System.Text.UTF8Encoding($false))) } else { $json }