<#
MRLab tracking PC tools (procedure in README.md next to this file). Started by the numbered .bat files.

Everything stays inside this folder: downloads, Python, Ollama, the vision model and all temporary
files go to .\runtime, and every program started from here (PowerShell included, see env.bat) gets
its home, AppData and temp folders inside .\runtime. Nothing is installed, no setting of the PC is
changed, no file outside this folder is written. To remove everything, delete this folder.

Actions:
  check    read-only report: Windows, GPU, disk, Moverse, network, internet, setup state
  setup    download Python, the Python packages, Ollama and the vision model into .\runtime
  cameras  list the OAK cameras and show one picture of each (optional: camera addresses)
  run      start the vision model and the camera service (asks for its two settings once)
#>
param(
    [Parameter(Mandatory = $true)][ValidateSet('check', 'setup', 'cameras', 'run')][string]$Action,
    [ValidateSet('oak', 'webcam')][string]$Source = 'oak',  # webcam: laptop testing only
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Cameras = @()
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Here = $PSScriptRoot
$Runtime = Join-Path $Here 'runtime'
$Downloads = Join-Path $Runtime 'downloads'
$PythonDir = Join-Path $Runtime 'python'
$Python = Join-Path $PythonDir 'python.exe'
$SitePackages = Join-Path $PythonDir 'Lib\site-packages'
$OllamaDir = Join-Path $Runtime 'ollama'
$Model = 'qwen3.5:4b'
$ModelManifest = Join-Path $Runtime 'models\manifests\registry.ollama.ai\library\qwen3.5\4b'
$OllamaAddress = '127.0.0.1:11435'  # its own port, so an Ollama installed on the PC is not touched
$Settings = Join-Path $Here 'mrlab_camera_service.local.json'

$PythonUrl = 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip'
$Wheels = @(@('numpy', '2.2.6'), @('opencv-python', '4.12.0.88'), @('depthai', '3.12.0'))
$OllamaVersion = 'v0.40.15'

function Title($Text) { Write-Host "`n== $Text" -ForegroundColor Cyan }

function Use-OwnFolders {
    # For this process and everything it starts: home, AppData, temp, model store inside .\runtime.
    $homeDir = Join-Path $Runtime 'home'
    foreach ($dir in @("$homeDir\AppData\Roaming", "$homeDir\AppData\Local", "$Runtime\temp", "$Runtime\models", $Downloads)) {
        New-Item -ItemType Directory -Force $dir | Out-Null
    }
    $env:USERPROFILE = $homeDir
    $env:HOME = $homeDir
    $env:APPDATA = "$homeDir\AppData\Roaming"
    $env:LOCALAPPDATA = "$homeDir\AppData\Local"
    $env:TEMP = "$Runtime\temp"
    $env:TMP = "$Runtime\temp"
    $env:OLLAMA_MODELS = "$Runtime\models"
    $env:OLLAMA_HOST = $OllamaAddress
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:PYTHONNOUSERSITE = '1'
}

function Get-File($Url, $Path) {
    Write-Host "Downloading $Url"
    & curl.exe -L --fail --silent --show-error -o $Path $Url
    if ($LASTEXITCODE -ne 0) { throw "Download failed: $Url" }
}

function Expand-Zip($Zip, $Destination) {
    # tar.exe (part of Windows) unpacks zip files and overwrites what a stopped earlier run left behind.
    New-Item -ItemType Directory -Force $Destination | Out-Null
    & tar.exe -xf $Zip -C $Destination
    if ($LASTEXITCODE -ne 0) { throw "Could not unpack $Zip" }
}

function Get-Ollama {
    # ollama.exe sits at the top of the release zip; searched in case a later zip nests it.
    $exe = Get-ChildItem $OllamaDir -Recurse -Filter 'ollama.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($exe) { return $exe.FullName } else { return $null }
}

function Test-Port($HostName, $Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try { return $client.ConnectAsync($HostName, $Port).Wait(3000) } catch { return $false } finally { $client.Dispose() }
}

function Start-Ollama {
    $process = Start-Process -FilePath (Get-Ollama) -ArgumentList 'serve' -WindowStyle Minimized -PassThru
    for ($i = 0; $i -lt 60; $i++) {
        & curl.exe --silent --fail "http://$OllamaAddress/api/version" | Out-Null
        if ($LASTEXITCODE -eq 0) { return $process }
        Start-Sleep -Seconds 1
    }
    Stop-Process $process -ErrorAction SilentlyContinue
    throw 'Ollama did not start within 60 s (see its minimized window).'
}

switch ($Action) {
    'check' {
        # Read-only: writes nothing (env.bat only creates the empty runtime folders).
        Title 'This PC'
        $os = Get-CimInstance Win32_OperatingSystem
        "$env:COMPUTERNAME, $($os.Caption) $($os.Version), RAM $([math]::Round($os.TotalVisibleMemorySize / 1MB)) GB"
        Title 'Graphics cards'
        Get-CimInstance Win32_VideoController | ForEach-Object { "$($_.Name), driver $($_.DriverVersion)" }
        $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
        if ($smi) {
            & $smi.Source --query-gpu=name,memory.total,memory.used,utilization.gpu --format=csv
            'Programs using the NVIDIA GPU:'
            & $smi.Source --query-compute-apps=process_name,used_memory --format=csv,noheader
        } else { 'nvidia-smi not found' }
        Title 'Free disk space where this folder is'
        $drive = Get-PSDrive ((Resolve-Path $Here).Drive.Name)
        "$([math]::Round($drive.Free / 1GB)) GB free on $($drive.Name): (setup needs about 9 GB while it runs, 7 GB after)"
        Title 'Moverse'
        $moverse = Get-Process | Where-Object { $_.ProcessName -match 'moverse' }
        if ($moverse) { $moverse | ForEach-Object { "running: $($_.ProcessName) (process $($_.Id))" } } else { 'no process with "moverse" in its name is running' }
        Title 'Network addresses of this PC'
        Get-CimInstance Win32_NetworkAdapterConfiguration -Filter 'IPEnabled=true' | ForEach-Object {
            "$($_.Description): $($_.IPAddress -join ', ')  mask $($_.IPSubnet -join ', ')"
        }
        Title 'Internet (needed only for setup)'
        foreach ($target in 'www.python.org', 'pypi.org', 'files.pythonhosted.org', 'github.com', 'registry.ollama.ai') {
            "${target}: $(if (Test-Port $target 443) { 'reachable' } else { 'NOT reachable' })"
        }
        foreach ($tool in 'curl.exe', 'tar.exe') {
            "${tool}: $(if (Get-Command $tool -ErrorAction SilentlyContinue) { 'present' } else { 'MISSING' })"
        }
        Title 'Setup state of this folder'
        "Python:       $(if (Test-Path $Python) { 'ready' } else { 'missing (run 2_setup.bat)' })"
        "Ollama:       $(if (Get-Ollama) { 'ready' } else { 'missing (run 2_setup.bat)' })"
        "Vision model: $(if (Test-Path $ModelManifest) { 'ready' } else { 'missing (run 2_setup.bat)' })"
        "Settings:     $(if (Test-Path $Settings) { Get-Content $Settings -Raw } else { 'not set yet (4_run.bat asks for them)' })"
    }

    'setup' {
        Use-OwnFolders

        Title 'Python 3.11.9 (portable)'
        if (-not (Test-Path $Python)) {
            $zip = Join-Path $Downloads 'python.zip'
            Get-File $PythonUrl $zip
            Expand-Zip $zip $PythonDir
            # The portable Python only searches the folders listed in this file.
            Set-Content -Encoding ASCII (Join-Path $PythonDir 'python311._pth') @('python311.zip', '.', 'Lib\site-packages')
            Remove-Item $zip
        }
        New-Item -ItemType Directory -Force $SitePackages | Out-Null
        'ready'

        foreach ($wheel in $Wheels) {
            $name, $version = $wheel
            Title "$name $version"
            if (Test-Path (Join-Path $SitePackages "$($name -replace '-', '_')-$version.dist-info")) { 'ready'; continue }
            $release = (& curl.exe --silent --fail "https://pypi.org/pypi/$name/$version/json") | Out-String | ConvertFrom-Json
            $file = $release.urls | Where-Object { $_.filename -like '*win_amd64.whl' -and ($_.filename -like '*cp311*' -or $_.filename -like '*abi3*') } | Select-Object -First 1
            if (-not $file) { throw "No Windows package of $name $version for Python 3.11" }
            $path = Join-Path $Downloads $file.filename
            Get-File $file.url $path
            if ((Get-FileHash $path -Algorithm SHA256).Hash -ne $file.digests.sha256) { throw "Checksum of $($file.filename) does not match PyPI" }
            Expand-Zip $path $SitePackages  # a wheel is a zip file; unpacked it is the installed package
            Remove-Item $path
            'ready'
        }

        Title "Ollama $OllamaVersion (portable, 1.6 GB download, 3.2 GB unpacked)"
        if (-not (Get-Ollama)) {
            $base = "https://github.com/ollama/ollama/releases/download/$OllamaVersion"
            $zip = Join-Path $Downloads 'ollama-windows-amd64.zip'
            Get-File "$base/ollama-windows-amd64.zip" $zip
            $sums = (& curl.exe -L --silent --fail "$base/sha256sum.txt") | Out-String
            $expected = ($sums -split "`n" | Where-Object { $_ -match 'ollama-windows-amd64\.zip\s*$' } | ForEach-Object { ($_ -split '\s+')[0] }) | Select-Object -First 1
            if (-not $expected -or (Get-FileHash $zip -Algorithm SHA256).Hash -ne $expected) { throw 'Checksum of the Ollama download does not match the release' }
            Expand-Zip $zip $OllamaDir
            Remove-Item $zip
        }
        'ready'

        Title "Vision model $Model (3.3 GB download)"
        if (-not (Test-Path $ModelManifest)) {
            $server = Start-Ollama
            try {
                & (Get-Ollama) pull $Model
                if ($LASTEXITCODE -ne 0) { throw "Download of $Model failed" }
            } finally { Stop-Process $server -ErrorAction SilentlyContinue }
        }
        'ready'

        Title 'Check that the Python packages load'
        & $Python -c "import numpy, cv2, depthai; print('numpy', numpy.__version__, '| opencv', cv2.__version__, '| depthai', depthai.__version__)"
        if ($LASTEXITCODE -ne 0) { throw 'The Python packages do not load' }
        Title 'Setup done'
    }

    'cameras' {
        Use-OwnFolders
        if (-not (Test-Path $Python)) { throw 'Run 2_setup.bat first.' }
        & $Python (Join-Path $Here 'find_cameras.py') @Cameras
    }

    'run' {
        Use-OwnFolders
        if (-not (Test-Path $ModelManifest)) { throw 'Run 2_setup.bat first.' }
        if (-not (Test-Path $Settings)) {
            Title 'Settings (asked once, saved in mrlab_camera_service.local.json in this folder)'
            $sendTo = Read-Host 'Address and port of the Unreal PC (address:port)'
            $camera = Read-Host 'Frontal camera: ID or address from 3_find_cameras.bat'
            @{ send_to = $sendTo.Trim(); oak_device = $camera.Trim() } | ConvertTo-Json | Set-Content -Encoding ASCII $Settings
        }
        Title 'Starting the vision model (minimized window "ollama")'
        $server = Start-Ollama
        try {
            Title 'Camera service (Ctrl+C stops it)'
            & $Python (Join-Path $Here 'mrlab_camera_service.py') --source $Source
        } finally {
            Stop-Process $server -ErrorAction SilentlyContinue
        }
    }
}
