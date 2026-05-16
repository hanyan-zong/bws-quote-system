# BWS 预报价系统 · B 端版本

> 面向同业旅行社的智能预报价系统 · **v0.9.0**
> 技术栈:FastAPI + Vue 3 + SQLite + Alembic + Claude AI

[![Version](https://img.shields.io/badge/version-0.9.0-blue.svg)]()
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)]()
[![Tests](https://img.shields.io/badge/tests-30%20passing-brightgreen.svg)]()
[![License](https://img.shields.io/badge/license-Private-red.svg)]()

---

## 🎯 系统概述

面向 **B 端同业旅行社**的网页版预报价系统,通过 AI + 业务规则,把资深业务员"凭经验报价"沉淀为可复用、可审计、可学习的系统化能力。

### 核心能力

| 模块 | 描述 |
|---|---|
| 🗂 **资源库管理** | 酒店 / 餐厅 / 景点 / 下午茶 / SPA / 水上 / 车辆 / 导游 — 8 类成本资源统一录入维护 |
| 📝 **行程组合** | 日游 + 多日游 + 自由活动任意组合(4 晚 5 天 + 2 天自由活动等) |
| 🤖 **AI 文档采集** | 上传 PDF / DOCX / Excel / 图片 → AI 抽出资源数据回填资源库 |
| ⚡ **AI 一键报价** | 客户上传"行程意向" → AI 解析 → 缺失字段补漏 dialog → 一键算价 |
| 💰 **赌自费策略** | 12 条业务规则(自由活动是铁律 + 5 维度细分:酒店级别 / 水上数 / 自由日含餐 / 儿童占比 / 老年占比) |
| 🛡 **行程合理性校验** | 景点-景点-酒店距离矩阵 + 一日游模板 + 区域规则 + 景点互斥 |
| 📊 **三件套导出** | Excel / PDF (WeasyPrint 中英文混排) / Word — 按角色裁剪敏感字段 |
| 📈 **赌自费回写闭环** | 团结束反馈实际收入 → 策略胜率统计反哺策略库 |
| 👥 **5 角色权限** | super_admin / ops_manager / agency_owner / agent / viewer |
| 🔐 **功能配额** | 23 功能 × 5 角色 × 32 默认配额项,可单用户覆盖 |
| 📨 **多步注册向导** | 邀请码注册 (2 步) + 自助申请 (3 步,管理员审核) |
| 💸 **双币种** | 成本 IDR 录入,对外报价 RMB 输出,汇率手动可调 |

---

## 🚀 快速开始

### 前置要求

- Docker Desktop (Windows / Mac / Linux)
- 16 GB 内存推荐
- 浏览器: Chrome / Edge / Firefox 最新版

### 一键启动 (Windows)

```bat
:: 双击下面任一脚本即可
诊断并启动.bat       :: 推荐 - 自动检查 Docker / 重建镜像 / 等待健康
一键启动.bat         :: 简化版 - 直接 docker compose up -d
全盘搜索并启动.bat   :: 不知道项目在哪儿时双击, 自动找
```

### 命令行启动 (任意 OS)

```bash
git clone https://github.com/<你的用户名>/<仓库名>.git
cd <仓库名>
cp .env.example .env       # 第一次启动复制配置, 默认 admin/admin123
docker compose up -d --build
# 等约 30 秒, 然后浏览器开 http://localhost:8000
```

### 默认账号

```
用户名: admin
密  码: admin123
```

⚠ **首次登录后立即在"账号管理"里改密码!** 系统会顶部红色警告提醒。

### 忘记密码 / 账号被锁

双击 `重置admin账号.bat`(自动解锁 + 重置密码到 admin/admin123)

或在登录页"账号已锁定"提示下点 **🔓 使用环境密钥自助解锁**,输入 `.env` 里的 `BWS_AUTH_PASSWORD` 即可。

---

## 🏗 项目结构

```
.
├── backend/                # FastAPI 后端
│   ├── app/
│   │   ├── main.py         # 入口
│   │   ├── config.py       # 全局配置
│   │   ├── database.py     # SQLAlchemy + bootstrap admin
│   │   ├── seed.py         # 默认数据 (12 条赌自费策略 + 资源样本)
│   │   ├── schemas.py      # Pydantic
│   │   ├── models/         # ORM (核心 / 报价 / 系统)
│   │   ├── routers/        # 11 个 API 路由
│   │   ├── utils/          # 计价 / 校验 / 赌自费 / 权限 / 导出
│   │   ├── ai/             # Claude 客户端 + 文档解析
│   │   └── templates/      # WeasyPrint PDF 模板
│   └── requirements.txt
├── frontend/               # 单 HTML + Vue 3 (CDN)
│   ├── index.html          # 主入口 + 注册向导
│   └── static/
│       ├── css/style.css   # 全套样式
│       ├── js/app.js       # 主逻辑
│       ├── js/components.js # 6 大组件
│       └── vendor/         # Vue / Element Plus / axios (打包进镜像)
├── docs/                   # 设计文档 (10+ MD)
├── scripts/                # init_db / 数据导入工具
├── samples/                # 示例 Excel / PDF (供 AI 解析测试)
├── skill/                  # SKILL.md (项目知识库)
├── Dockerfile              # 多阶段构建 (Python 3.11 + WeasyPrint + Noto CJK)
├── docker-compose.yml      # 含 SQLite + 可选 Postgres profile
├── .env.example            # 环境变量模板
├── 一键启动.bat            # Windows 一键启动
├── 诊断并启动.bat          # 自动诊断 + 启动
├── 全盘搜索并启动.bat       # 不知项目位置时用
└── 重置admin账号.bat       # 紧急重置 admin 账号
```

---

## 🛠 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| 后端 | FastAPI 0.115 + SQLAlchemy 2.0 + Pydantic 2 | 异步 + 类型安全 + AI 生态最近 |
| 数据库 | SQLite (默认) / PostgreSQL (生产) | 单文件零运维 → 平滑迁移 PG |
| 前端 | Vue 3 + Element Plus (CDN) | 零构建,单 HTML 跑通 |
| AI | Claude Sonnet 4.6 | 多模态 + PDF/图片直读,精度高于 OCR |
| 文档导出 | openpyxl / WeasyPrint / python-docx | 中文混排稳定 |
| 容器 | Docker + multi-stage | Cairo / Pango / Noto CJK 字体已装 |
| 认证 | bcrypt + HMAC-SHA256 cookie | 主流安全方案 |

---

## 🔐 5 角色权限矩阵

| 角色 | 描述 | 默认 AI 月配额 | 默认导出月配额 |
|---|---|---|---|
| `super_admin` | 公司超管 — 全权 + 跨 agency + 改设置 | ∞ | ∞ |
| `ops_manager` | 公司 OP — 跨 agency 帮做单,不改设置 | 1000 | ∞ |
| `agency_owner` | 旅行社老板 — 本社全部 + 邀请下属 | 200 | 500 |
| `agent` | 业务员 — 仅自己 quote | 50 | 100 |
| `viewer` | 基础只读 | 0 | 5 |

详见 `backend/app/utils/feature_permissions.py`(23 功能 × 5 角色完整矩阵)

---

## 📚 关键文档

| 文档 | 内容 |
|---|---|
| `docs/00_系统总体设计.md` | 整体架构 |
| `docs/01_架构设计.md` | 模块划分 |
| `docs/02_数据库设计.md` | 23 张表关系 |
| `docs/03_AI模块设计.md` | Claude 集成 + prompt 设计 |
| `docs/04_赌自费算法.md` | 12 条策略业务规则 |
| `docs/05_API规范.md` | 80+ 端点清单 |
| `docs/06_开发日志.md` | 版本演进 |
| `docs/07_行程合理性校验.md` | 距离 + 区域 + 互斥规则 |
| `docs/08_账号权限系统设计.md` | 5 角色 + 配额 |
| `docs/09_ERP同步钩子设计.md` | webhook 队列 |

---

## 🆘 常见问题

| 症状 | 解决 |
|---|---|
| 浏览器 ERR_CONNECTION_REFUSED | `docker compose up -d` |
| 页面顶部仍显示老版本号 | 浏览器 Ctrl+Shift+R 强刷 + `docker compose build --no-cache` |
| 登录 "账号已锁定 X 秒" | 双击 `重置admin账号.bat`,或登录页 🔓 自助解锁 |
| Docker Hub 拉镜像被墙 | Docker Desktop → Settings → Docker Engine 加 `registry-mirrors` |
| AI 解析返回 mock 数据 | 在 `.env` 设 `ANTHROPIC_API_KEY=sk-ant-xxx` |
| 切 Tab 报 "401 未登录" | 浏览器留旧 cookie,F12 → Application → Cookies → Clear |

---

## 📦 版本历史

| 版本 | 日期 | 关键改动 |
|---|---|---|
| v0.8.4 | 2026-05-10 | 企业级 Header (深色 + 用户菜单 dropdown) + 直接添加用户 |
| v0.8.3 | 2026-05-10 | 防坑功能 (主密钥自助解锁 + 默认密码警告 + 用户解锁按钮) |
| v0.8.2 | 2026-05-10 | 现代 SaaS 风格登录/注册页 (全屏渐变 + 居中卡片) |
| v0.8.1 | 2026-05-10 | 强制启用用户系统 + UI 隐藏问题修复 |
| v0.8 | 2026-05-10 | 自助注册 + 审核流程 + 多步注册向导 + Agencies CRUD + 使用统计 |
| v0.7 | 2026-05-10 | 5 角色权限 + 23 功能配额 + 32 默认配额项 |
| v0.6 | 2026-05-10 | AI 一键上传客户行程 → 直接生成报价 + 缺失字段补漏 |
| v0.5.2 | 2026-05-10 | 赌自费铁律 (有自由活动必赌) + 5 维度细分 |
| v0.5.1 | 2026-05-10 | 赌自费 UI 简化 (skip + 加利润 / fixed 让利) |
| v0.5 | 2026-05-10 | 报价导出三件套 + 团结束反馈 + 策略胜率统计 |
| v0.4 | 2026-05-08 | 多用户 + 4 角色 + ERP 钩子队列 |
| v0.3 | 2026-05-07 | GambleStrategy 单表 + 区域规则 + 景点互斥 |
| v0.2 | 2026-05-06 | 赌自费推荐引擎 + 行程合理性校验 |
| v0.1 | 2026-05-05 | 资源库 + 报价生成 + AI 文档采集 |

---

## 🤝 协作

- 本项目为 BWS Travel 内部工具,**仅限授权人员使用**
- 提 issue / PR 前请阅读 `docs/06_开发日志.md` 了解上下文
- 大改动建议先在 issue 讨论方案

---

## 📄 License

私有项目 · © PT BWS Indonesia · 保留所有权利
