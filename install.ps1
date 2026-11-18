# Clip Agent installer for Windows.
# Run in PowerShell:  irm https://raw.githubusercontent.com/coder677777/clip-agent/main/install.ps1 | iex
# Installs to %LOCALAPPDATA%\ClipAgent, sets up Python if needed, and adds Desktop + Start menu icons.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Repo = 'coder677777/clip-agent'
$Raw  = "https://raw.githubusercontent.com/$Repo/main"
$Dir  = Join-Path $env:LOCALAPPDATA 'ClipAgent'

function Say($msg) { Write-Host "  $msg" -ForegroundColor Cyan }
function Find-Python {
    foreach ($v in '3.12', '3.13', '3.11', '3.10', '3.14') {
        try {
            $p = & py "-$v" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $p) { return ($p | Select-Object -First 1).Trim() }
        } catch {}
    }
    foreach ($c in @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
                     "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
                     "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe")) {
        if (Test-Path $c) { return $c }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notmatch 'WindowsApps') { return $cmd.Source }
    return $null
}

Write-Host ""
Write-Host "  Installing Clip Agent" -ForegroundColor Yellow
Write-Host ""

# Close a running copy so files can be replaced
try { Invoke-WebRequest -UseBasicParsing -Method Post -TimeoutSec 2 'http://127.0.0.1:8765/api/quit' | Out-Null; Start-Sleep 2 } catch {}

# 1. Python
$py = Find-Python
if (-not $py) {
    Say "Installing Python 3.12 (one time, a couple of minutes)..."
    $ok = $false
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        try {
            winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Host
            $ok = $true
        } catch {}
    }
    $py = Find-Python
    if (-not $py) {
        Say "Downloading Python from python.org..."
        $exe = Join-Path $env:TEMP 'python-3.12.10-amd64.exe'
        Invoke-WebRequest -UseBasicParsing 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $exe
        Start-Process $exe -ArgumentList '/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0' -Wait
        $py = Find-Python
    }
    if (-not $py) { throw "Python didn't install. Install Python 3.12 from https://www.python.org/downloads/ and run this again." }
}
Say "Using Python: $py"

# 2. App files
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
Say "Downloading Clip Agent..."
$manifestText = (Invoke-WebRequest -UseBasicParsing "$Raw/manifest.json?t=$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())").Content
if ($manifestText -is [byte[]]) { $manifestText = [Text.Encoding]::UTF8.GetString($manifestText) }
$manifest = $manifestText | ConvertFrom-Json
foreach ($f in $manifest.files.PSObject.Properties.Name) {
    $dest = Join-Path $Dir ($f -replace '/', '\')
    New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
    for ($try = 1; $try -le 4; $try++) {
        try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 120 "$Raw/$f" -OutFile $dest; break }
        catch { if ($try -eq 4) { throw "Couldn't download $f (internet too slow?). Run the install command again." }
                Say "Download timed out, retrying ($try/3)..."; Start-Sleep -Seconds (5 * $try) }
    }
}
[IO.File]::WriteAllText((Join-Path $Dir 'manifest.json'), $manifestText)

# Bring over a Gemini key from an older Clip Agent folder, if there is one
if (-not (Test-Path (Join-Path $Dir 'config.json'))) {
    foreach ($root in @("$env:USERPROFILE\Downloads", "$env:USERPROFILE\Desktop", "$env:USERPROFILE\Documents")) {
        if (-not (Test-Path $root)) { continue }
        $old = Get-ChildItem $root -Recurse -Depth 4 -Filter config.json -ErrorAction SilentlyContinue |
               Where-Object { $_.Directory.Name -like 'clip-agent*' } | Select-Object -First 1
        if ($old) { Copy-Item $old.FullName (Join-Path $Dir 'config.json'); Say "Kept your saved Gemini key."; break }
    }
}

# 3. Packages
$venvPy = Join-Path $Dir '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
    Say "Setting up (first time takes a few minutes)..."
    & $py -m venv (Join-Path $Dir '.venv')
    if (-not (Test-Path $venvPy)) {
        throw "Couldn't set up Python for Clip Agent. Reinstall Python 3.12 from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run the install command again."
    }
}
& $venvPy -m pip install --upgrade pip --quiet --disable-pip-version-check --timeout 120 --retries 10
$pipOk = $false
for ($try = 1; $try -le 3; $try++) {
    & $venvPy -m pip install -r (Join-Path $Dir 'requirements.txt') --disable-pip-version-check --timeout 120 --retries 10
    if ($LASTEXITCODE -eq 0) { $pipOk = $true; break }
    if ($try -lt 3) { Say "A download was too slow. Trying again ($try/2) - finished downloads are kept..."; Start-Sleep -Seconds 10 }
}
if (-not $pipOk) { throw "Installing packages failed (the internet connection kept timing out). Run the install command again; it continues where it stopped." }

# 4. Icons
$pyw = Join-Path $Dir '.venv\Scripts\pythonw.exe'
$launch = Join-Path $Dir 'launch.pyw'
$shell = New-Object -ComObject WScript.Shell
$places = @([Environment]::GetFolderPath('Desktop'), (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'))
foreach ($place in $places) {
    $lnk = $shell.CreateShortcut((Join-Path $place 'Clip Agent.lnk'))
    $lnk.TargetPath = $pyw
    $lnk.Arguments = "`"$launch`""
    $lnk.WorkingDirectory = $Dir
    $lnk.IconLocation = (Join-Path $Dir 'icon.ico')
    $lnk.Description = 'Turn long videos into Shorts and TikTok clips'
    $lnk.Save()
}

# 5. Open it
Start-Process $pyw -ArgumentList "`"$launch`"" -WorkingDirectory $Dir
Write-Host ""
Write-Host "  Done! Clip Agent is opening in your browser." -ForegroundColor Green
Write-Host "  Next time, double-click the Clip Agent icon on your desktop." -ForegroundColor Green
Write-Host ""
