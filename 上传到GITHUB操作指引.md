# 上传到 GitHub 操作指引(2026-05-10)

> 当前情况:你已经在 GitHub 创建了仓库 `bwsb-`(用户名 `hanyan-zong`)
> 仓库已有一个自动生成的 README — 我们的本地代码会**强制覆盖**它

---

## 🛑 第一件事 — 立刻去改密码

你之前在聊天里贴了 GitHub 密码 `iPhone17Air`(明文)。请马上做:

1. 改密码:https://github.com/settings/security
2. 开启 2FA(双因素认证):同一页

GitHub 现在强制要求 2FA,不开启迟早会被锁。

---

## 第一步 — 生成 Personal Access Token (PAT)

GitHub 不接受密码 push,必须用 PAT:

1. 打开:https://github.com/settings/tokens/new
2. **Note**:`bws-quote-push`
3. **Expiration**:`90 days`
4. **Select scopes**:**只勾 `repo`**(其他都不要勾)
5. 滑到底点 **Generate token**
6. 页面会显示一串 `ghp_xxxxxxxxxxx`(40 多字符)→ **立刻复制**(这是一次性显示)

把 PAT 临时存在记事本里,等下要用。

---

## 第二步 — 双击 [`推送到github.bat`](computer:///sessions/focused-sharp-bohr/mnt/balijob/预报价系统B端版本/推送到github.bat)

脚本会自动:
1. 检查 git 装没装
2. 删除沙箱遗留的破损 .git
3. `git init -b main`
4. 配置 `user.email = 101797074@qq.com` / `user.name = hanyan-zong`
5. `git add .` (按 .gitignore 排除 .env / .db / .zip 等)
6. 让你**输仓库名**:输入 `bwsb-`(注意末尾的 `-`)
7. fetch 远程,**检测到远程已有 commit**(那个 README),弹两个选项:
   - `[1]` 用本地完全覆盖远程(推荐)— GitHub 上的 README 会被我们的替换
   - `[2]` 合并远程到本地后再 push
8. `git commit` + `git push`
9. 推送时提示:
   - **Username**:`hanyan-zong`
   - **Password**:**粘贴 PAT**(`ghp_xxx...`)— 不是 GitHub 密码!
10. 成功 → 自动开浏览器到你的仓库页

---

## 第三步(可选)— 上传备份 Zip 到 Releases

普通 git 仓库**不应该**装大 zip(每个 75MB),应该用 GitHub Releases:

双击 [`上传Release到github.bat`](computer:///sessions/focused-sharp-bohr/mnt/balijob/预报价系统B端版本/上传Release到github.bat):

1. 仓库名输 `bwsb-`
2. 版本号输 `v0.8.4`(或回车用默认)
3. 输 PAT(就是步骤 1 那个)
4. 脚本自动:
   - 找当前目录最新的 `预报价系统B端版本_*.zip`
   - 调 GitHub API 创建 Release
   - 上传 ZIP 文件(75MB,大概 1-3 分钟)
   - 完成后自动打开 Release 页

你的 zip 之后会出现在:
`https://github.com/hanyan-zong/bwsb-/releases/tag/v0.8.4`

别人 clone 后可以从那里下载某个版本的快照。

---

## 文件清单确认

我准备好的文件(都在你 Windows 项目目录里):

```
预报价系统B端版本/
├── .gitignore                 ← 排除敏感文件(.env / .db / *.zip / __pycache__)
├── README.md                  ← 完整项目介绍(你 GitHub 仓库首页会显示这个)
├── 推送到github.bat            ← 一键 push 脚本(本次新增)
├── 上传Release到github.bat     ← 上传备份 zip 到 Releases(本次新增)
├── 上传到GITHUB操作指引.md      ← 本文档
├── bws-quote.bundle           ← Git bundle 备份(可选用法)
├── 一键启动.bat                ← 跑系统
├── 诊断并启动.bat              ← 自动诊断 + 启动
├── 全盘搜索并启动.bat          ← 找项目位置
├── 重置admin账号.bat            ← 紧急重置 admin
├── Dockerfile                 ← Docker 多阶段构建
├── docker-compose.yml         ← Compose 配置
├── .env.example               ← 环境变量模板(默认 admin/admin123)
├── backend/                   ← FastAPI 后端
├── frontend/                  ← Vue 3 前端
├── docs/                      ← 设计文档
├── samples/                   ← AI 解析测试样本
└── scripts/                   ← init_db 等运维脚本
```

排除的(不会上传到 GitHub):
- `.env`(含密码)
- `*.db`(数据库)
- `*.zip`(备份压缩包,单独走 Releases)
- `工作脚本备份_*/`(开发过程快照)
- `uploads/` `logs/` `__pycache__/` `.venv/`
- `ziAQZewW`(沙箱临时文件)

---

## 推送后会发生什么

1. **代码** → https://github.com/hanyan-zong/bwsb-(自动覆盖原 README)
2. **后续修改**:每次改完 3 行命令更新:
   ```powershell
   cd C:\Users\001\balijob\预报价系统B端版本
   git add .
   git commit -m "改了什么"
   git push
   ```
3. **PAT 管理**:用完可以在 https://github.com/settings/tokens 撤销

---

## 常见错误诊断

| 错误信息 | 解决 |
|---|---|
| `Authentication failed` | Password 必须填 PAT(`ghp_xxx`),不是 GitHub 密码 |
| `Repository not found` | 仓库名打错了,或者 username 不对 |
| `! [rejected] main -> main (fetch first)` | 远程有更新,选脚本里"用本地完全覆盖远程" |
| `git: command not found` | 装 Git for Windows: https://git-scm.com/download/win |
| 中文用户名问题 | 改成英文 username:https://github.com/settings/admin |
| Release 上传 422 错误 | tag 名重复了,改一下版本号 |

---

## ⚠ 安全 checklist(每个都要做)

- [ ] 改 GitHub 密码(刚才聊天里泄露了)
- [ ] 开 GitHub 2FA
- [ ] PAT 用完后撤销(https://github.com/settings/tokens)
- [ ] 仓库设为 **Private**(代码含商业逻辑)
- [ ] **永远不要**把 `.env` 推到 GitHub(`.gitignore` 已自动排除)
- [ ] 生产部署时改 `.env` 的 `BWS_AUTH_PASSWORD` 到强密码
- [ ] 定期检查 GitHub Security Alerts(在仓库 Security tab)

---

## Bundle 文件用法(高阶,可忽略)

我也生成了一个 `bws-quote.bundle`(765KB,git 原生格式,含完整 commit 历史)。

如果 `推送到github.bat` 失败了,用 bundle 备用方案:

```powershell
cd C:\Users\001\balijob
git clone bws-quote.bundle bws-quote-from-bundle
cd bws-quote-from-bundle
git remote add origin https://github.com/hanyan-zong/bwsb-.git
git push -f origin main
# 然后会问 PAT
```

但正常用上面的 `.bat` 就行,bundle 是兜底。
