# ANI one-time setup for a new Windows machine. Run from the cloned repo:
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

foreach ($tool in 'python', 'ffmpeg', 'claude') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "ไม่พบ '$tool' บน PATH — ติดตั้งก่อน (Python 3.12+, ffmpeg, Claude Code) แล้วรันสคริปต์นี้ใหม่"
    }
}

$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Host '[1/4] สร้าง .venv'
    python -m venv (Join-Path $root '.venv')
}
Write-Host '[2/4] ติดตั้ง requirements.txt'
& $py -m pip install -q -r (Join-Path $root 'requirements.txt')
if ($LASTEXITCODE) { throw 'pip install ล้มเหลว' }

Write-Host "[3/4] ตั้ง ANI_ROOT = $root"
[Environment]::SetEnvironmentVariable('ANI_ROOT', $root, 'User')
$env:ANI_ROOT = $root

Write-Host '[4/4] ติดตั้งปลั๊กอิน Claude Code (ani@ani)'
claude plugin marketplace add $root
claude plugin install ani@ani

Write-Host "`nเสร็จแล้ว — เปิด terminal ใหม่ แล้วรัน 'claude' จากนั้นพิมพ์ /mcp เพื่อตรวจว่า ani-studio เชื่อมต่อ"
Write-Host 'ยังต้องทำเอง: คัดลอก .env (ถ้าใช้ API) และล็อกอิน Google Flow ในเครื่องนี้'
