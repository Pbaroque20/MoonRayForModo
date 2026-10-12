# Every two seconds, for the given number of seconds: the processor time each preview process has used so far, and how
# busy the graphics card is. Written as lines of JSON for tools/report_idle.py to set against probe_idle.py's marks.
param([int]$Seconds = 300, [string]$Out = "C:\Users\Raphael Tobar\MoonRayForModo\test-results\idle\samples.jsonl")
New-Item -ItemType Directory -Force (Split-Path $Out) | Out-Null
Set-Content -Path $Out -Value "" -Encoding utf8
$until = (Get-Date).AddSeconds($Seconds)
while ((Get-Date) -lt $until) {
    $now = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0
    $cpu = @{}
    foreach ($p in Get-Process -Name modo, moonray, moonlightipr_session, modo_display_stream -ErrorAction SilentlyContinue) {
        $cpu["$($p.Name):$($p.Id)"] = $p.TotalProcessorTime.TotalSeconds
    }
    $gpu = (& nvidia-smi --query-gpu=utilization.gpu,memory.used,power.draw --format=csv,noheader,nounits) -split ','
    $line = @{ time = $now; cpu = $cpu; gpu = [double]$gpu[0]; memory = [double]$gpu[1]; watts = [double]$gpu[2] } | ConvertTo-Json -Compress
    Add-Content -Path $Out -Value $line -Encoding utf8
    Start-Sleep -Seconds 2
}
