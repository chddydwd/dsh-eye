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
    $v = ''
    try { if (-not $child.Current.IsPassword) { $vp = $child.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern); if ($vp -ne $null) { $v = $vp.Current.Value } } } catch {}
    $t = ''
    try { $tp = $child.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern); if ($tp -ne $null) { $t = $tp.DocumentRange.GetText(4000) } } catch {}
    if (($n -ne '') -or ($v -ne '') -or ($t -ne '')) {
      $r = $child.Current.BoundingRectangle
      $role = $child.Current.ControlType.ProgrammaticName.Replace('ControlType.','')
      $null = $script:nodes.Add([pscustomobject]@{ r = $role; n = $n; v = $v; t = $t; x = [int]$r.X; y = [int]$r.Y; w = [int]$r.Width; h = [int]$r.Height })
    }
    Walk $child ($depth + 1)
    $child = $walker.GetNextSibling($child)
  }
}
$script:nodes = $nodes
$script:maxN = $MaxNodes
Walk $el 0
$sw.Stop()
$out = [pscustomobject]@{ ok = $true; ms = [int]$sw.ElapsedMilliseconds; hwnd = $Hwnd; title = $el.Current.Name; cls = $el.Current.ClassName; n = $nodes.Count; nodes = $nodes }
$json = $out | ConvertTo-Json -Compress -Depth 5
if ($OutPath -ne '') { [System.IO.File]::WriteAllText($OutPath, $json, (New-Object System.Text.UTF8Encoding($false))) } else { $json }