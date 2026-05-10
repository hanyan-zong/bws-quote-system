#Requires -Version 5
# ============================================================
# BWS - 上传备份 ZIP 到 GitHub Releases
# ============================================================

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Continue'
Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  BWS - 上传备份 ZIP 到 GitHub Releases" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  为什么用 Releases 而不是直接放仓库?" -ForegroundColor White
Write-Host "    - 你的 ZIP 每个 75MB, 放仓库会让 git clone 很慢" -ForegroundColor White
Write-Host "    - GitHub 单文件 100MB 上限, 用 Releases 可到 2GB" -ForegroundColor White
Write-Host "    - Releases 有版本管理, 更适合发布物" -ForegroundColor White
Write-Host ""

# ----- 输入信息 -----
$ghUser = Read-Host "GitHub 用户名 [默认 hanyan-zong]"
if ([string]::IsNullOrWhiteSpace($ghUser)) { $ghUser = "hanyan-zong" }

$repoName = Read-Host "GitHub 仓库名 [默认 bwsb-]"
if ([string]::IsNullOrWhiteSpace($repoName)) { $repoName = "bwsb-" }

$tagName = Read-Host "发布版本号 [默认 v0.8.4]"
if ([string]::IsNullOrWhiteSpace($tagName)) { $tagName = "v0.8.4" }

$pat = Read-Host "你的 GitHub PAT (ghp_xxx)" -AsSecureString
$patPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($pat))
if ([string]::IsNullOrWhiteSpace($patPlain)) {
    Write-Host "[致命] PAT 不能为空" -ForegroundColor Red
    Write-Host "生成: https://github.com/settings/tokens/new?description=bws-quote-push&scopes=repo" -ForegroundColor Yellow
    Read-Host "按回车退出"; exit 1
}

# ----- 找最新的 zip 文件 -----
$zips = Get-ChildItem -Path . -Filter "预报价系统B端版本_*.zip" | Sort-Object LastWriteTime -Descending
if (-not $zips) {
    Write-Host "[致命] 没找到 预报价系统B端版本_*.zip" -ForegroundColor Red
    Read-Host "按回车退出"; exit 1
}
$zipFile = $zips[0]
$zipSizeMB = [math]::Round($zipFile.Length / 1MB, 1)
Write-Host ""
Write-Host "找到备份: $($zipFile.Name)" -ForegroundColor Green
Write-Host "大小: $zipSizeMB MB" -ForegroundColor Green
Write-Host ""

$confirm = Read-Host "确认上传到 https://github.com/$ghUser/$repoName/releases/$tagName ? [Y/n]"
if ($confirm -eq 'n' -or $confirm -eq 'N') { Write-Host "已取消"; exit 0 }

# ----- 创建 Release -----
Write-Host ""
Write-Host "[1/2] 创建 GitHub Release ..." -ForegroundColor Yellow

$headers = @{
    Authorization = "Bearer $patPlain"
    Accept = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}
$body = @{
    tag_name = $tagName
    name = "BWS 预报价系统 $tagName"
    body = "完整代码 + 备份压缩包. 包含 5 角色权限/AI 一键报价/赌自费 12 策略/导出三件套等全部 v0.8.4 功能."
    draft = $false
    prerelease = $false
} | ConvertTo-Json

$uploadUrl = $null
try {
    $r = Invoke-RestMethod -Method Post `
        -Uri "https://api.github.com/repos/$ghUser/$repoName/releases" `
        -Headers $headers -Body $body -ContentType 'application/json'
    $uploadUrl = ($r.upload_url -replace '\{.*\}', '')
    Write-Host "  ✓ Release 已创建. ID: $($r.id)" -ForegroundColor Green
} catch {
    if ($_.Exception.Response.StatusCode.value__ -eq 422) {
        Write-Host "  [警告] tag $tagName 已存在, 复用现有 Release" -ForegroundColor Yellow
        try {
            $r2 = Invoke-RestMethod -Method Get `
                -Uri "https://api.github.com/repos/$ghUser/$repoName/releases/tags/$tagName" `
                -Headers $headers
            $uploadUrl = ($r2.upload_url -replace '\{.*\}', '')
            Write-Host "  ✓ 复用 Release ID: $($r2.id)" -ForegroundColor Green
        } catch {
            Write-Host "  [致命] 拉取已有 Release 失败: $($_.Exception.Message)" -ForegroundColor Red
            Read-Host "按回车退出"; exit 1
        }
    } else {
        Write-Host "  [致命] Release 创建失败:" -ForegroundColor Red
        Write-Host "    $($_.Exception.Message)" -ForegroundColor Red
        Read-Host "按回车退出"; exit 1
    }
}

# ----- 上传 ZIP -----
Write-Host ""
Write-Host "[2/2] 上传 $zipSizeMB MB ZIP (大概 1-3 分钟, 取决于网速) ..." -ForegroundColor Yellow
try {
    $r3 = Invoke-RestMethod -Method Post `
        -Uri "$uploadUrl?name=$([System.Uri]::EscapeDataString($zipFile.Name))" `
        -Headers $headers `
        -InFile $zipFile.FullName `
        -ContentType 'application/zip'
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  ✅ 全部完成!" -ForegroundColor Green
    Write-Host "" -ForegroundColor Green
    Write-Host "  下载地址: $($r3.browser_download_url)" -ForegroundColor Green
    Write-Host "" -ForegroundColor Green
    Write-Host "  Release 页面: https://github.com/$ghUser/$repoName/releases/tag/$tagName" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Start-Process "https://github.com/$ghUser/$repoName/releases/tag/$tagName"
} catch {
    Write-Host "  [失败] 上传出错: $($_.Exception.Message)" -ForegroundColor Red
    Read-Host "按回车退出"; exit 1
}

Read-Host "按回车退出"
