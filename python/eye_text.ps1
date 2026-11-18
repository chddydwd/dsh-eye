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
      $rx = 0; $ry = 0; $rw = 0; $rh = 0; $role = ''
      try {
        $r = $child.Current.BoundingRectangle
        $role = $child.Current.ControlType.ProgrammaticName.Replace('ControlType.','')
        # 有的窗口会给出 NaN / Infinity / 天文数字坐标，[int] 转换会抛异常把整棵树的读取打断
        try { if (-not [double]::IsNaN($r.X) -and -not [double]::IsInfinity($r.X)) { $rx = [int][math]::Max(-2000000, [math]::Min(2000000, $r.X)) } } catch {}
        try { if (-not [double]::IsNaN($r.Y) -and -not [double]::IsInfinity($r.Y)) { $ry = [int][math]::Max(-2000000, [math]::Min(2000000, $r.Y)) } } catch {}
        try { if (-not [double]::IsNaN($r.Width) -and -not [double]::IsInfinity($r.Width)) { $rw = [int][math]::Max(0, [math]::Min(2000000, $r.Width)) } } catch {}
        try { if (-not [double]::IsNaN($r.Height) -and -not [double]::IsInfinity($r.Height)) { $rh = [int][math]::Max(0, [math]::Min(2000000, $r.Height)) } } catch {}
      } catch {}
      try { $null = $script:nodes.Add([pscustomobject]@{ r = $role; n = $n; v = $v; t = $t; p = $pw; x = $rx; y = $ry; w = $rw; h = $rh }) } catch {}
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
# Chromium/Edge: Document 常常不在 ControlView 树里，按文档正文再补一段（读不到 t 才补，避免重复）
$joined = (($nodes | ForEach-Object { $_.t }) -join "`n")
if ($true) {
  try {
    $condD = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Document)
    $docsD = $el.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condD)
    foreach ($dD in $docsD) {
      try {
        $tpD = $dD.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)
        if ($tpD -ne $null) {
          $txtD = $tpD.DocumentRange.GetText(6000)
          if ($txtD -ne $null -and $txtD.Trim() -ne '' -and $joined.IndexOf($txtD.Trim()) -lt 0) {
            $rD = $dD.Current.BoundingRectangle
            $null = $nodes.Add([pscustomobject]@{ r = 'Document'; n = ''; v = ''; t = $txtD; p = $false; x = [int]$rD.X; y = [int]$rD.Y; w = [int]$rD.Width; h = [int]$rD.Height })
            break
          }
        }
      } catch {}
    }
  } catch {}
}
$sw.Stop()
$out = [pscustomobject]@{ ok = $true; ms = [int]$sw.ElapsedMilliseconds; hwnd = $Hwnd; title = $el.Current.Name; cls = $el.Current.ClassName; n = $nodes.Count; nodes = $nodes; pwds = $pwds; edits = $pwdEdits }
$json = $out | ConvertTo-Json -Compress -Depth 5
if ($OutPath -ne '') { [System.IO.File]::WriteAllText($OutPath, $json, (New-Object System.Text.UTF8Encoding($false))) } else { $json }