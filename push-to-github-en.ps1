#Requires -Version 5
# Pure ASCII version - no Chinese chars to avoid encoding issues
# Run with: powershell -ExecutionPolicy Bypass -File .\push-to-github-en.ps1

$ErrorActionPreference = 'Continue'
Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host "============================================================"
Write-Host "  BWS Quote System - Push to GitHub (ASCII safe)"
Write-Host "============================================================"
Write-Host ""

# Step 1: git check
try { git --version | Out-Null } catch {
    Write-Host "[FATAL] git not installed: https://git-scm.com/download/win"
    Read-Host "Press Enter to exit"; exit 1
}
Write-Host "[1/6] git OK"

# Step 2: clean old .git
if (Test-Path ".git") {
    Write-Host "[2/6] Removing old .git ..."
    Remove-Item -Recurse -Force ".git" -ErrorAction SilentlyContinue
}
if (Test-Path ".git") {
    Write-Host "[FATAL] cannot remove .git (file in use?). Close VSCode/git tools and retry."
    Read-Host "Press Enter to exit"; exit 1
}
Write-Host "[2/6] .git cleaned"

# Step 3: init
git init -b main | Out-Null
git config user.email "101797074@qq.com"
git config user.name "hanyan-zong"
git config core.autocrlf input
git config core.quotepath false
Write-Host "[3/6] git init done"

# Step 4: input
Write-Host ""
$ghUser = Read-Host "GitHub username [press Enter for hanyan-zong]"
if ([string]::IsNullOrWhiteSpace($ghUser)) { $ghUser = "hanyan-zong" }

$repoName = Read-Host "GitHub repo name [press Enter for bwsb-]"
if ([string]::IsNullOrWhiteSpace($repoName)) { $repoName = "bwsb-" }

$remoteUrl = "https://github.com/$ghUser/$repoName.git"
Write-Host "[4/6] Remote URL: $remoteUrl"

# Step 5: add + commit
Write-Host ""
Write-Host "[5/6] Adding files + commit ..."
git add . 2>&1 | Out-Null

$fileCount = (git status -s | Measure-Object).Count
Write-Host "  About to commit $fileCount files"

$confirm = Read-Host "Confirm commit? [Y/n]"
if ($confirm -eq 'n' -or $confirm -eq 'N') { Write-Host "Cancelled"; exit 0 }

git commit -m "BWS Quote System v0.8.4 - initial commit" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FATAL] commit failed"
    Read-Host "Press Enter to exit"; exit 1
}
Write-Host "[5/6] Commit OK"

# Step 6: push
Write-Host ""
Write-Host "[6/6] Push to GitHub"
Write-Host ""
Write-Host "  Username: $ghUser"
Write-Host "  Password: paste your PAT (ghp_xxx, NOT GitHub password)"
Write-Host "  Generate PAT: https://github.com/settings/tokens/new?description=bws-quote-push&scopes=repo"
Write-Host ""
Read-Host "Ready? Press Enter to start push"

git remote remove origin 2>$null
git remote add origin $remoteUrl

# Force push (overwrite GitHub's auto-generated README)
git push -f origin main

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "============================================================"
    Write-Host "[FAILED] Push failed"
    Write-Host ""
    Write-Host "Common errors:"
    Write-Host "  - 'Authentication failed':"
    Write-Host "      Password must be PAT (ghp_xxx), NOT GitHub password"
    Write-Host "      Generate: https://github.com/settings/tokens/new?description=bws-quote-push&scopes=repo"
    Write-Host "  - 'Repository not found':"
    Write-Host "      Repo name wrong (you typed: $repoName)"
    Write-Host "      Or username wrong (you typed: $ghUser)"
    Write-Host "============================================================"
    Read-Host "Press Enter to exit"; exit 1
}

Write-Host ""
Write-Host "============================================================"
Write-Host "  SUCCESS!"
Write-Host ""
$repoUrl = "https://github.com/$ghUser/$repoName"
Write-Host "  Repository: $repoUrl"
Write-Host ""
Write-Host "  Next time you change code, just run:"
Write-Host "    git add ."
Write-Host "    git commit -m 'what changed'"
Write-Host "    git push"
Write-Host "============================================================"
Write-Host ""

Start-Process $repoUrl
Read-Host "Press Enter to exit"
