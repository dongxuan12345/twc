# -*- coding: utf-8 -*-
# 神经网络文献追踪看板 —— 一键启动脚本（由 启动看板.bat 调用）
# 关键改进：自动寻找 Python（PATH 里没有也能找到），全过程写日志，出错窗口不关闭。

$ErrorActionPreference = 'Continue'
Set-Location -Path $PSScriptRoot

$logPath = Join-Path $PSScriptRoot '启动日志.txt'
"==== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====" | Set-Content -Path $logPath -Encoding UTF8

function Say($msg) {
    Write-Host $msg
    try { Add-Content -Path $logPath -Value $msg -Encoding UTF8 } catch {}
}

Say "============================================================"
Say "  神经网络文献追踪看板 · 启动器"
Say "============================================================"
Say ""

# ---------------- 1. 找 Python（PATH → py 启动器 → 常见安装目录）----------------
function Find-Python {
    $candidates = @()

    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
    $cmd2 = Get-Command py -ErrorAction SilentlyContinue
    if ($cmd2) { $candidates += $cmd2.Source }

    $patterns = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python*\python.exe'),
        'C:\Python3*\python.exe',
        'C:\Program Files\Python3*\python.exe',
        'C:\Program Files (x86)\Python3*\python.exe',
        'D:\Python3*\python.exe'
    )
    foreach ($p in $patterns) {
        Get-ChildItem -Path $p -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending |
            ForEach-Object { $candidates += $_.FullName }
    }

    foreach ($c in $candidates) {
        try {
            $lines = & $c -c "import sys; print(sys.version_info[0]*100+sys.version_info[1])" 2>$null
            $code = ($lines | Select-Object -First 1)
            if ($LASTEXITCODE -eq 0 -and $code -and [int]$code -ge 309) {
                return @{ Exe = $c; Code = [int]$code }
            }
        } catch { }
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    Say "[错误] 没有找到 Python 3.9 或更高版本。"
    Say ""
    Say "       请安装：https://www.python.org/downloads/"
    Say "       安装时务必勾选 'Add python.exe to PATH'。"
    Say "       装完关掉本窗口，重新双击 启动看板.bat。"
    exit 1
}
Say "[1/4] Python 就绪：$($py.Exe)"
Say "      版本代号：$($py.Code)（>=309 表示 3.9 以上）"

# ---------------- 2. 虚拟环境 ----------------
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Say "[2/4] 首次运行，正在创建虚拟环境 .venv（约 10 秒）…"
    & $py.Exe -m venv .venv
    if (-not (Test-Path $venvPython)) {
        Say "[错误] 创建虚拟环境失败。"
        exit 1
    }
} else {
    Say "[2/4] 虚拟环境已存在。"
}

# ---------------- 3. 依赖 ----------------
Say "[3/4] 检查依赖…"
& $venvPython -c "import streamlit, openai, dotenv, pandas" 2>$null
if ($LASTEXITCODE -ne 0) {
    Say "      依赖不完整，开始安装（1-3 分钟，需要联网）…"
    & $venvPython -m pip install --upgrade pip --quiet
    & $venvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Say "[错误] 依赖安装失败。"
        Say "       换国内镜像重试："
        Say "       .venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple"
        exit 1
    }
} else {
    Say "      依赖完整。"
}

# 启动前做一次静态导入自检，把语法/依赖问题提前暴露
& $venvPython -c "import src.pipeline, src.storage, src.llm_extractor, src.translator, src.i18n" 2>$null
if ($LASTEXITCODE -ne 0) {
    Say "[错误] 模块导入失败，下面是详细报错："
    & $venvPython -c "import src.pipeline, src.storage, src.llm_extractor, src.translator, src.i18n"
    exit 1
}

# ---------------- 4. 启动 ----------------
$envFile = Join-Path $PSScriptRoot '.env'
if (Test-Path $envFile) {
    Say "      已找到 .env（API Key 会从里面读取）"
} else {
    Say "[警告] 没有 .env，界面里会显示「未配置 API Key」。"
}

Say "[4/4] 启动 Streamlit，浏览器会自动打开 http://localhost:8501"
Say "      关闭本窗口或按 Ctrl+C 可停止服务。"
Say ""

& $venvPython -m streamlit run app.py --server.port 8501 --browser.gatherUsageStats false

Say ""
Say "服务已停止。完整日志已写入：启动日志.txt"
