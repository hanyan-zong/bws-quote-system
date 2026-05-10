#Requires -Version 5
# ============================================================
# BWS - 推送到 GitHub (PowerShell 版, 比 .bat 可靠)
# ============================================================

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Continue'
Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  BWS 预报价系统 - 推送到 GitHub" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ----- Step 1: git 检查 -----
try { git --version | Out-Null } catch {
    Write-Host "[致命] 没装 git: https://git-scm.com/download/win" -ForegroundColor Red
    Read-Host "按回车退出"; exit 1
}
Write-Host "[1/7] git 已安装" -ForegroundColor Green

# ----- Step 2: 清理旧 .git -----
if (Test-Path ".git") {
    Write-Host "[2/7] 清理已有 .git ..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force ".git"
}
Write-Host "[2/7] .git 已清理" -ForegroundColor Green

# ----- Step 3: git init + 配置 -----
git init -b main | Out-Null
git config user.email "101797074@qq.com"
git config user.name "hanyan-zong"
git config core.autocrlf input
git config core.quotepath false
Write-Host "[3/7] git 已初始化" -ForegroundColor Green

# ----- Step 4: 仓库信息 -----
Write-Host ""
$ghUser = Read-Host "GitHub 用户名 [默认 hanyan-zong, 直接回车]"
if ([string]::IsNullOrWhiteSpace($ghUser)) { $ghUser = "hanyan-zong" }

$repoName = Read-Host "GitHub 仓库名 [默认 bwsb-, 直接回车]"
if ([string]::IsNullOrWhiteSpace($repoName)) { $repoName = "bwsb-" }

$remoteUrl = "https://github.com/$ghUser/$repoName.git"
Write-Host "[4/7] 远程仓库 URL: $remoteUrl" -ForegroundColor Green

# ----- Step 5: add + commit -----
Write-Host ""
Write-Host "[5/7] 添加文件 + commit ..." -ForegroundColor Yellow
git add .

$fileCount = (git status -s | Measure-Object).Count
Write-Host "  即将提交 $fileCount 个文件" -ForegroundColor White
Write-Host "  示例 (前 10 个):" -ForegroundColor White
git status -s | Select-Object -First 10 | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }

$confirm = Read-Host "确认 commit? [Y/n]"
if ($confirm -eq 'n' -or $confirm -eq 'N') { Write-Host "已取消"; exit 0 }

git commit -m "BWS 预报价系统 v0.8.4 - 完整代码 (5 角色权限/AI 一键报价/赌自费 12 策略/导出三件套)" | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[致命] commit 失败" -ForegroundColor Red
    Read-Host "按回车退出"; exit 1
}
Write-Host "[5/7] commit OK" -ForegroundColor Green

# ----- Step 6: 配 remote + 处理冲突 -----
Write-Host ""
Write-Host "[6/7] 配置 remote + 检查远程状态 ..." -ForegroundColor Yellow
git remote remove origin 2>$null
git remote add origin $remoteUrl

# 测试 fetch (匿名, 看 repo 是否存在 + 远程是否有 commit)
$env:GIT_TERMINAL_PROMPT = "0"
$lsRemote = git ls-remote origin main 2>&1
$env:GIT_TERMINAL_PROMPT = "1"
if ($lsRemote -match "fatal") {
    Write-Host "  [警告] 无法读取远程 (可能 repo 不存在 / 网络问题)" -ForegroundColor Yellow
    $remoteEmpty = $true
} elseif ($lsRemote -match "\S") {
    Write-Host "  远程已有 commit: $($lsRemote.Substring(0, 12))..." -ForegroundColor Yellow
    $remoteEmpty = $false
} else {
    Write-Host "  远程是空仓库" -ForegroundColor Green
    $remoteEmpty = $true
}

# ----- Step 7: push -----
Write-Host ""
Write-Host "[7/7] 推送到 GitHub" -ForegroundColor Yellow
Write-Host ""
Write-Host "  ★ Username: $ghUser" -ForegroundColor Cyan
Write-Host "  ★ Password: 请输你的 Personal Access Token (PAT, ghp_xxx)" -ForegroundColor Cyan
Write-Host "    (不是 GitHub 密码!)" -ForegroundColor Cyan
Write-Host "    没生成 PAT? 打开: https://github.com/settings/tokens/new?description=bws-quote-push&scopes=repo" -ForegroundColor Cyan
Write-Host ""
Read-Host "准备好 PAT 后, 按回车开始推送"

if (-not $remoteEmpty) {
    Write-Host ""
    Write-Host "  远程仓库已有 commit (可能是 GitHub 自动加的 README)" -ForegroundColor Yellow
    Write-Host "  → 强制覆盖远程 (推荐, 你的本地代码会替换 GitHub 上那个 README)" -ForegroundColor Yellow
    Write-Host ""
    git push -f origin main
} else {
    git push -u origin main
}

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host "[失败] 推送失败" -ForegroundColor Red
    Write-Host "" -ForegroundColor Red
    Write-Host "常见错误:" -ForegroundColor Red
    Write-Host "  - Authentication failed:" -ForegroundColor White
    Write-Host "      Password 必须填 PAT (ghp_xxx), 不是 GitHub 密码" -ForegroundColor White
    Write-Host "      生成: https://github.com/settings/tokens/new?description=bws-quote-push&scopes=repo" -ForegroundColor White
    Write-Host "  - Repository not found:" -ForegroundColor White
    Write-Host "      仓库名打错了 (你输的是: $repoName)" -ForegroundColor White
    Write-Host "      或 username 错 (你输的是: $ghUser)" -ForegroundColor White
    Write-Host "============================================================" -ForegroundColor Red
    Read-Host "按回车退出"; exit 1
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  ✅ 推送成功!" -ForegroundColor Green
Write-Host "" -ForegroundColor Green
$repoUrl = "https://github.com/$ghUser/$repoName"
Write-Host "  仓库地址: $repoUrl" -ForegroundColor Green
Write-Host "" -ForegroundColor Green
Write-Host "  接下来:" -ForegroundColor Green
Write-Host "    - 浏览器即将打开" -ForegroundColor Green
Write-Host "    - 上传备份 zip: 跑 .\上传Release到github.ps1" -ForegroundColor Green
Write-Host "    - 后续修改 3 行命令: git add . / git commit -m '...' / git push" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""

Start-Process $repoUrl
Read-Host "按回车退出"
