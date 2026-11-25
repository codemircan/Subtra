# Subtra — Windows dagitim betigi
# Kullanim: powershell -ExecutionPolicy Bypass -File build.ps1
#
# Uretilenler:
#   dist\Subtra\            -> calistirilabilir klasor
#   Subtra-portable.zip     -> tasinabilir zip

param(
    [switch]$SkipTests,
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Write-Step($text) {
    Write-Host ""
    Write-Host "=== $text ===" -ForegroundColor Cyan
}

function Require-Command($name, $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "$name bulunamadi. $hint"
    }
}

Write-Step "Ortam kontrolu"
$python = "py"
Require-Command $python "Python kurun: https://www.python.org/downloads/windows/"

$version = & py -3.14 -c "import sys; print(sys.version.split()[0])" 2>$null
if (-not $version) {
    $version = & py -c "import sys; print(sys.version.split()[0])"
}
Write-Host "Python: $version"

Write-Step "Bagimliliklar"
& py -3.14 -m pip install --upgrade pip --quiet
& py -3.14 -m pip install -r requirements.txt --quiet
& py -3.14 -m pip install pyinstaller --quiet
Write-Host "Bagimliliklar hazir."

if (-not $SkipTests) {
    Write-Step "Testler"
    & py -3.14 test/test_subtitles.py
    if ($LASTEXITCODE -ne 0) { throw "Altyazi testleri basarisiz." }
} else {
    Write-Host "Testler atlandi (-SkipTests)."
}

Write-Step "Eski cikti temizleniyor"
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

Write-Step "PyInstaller"
& py -3.14 -m PyInstaller Subtra.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller basarisiz." }

$dist = Join-Path $root "dist\Subtra"
if (-not (Test-Path $dist)) { throw "Cikti klasoru bulunamadi: $dist" }

Write-Step "FFmpeg kopyalaniyor"
$localFfmpeg = Join-Path $root "ffmpeg\bin\ffmpeg.exe"
$localProbe = Join-Path $root "ffmpeg\bin\ffprobe.exe"
if ((Test-Path $localFfmpeg) -and (Test-Path $localProbe)) {
    $target = Join-Path $dist "ffmpeg\bin"
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    Copy-Item $localFfmpeg $target -Force
    Copy-Item $localProbe $target -Force
    Write-Host "FFmpeg ciktiya eklendi (PATH gerekmez)."
} else {
    Write-Warning "ffmpeg\bin bulunamadi; uygulama ilk acilista otomatik indirecek."
}

Write-Step "README kopyalaniyor"
Copy-Item (Join-Path $root "README.md") $dist -Force -ErrorAction SilentlyContinue

if (-not $SkipZip) {
    Write-Step "Tasinabilir zip"
    $zip = Join-Path $root "Subtra-portable.zip"
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
    Compress-Archive -Path (Join-Path $dist "*") -DestinationPath $zip -CompressionLevel Optimal
    $sizeMb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
    Write-Host "Olusturuldu: $zip ($sizeMb MB)"}

Write-Step "Bitti"
Write-Host "Klasor : $dist" -ForegroundColor Green
Write-Host "Exe    : $(Join-Path $dist 'Subtra.exe')" -ForegroundColor Green
Write-Host ""
Write-Host "Not: Modeller ilk kullanimda indirilir ve su klasore yazilir:"
Write-Host "     $env:LOCALAPPDATA\Subtra\models"