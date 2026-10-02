$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$version = (Get-Content (Join-Path $projectRoot "VERSION") -Raw).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+$') {
    throw "VERSION doit respecter le format semver X.Y.Z."
}
$buildRoot = Join-Path $projectRoot "build"
$buildId = [guid]::NewGuid().ToString("N")
$workRoot = Join-Path $buildRoot "work-$buildId"
$distRoot = Join-Path $buildRoot "dist-$buildId"
$appBundle = Join-Path $distRoot "ASN Wave Monitor"
$installerOutput = Join-Path $projectRoot "dist"
$innoCompiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue

if (-not $innoCompiler) {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    $compilerPath = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($compilerPath) {
        $innoCompiler = @{ Source = $compilerPath }
    }
}

if (-not $innoCompiler) {
    throw "Inno Setup 6 est requis. Installez-le puis relancez ce script."
}

Push-Location $projectRoot
try {
    & py -m PyInstaller --version
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller est requis. Installez-le avec 'py -m pip install --user pyinstaller'."
    }

    & py -c "import matplotlib, numpy, openpyxl, scipy, serial"
    if ($LASTEXITCODE -ne 0) {
        throw "Les dépendances de requirements.txt doivent être installées avant le build."
    }

    & py -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --onedir `
        --name "ASN Wave Monitor" `
        --distpath $distRoot `
        --workpath $workRoot `
        --specpath $buildRoot `
        --add-data "${projectRoot}\config.json;." `
        --add-data "${projectRoot}\rao;rao" `
        app.py
    if ($LASTEXITCODE -ne 0) {
        throw "La génération de l'application avec PyInstaller a échoué."
    }

    if (-not (Test-Path (Join-Path $appBundle "_internal\config.json"))) {
        throw "config.json est absent du bundle PyInstaller attendu."
    }
    if (-not (Test-Path (Join-Path $appBundle "_internal\rao\RAO_IOT_Arrival_Concrete_V0.xlsx"))) {
        throw "Le classeur RAO IOT est absent du bundle PyInstaller."
    }
    if (-not (Test-Path (Join-Path $appBundle "_internal\rao\RAO_ ASN_Ile de Molene_Cd=0.8.xlsx"))) {
        throw "Le classeur RAO Molène est absent du bundle PyInstaller."
    }

    New-Item -ItemType Directory -Force -Path $installerOutput | Out-Null
    $installerScript = Join-Path $projectRoot "packaging\installer.iss"
    & $innoCompiler.Source $installerScript `
        "/DAppSource=$appBundle" `
        "/DOutputDir=$installerOutput" `
        "/DAppVersion=$version"
    if ($LASTEXITCODE -ne 0) {
        throw "La compilation de l'installateur Inno Setup a échoué."
    }

    $installerPath = Join-Path $installerOutput "ASN-Wave-Monitor-Setup-v$version.exe"
    if (-not (Test-Path $installerPath)) {
        throw "L'installateur attendu n'a pas été généré: $installerPath"
    }
    Write-Host "Installateur créé: $installerPath"
}
finally {
    Pop-Location
}