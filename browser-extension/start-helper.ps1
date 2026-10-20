$ErrorActionPreference = "Stop"

$helperDir = $PSScriptRoot
$environmentDir = Join-Path $helperDir ".venv"
$pythonPath = Join-Path $environmentDir "Scripts\python.exe"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Chưa tìm thấy Python Launcher. Hãy cài Python 3.10+ rồi chạy lại script này."
}

if (-not (Test-Path -LiteralPath $pythonPath)) {
    Write-Host "Đang tạo môi trường riêng và cài yt-dlp lần đầu…"
    & py -3 -m venv $environmentDir
    & $pythonPath -m pip install -r (Join-Path $helperDir "requirements.txt")
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Warning "Chưa tìm thấy FFmpeg trên PATH. Cài FFmpeg rồi mở PowerShell mới để tải video có chất lượng cao nhất."
}

& $pythonPath (Join-Path $helperDir "local_video_helper.py")
