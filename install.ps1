# wow-voice installer for Windows: a Python venv with Vosk and sounddevice, the Vosk
# models, the WoW Voice addon, and a wow-voice.cmd to start it. Safe to run again.
#
#   powershell -ExecutionPolicy Bypass -File install.ps1
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Lang en
#   powershell -ExecutionPolicy Bypass -File install.ps1 -AddOns "D:\Games\World of Warcraft\_classic_beta_\Interface\AddOns"
param(
    [string]$Lang = "es en",
    [string]$AddOns = ""
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest is much faster without the bar

$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$Data = if ($env:WOWVOICE_HOME) { $env:WOWVOICE_HOME } else { Join-Path $env:LOCALAPPDATA "wow-voice" }
function Say($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "!!  $m" -ForegroundColor Yellow }

# 1. Python 3.10 or newer (python.org or the Microsoft Store).
$py = $null
foreach ($c in @("py", "python", "python3")) {
    if (Get-Command $c -ErrorAction SilentlyContinue) { $py = $c; break }
}
if (-not $py) {
    Warn "Python not found. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH') and run this again."
    exit 1
}

# 2. The venv, Vosk and sounddevice.
Say "Python venv in $Data\venv"
New-Item -ItemType Directory -Force -Path "$Data\vosk" | Out-Null
$vpy = Join-Path $Data "venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) {
    if ($py -eq "py") { & py -3 -m venv "$Data\venv" } else { & $py -m venv "$Data\venv" }
}
& $vpy -m pip install -q --upgrade pip
& $vpy -m pip install -q -r (Join-Path $Repo "requirements.txt")

# 3. The speech models (about 40 MB each).
$models = @{ "es" = "vosk-model-small-es-0.42"; "en" = "vosk-model-small-en-us-0.15" }
foreach ($l in $Lang.Split(" ", [System.StringSplitOptions]::RemoveEmptyEntries)) {
    $m = $models[$l]
    if (-not $m) { Warn "no model for language '$l' (es, en)"; continue }
    if (Test-Path (Join-Path $Data "vosk\$m")) { Say "Vosk model ${m}: already there"; continue }
    Say "Downloading the Vosk model $m"
    $zip = Join-Path $Data "vosk\$m.zip"
    Invoke-WebRequest -Uri "https://alphacephei.com/vosk/models/$m.zip" -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath (Join-Path $Data "vosk") -Force
    Remove-Item $zip
}

# 4. The addon, into the game's AddOns folder.
if (-not $AddOns) {
    $found = @()
    foreach ($root in @("${env:ProgramFiles(x86)}\World of Warcraft", "$env:ProgramFiles\World of Warcraft", "C:\World of Warcraft")) {
        if (Test-Path $root) {
            Get-ChildItem -Directory -Path $root -Filter "_*_" | ForEach-Object {
                $a = Join-Path $_.FullName "Interface\AddOns"
                if (Test-Path $a) { $found += $a }
            }
        }
    }
    if ($found.Count -eq 1) { $AddOns = $found[0] }
    elseif ($found.Count -gt 1) { Warn "several WoW installs; pick one with -AddOns:"; $found | ForEach-Object { Write-Host "     $_" } }
    else { Warn "WoW's AddOns folder not found; copy addon\WoWVoice there yourself, or use -AddOns" }
}
if ($AddOns) {
    Say "Addon WoW Voice -> $AddOns"
    New-Item -ItemType Directory -Force -Path $AddOns | Out-Null
    Copy-Item -Recurse -Force (Join-Path $Repo "addon\WoWVoice") $AddOns
    Write-Host "   Restart the game (a new addon is only found at start), then /reload once in game."
}

# 5. A command to start it.
$cmd = Join-Path $Data "wow-voice.cmd"
Set-Content -Path $cmd -Encoding ASCII -Value "@echo off`r`ncd /d `"$Repo`"`r`n`"$vpy`" -m wowvoice %*`r`n"

Write-Host ""
Say "Done."
Write-Host "   Start:        $cmd          (keep the window open while you play)"
Write-Host "   Try a phrase: $cmd --say `"jump twice`" --lang en"
Write-Host "   Microphone:   Settings > Privacy & security > Microphone > let desktop apps use it."
Write-Host "   If WoW runs as administrator, run wow-voice as administrator too (Windows blocks keys otherwise)."
Write-Host "   Optional:     JEV (understands free phrasing): OPENROUTER_API_KEY=... in $env:USERPROFILE\.config\wow-voice\openrouter.env"
