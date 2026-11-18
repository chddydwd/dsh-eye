param([long]$Hwnd = 0, [string]$QueryB64 = '', [int]$MaxResults = 10, [string]$OutPath = '')
$ErrorActionPreference = 'Stop'
$Query = ''
if ($QueryB64 -ne '') { $Query = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($QueryB64)) }
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
if ($Hwnd -eq 0) {
  Add-Type -TypeDefinition 'using System;using System.Runtime.InteropServices;public class Fgw2 { [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow(); }'
  $Hwnd = [Fgw2]::GetForegroundWindow().ToInt64()
}
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$hits = @()
$err = ''
$EP = [System.Windows.Automation.Text.TextPatternRangeEndpoint]
$EP_START = [System.Enum]::Parse($EP, 'Start')
$EP_END = [System.Enum]::Parse($EP, 'End')
try {
  if ($Query -eq '') { throw 'empty query' }
  $el = [System.Windows.Automation.AutomationElement]::FromHandle([System.IntPtr]$Hwnd)
  if ($el -eq $null) { throw 'no element for hwnd' }
  $docs = @()
  $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Document)
  $foundDocs = $el.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
  foreach ($d in $foundDocs) { $docs += $d }
  $docs += $el
  foreach ($docEl in $docs) {
    if ($hits.Count -ge $MaxResults) { break }
    $tp = $null
    try { $tp = $docEl.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern) } catch { continue }
    if ($tp -eq $null) { continue }
    $full = $tp.DocumentRange
    $rest = $full.Clone()
    $guard = 0
    while ($hits.Count -lt $MaxResults -and $guard -lt 400) {
      $guard++
      $hit = $rest.FindText($Query, $false, $false)
      if ($hit -eq $null) { break }
      try {
        $rects = $hit.GetBoundingRectangles()
        if ($rects -ne $null) {
          foreach ($r in $rects) {
            $x = [int]$r.X; $y = [int]$r.Y; $w = [int]$r.Width; $h = [int]$r.Height
            if ($w -ge 2 -and $h -ge 2) {
              $hits += [pscustomobject]@{ x = $x; y = $y; w = $w; h = $h; cx = [int]($x + $w / 2); cy = [int]($y + $h / 2); text = $Query }
              if ($hits.Count -ge $MaxResults) { break }
            }
          }
        }
      } catch {}
      if ($hits.Count -ge $MaxResults) { break }
      $next = $full.Clone()
      try {
        $next.MoveEndpointByRange($EP_START, $hit, $EP_END)
        $next.MoveEndpointByRange($EP_END, $full, $EP_END)
      } catch { break }
      if ($next.CompareEndpoints($EP_START, $hit, $EP_END) -ge 0) { break }
      $rest = $next
    }
  }
} catch { $err = $_.Exception.Message }
$sw.Stop()
$out = [pscustomobject]@{ ok = $true; ms = [int]$sw.ElapsedMilliseconds; hwnd = $Hwnd; q = $Query; n = $hits.Count; hits = $hits; err = $err }
$json = $out | ConvertTo-Json -Compress -Depth 5
if ($OutPath -ne '') { [System.IO.File]::WriteAllText($OutPath, $json, (New-Object System.Text.UTF8Encoding($false))) } else { $json }