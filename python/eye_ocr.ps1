# dsh-eye OCR: read text from an image with the Windows built-in engine (zh/en, offline).
# usage: powershell -NoProfile -ExecutionPolicy Bypass -File eye_ocr.ps1 <image path> [max lines]
param([string]$Path, [int]$MaxLines = 200, [string]$OutPath = '')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskOp = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $t) { $task = $asTaskOp.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait(-1) | Out-Null; $task.Result }
$BD = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$SB = [Windows.Graphics.Imaging.SoftwareBitmap,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$OCR = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$IRAS = [Windows.Storage.Streams.InMemoryRandomAccessStream,Windows.Storage.Streams,ContentType=WindowsRuntime]
$DW = [Windows.Storage.Streams.DataWriter,Windows.Storage.Streams,ContentType=WindowsRuntime]
$wordsType = [Windows.Media.Ocr.OcrWord,Windows.Foundation,ContentType=WindowsRuntime]
$bytes = [System.IO.File]::ReadAllBytes($Path)
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$stream = $IRAS::new()
$writer = $DW::new($stream)
$writer.WriteBytes($bytes)
$null = Await ($writer.StoreAsync()) ([uint32])
$writer.DetachStream() | Out-Null
$stream.Seek(0)
$decoder = Await ($BD::CreateAsync($stream)) $BD
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) $SB
$engine = $OCR::TryCreateFromUserProfileLanguages()
if ($engine -eq $null) { '{"ok":false,"err":"no ocr engine"}'; exit 0 }
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult,Windows.Foundation,ContentType=WindowsRuntime])
$sw.Stop()
$arr = New-Object System.Collections.ArrayList
$i = 0
foreach ($line in $result.Lines) {
  if ($i -ge $MaxLines) { break }
  $x1 = 1e9; $y1 = 1e9; $x2 = -1; $y2 = -1
  foreach ($wd in $line.Words) { $r = $wd.BoundingRect; if ($r.X -lt $x1) { $x1 = $r.X }; if ($r.Y -lt $y1) { $y1 = $r.Y }; if (($r.X + $r.Width) -gt $x2) { $x2 = $r.X + $r.Width }; if (($r.Y + $r.Height) -gt $y2) { $y2 = $r.Y + $r.Height } }
  if ($x2 -lt 0) { continue }
  $null = $arr.Add([pscustomobject]@{ t = $line.Text; x = [int]$x1; y = [int]$y1; w = [int]($x2 - $x1); h = [int]($y2 - $y1) })
  $i++
}
$out = [pscustomobject]@{ ok = $true; ms = [int]$sw.ElapsedMilliseconds; n = $arr.Count; lines = $arr }
$json = $out | ConvertTo-Json -Compress -Depth 4
if ($OutPath -ne '') { [System.IO.File]::WriteAllText($OutPath, $json, (New-Object System.Text.UTF8Encoding($false))) } else { $json }