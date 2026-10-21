param(
    [switch]$SkipInstall,
    [switch]$SkipModelCache,
    [switch]$Verify
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot ".venv312\Scripts\python.exe"
$pyinstaller = Join-Path $projectRoot ".venv312\Scripts\pyinstaller.exe"
$buildDir = Join-Path $projectRoot "build"
$distRoot = Join-Path $projectRoot "dist"
$releaseDir = Join-Path $distRoot "ScreenTranslator"
$modelsSource = Join-Path $env:USERPROFILE ".paddleocr\whl"
$modelsTarget = Join-Path $releaseDir "models\paddleocr\whl"

Set-Location $projectRoot

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python not found: $python"
}
if (-not $SkipInstall -and -not (Test-Path -LiteralPath $pyinstaller)) {
    & $python -m pip install pyinstaller
}
if (-not (Test-Path -LiteralPath $pyinstaller)) {
    throw "PyInstaller not found in .venv312. Run without -SkipInstall."
}

$requiredModels = @(
    "det\ch\ch_PP-OCRv4_det_infer\inference.pdmodel",
    "rec\ch\ch_PP-OCRv4_rec_infer\inference.pdmodel"
)
foreach ($relativePath in $requiredModels) {
    $modelFile = Join-Path $modelsSource $relativePath
    if (-not (Test-Path -LiteralPath $modelFile)) {
        throw "Missing OCR model: $modelFile. Run main.py once with network access to download PP-OCRv4."
    }
}

& $pyinstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name "ScreenTranslator" `
    --paths $projectRoot `
    --collect-all "paddleocr" `
    --collect-all "paddle" `
    --hidden-import "PIL._tkinter_finder" `
    --exclude-module "matplotlib" `
    --exclude-module "IPython" `
    --exclude-module "notebook" `
    --exclude-module "tests" `
    --distpath $distRoot `
    --workpath (Join-Path $buildDir "pyinstaller") `
    --specpath $buildDir `
    (Join-Path $projectRoot "main.py")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

if (-not $SkipModelCache) {
    if (-not (Test-Path -LiteralPath $modelsTarget)) {
        New-Item -ItemType Directory -Path $modelsTarget -Force | Out-Null
    }
    Get-ChildItem -LiteralPath $modelsSource -Force | Copy-Item -Destination $modelsTarget -Recurse -Force
}

if ($Verify) {
    $previousAppDir = $env:SCREEN_TRANSLATOR_APP_DIR
    try {
        $env:SCREEN_TRANSLATOR_APP_DIR = $releaseDir
        $verification = @'
from PIL import Image, ImageDraw

from config import bundled_ocr_models_dir
from ocr import recognize_text, warm_up_ocr, using_bundled_models

assert using_bundled_models(), "bundled OCR models were not found"
print("models:", bundled_ocr_models_dir())
warm_up_ocr()
image = Image.new("RGB", (640, 120), "white")
ImageDraw.Draw(image).text((24, 44), "Screen translator OCR test 123", fill="black")
print("recognized:", recognize_text(image))
'@
        & $python -c $verification
        if ($LASTEXITCODE -ne 0) {
            throw "Python OCR verification failed with exit code $LASTEXITCODE"
        }
    } finally {
        $env:SCREEN_TRANSLATOR_APP_DIR = $previousAppDir
    }
}

Write-Host ""
Write-Host "Build complete: $releaseDir\ScreenTranslator.exe"
Write-Host "Ship the entire ScreenTranslator folder, including models."
