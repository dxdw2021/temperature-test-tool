# Tesseract 7段数码管训练脚本
# 使用方法：
# 1. 先将标注好的 .tif + .box 文件放到 train_data 文件夹
# 2. 修改下方 $fontName 和 $langName 为你的命名
# 3. 在 PowerShell 中运行此脚本

param(
    [string]$trainDir = ".",
    [string]$langName = "seg7",
    [string]$fontName = "lcd",
    [string]$tesseractDir = "D:\Program Files\Tesseract-OCR"
)

$ErrorActionPreference = "Continue"
$oldPath = $env:Path
$env:Path = "$tesseractDir;$env:Path"
$env:TESSDATA_PREFIX = "$tesseractDir\tessdata"

Write-Host "=== Tesseract 7段数码管字库训练 ===" -ForegroundColor Cyan
Write-Host "训练目录: $trainDir"
Write-Host "语言名: $langName"
Write-Host "字体名: $fontName"
Write-Host "Tesseract: $tesseractDir"
Write-Host ""

# 检查 .box 文件
$boxFiles = Get-ChildItem -Path $trainDir -Filter "*.box" | Select-Object -ExpandProperty Name
if (-not $boxFiles) {
    Write-Host "错误: 未找到 .box 文件，请先用 jTessBoxEditor 标注" -ForegroundColor Red
    exit 1
}
Write-Host "找到 $($boxFiles.Count) 个 .box 文件" -ForegroundColor Green

# Step 1: 生成 unicharset
Write-Host "`n[Step 1/5] 生成 unicharset..." -ForegroundColor Yellow
Push-Location $trainDir
& "$tesseractDir\unicharset_extractor.exe" *.box
if ($LASTEXITCODE -ne 0) { Write-Host "  unicharset_extractor 失败" -ForegroundColor Red }
else { Write-Host "  unicharset 生成成功" -ForegroundColor Green }
Pop-Location

# Step 2: 创建 font_properties
$fpPath = Join-Path $trainDir "font_properties"
"$fontName 0 0 0 0 0" | Set-Content -Path $fpPath -NoNewline
Write-Host "`n[Step 2/5] 创建 font_properties: $fontName" -ForegroundColor Yellow

# Step 3: 生成 .tr 文件
Write-Host "`n[Step 3/5] 生成 .tr 训练文件..." -ForegroundColor Yellow
Push-Location $trainDir
$tifFiles = Get-ChildItem -Path $trainDir -Filter "*.tif" | Select-Object -ExpandProperty Name
foreach ($tif in $tifFiles) {
    $base = [System.IO.Path]::GetFileNameWithoutExtension($tif)
    Write-Host "  处理: $tif -> $base.tr"
    & "$tesseractDir\tesseract.exe" $tif $base nobatch box.train
}
Pop-Location

# Step 4: 聚集训练数据
Write-Host "`n[Step 4/5] 聚集训练数据..." -ForegroundColor Yellow
Push-Location $trainDir
& "$tesseractDir\cntraining.exe" .
& "$tesseractDir\mftraining.exe" -F font_properties -U unicharset -O "$langName.unicharset" *.tr
Pop-Location

# Step 5: 合并成 traineddata
Write-Host "`n[Step 5/5] 合并生成 $langName.traineddata..." -ForegroundColor Yellow
Push-Location $trainDir
& "$tesseractDir\combine_tessdata.exe" "$langName."
Pop-Location

# 复制到 tessdata
$outputFile = Join-Path $trainDir "$langName.traineddata"
if (Test-Path $outputFile) {
    $targetDir = "$tesseractDir\tessdata"
    Copy-Item $outputFile $targetDir -Force
    Write-Host "`n=== 训练完成! ===" -ForegroundColor Cyan
    Write-Host "已复制到: $targetDir\$langName.traineddata" -ForegroundColor Green
    Write-Host ""
    Write-Host "测试命令:" -ForegroundColor White
    Write-Host "  tesseract test.png output -l $langName --psm 7" -ForegroundColor Gray
} else {
    Write-Host "训练失败: $outputFile 未生成" -ForegroundColor Red
}

$env:Path = $oldPath
pause
