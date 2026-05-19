---
name: bws-quote-system
description: 维护和扩展 BWS 预报价系统 B 端版本 — 涵盖资源库 / 行程组合 / AI 文档采集 / 行程合理性校验 / 赌自费规则系统的完整 codebase 知识. 当用户在 `预报价系统B端版本/` 项目内开发新功能、修 bug、加资源类型、加校验规则、改 AI 提示、扩展前端组件时使用本技能.
version: 0.2.0
created: 2026-05-05
---

# BWS 预报价系统 B 端版本 · 维护技能

> **触发条件**: 用户在 `预报价系统B端版本/` 项目下做开发, 或问该项目相关的设计/Bug/扩展问题
> **不适用**: 母库其他业务（账单分析/导游手册/自动化爬虫等）

---

## 一、必读上下文（开工先看）

按顺序读这 3 份, 30 分钟回到完整状态：

1. `docs/今日工作记录_2026-05-05.md` — v0.1 + v0.2 全程交付清单 + 下次优化方向
2. `docs/06_开发日志.md` — 持续避坑记录
3. `docs/00_系统总体设计.md` — 业务流程与模块全景

可视化辅助（直接用浏览器打开）：
- `docs/思维导图.html` — 8 个视图 Mermaid 思维导图

---

## 二、技术栈速查

| 层 | 技术 | 文件位置 |
|----|------|---------|
| 后端 | FastAPI + SQLAlchemy 2.x + Pydantic v2 | `backend/app/` |
| 数据库 | SQLite（SQLAlchemy create_all） | `backend/data/bws_quote.db` |
| 前端 | Vue 3 (CDN) + Element Plus + Axios | `frontend/index.html` + `static/js/` |
| AI | Claude Sonnet 4.6 (anthropic SDK) | `backend/app/ai/` |
| 文档解析 | pdfplumber / openpyxl / python-docx | `backend/app/ai/document_parser.py` |
| 部署 | Docker + docker-compose | `Dockerfile` + `docker-compose.yml` |

**Python 3.11 + Node 不需要**（前端走 CDN）。

---

## 三、模块入口索引

| 关注的事 | 直接打开这个文件 |
|---------|----------------|
| 加新资源类型（新增表 + CRUD） | `models/core.py` + `routers/resources.py` + `schemas.py` |
| 改赌自费算法 | `utils/gambling_engine.py`（v0.2 重写过）|
| 改行程合理性校验 | `utils/feasibility_engine.py` |
| 改 AI prompt | `ai/document_parser.py` 顶部 `SYSTEM_PROMPT` |
| 改前端按天编辑组件 | `frontend/static/js/components.js` 里的 `QuoteBuilder` |
| 改设置面板（含规则管理 UI） | `components.js` 里的 `SettingsPanel` |
| 加新的 no_gamble condition 类型 | `gambling_engine.py` `_eval_condition()` + `routers/settings.py` `condition-types` 端点 |
| 调整车型距离约束 | `models/core.py` `Vehicle` + `Distance` + `feasibility_engine.py` |

---

## 四、常见任务 SOP

### 任务 A · 加一个新资源类型（如"潜水中心"）

1. **加 Model**: `models/core.py` 末尾照抄 `WaterActivity` 改字段
2. **加 Schema**: `schemas.py` 加 `DiveCenterIn` / `DiveCenterOut`
3. **加 Router**: `routers/resources.py` 仿照 `optional-tours` 加 `/dive-centers` GET/POST/DELETE
4. **加 seed 样本**: `app/seed.py` 末尾加 `_seed_dive_centers(db)`
5. **删 db 重建**（v0.1 → v0.2 这种字段变更必须删 db）:
   ```bash
   rm backend/data/bws_quote.db && python scripts/init_db.py
   ```
6. **加前端**: `components.js` 的 `QuoteDay` 部分加 select; `app.js` 的 `loadAllResources` 加请求

### 任务 B · 加一个新的 no_gamble condition 类型

1. `routers/settings.py` 的 `list_condition_types()` 加一项新 type 描述
2. `gambling_engine.py` 的 `_eval_condition()` 加一个 `if t == "新type":` 分支
3. 如果需要新的 ItinerarySignals 字段，在 `_build_signals()` 里加
4. 前端 `SettingsPanel.openRuleDialog` 不用改（动态读 condition-types）

### 任务 C · 改 AI 解析 prompt

1. 编辑 `ai/document_parser.py` 顶部 `SYSTEM_PROMPT`
2. 留意：每周脚本会读 `logs/ai_corrections.jsonl` 推荐 prompt 改进, 不要直接覆盖, 先在分支测试
3. 灰度方法：复制一份 `SYSTEM_PROMPT_V2`, 在 `claude_client` 里按用户 ID 分流

### 任务 D · 改赌自费策略 (v0.3 主路径)

**首选:** 不动代码 — 在前端 Settings → 💰 赌自费策略 直接增改。

**改默认 seed:**
1. `app/seed.py` `_seed_gamble_strategies()` 加新 entry
2. 删 db 重建; 已有数据库通过迁移 API `POST /settings/gamble-strategies/migrate-from-no-gamble`

**加新 condition_type:** 见任务 B(condition 系统是 NoGamble + GambleStrategy 共用的)

**调老兜底算法系数(很少用):** `gambling_engine.py` `CUSTOMER_FACTOR` / `SEASON_FACTOR`(只在无策略命中时生效)

### 任务 E · 加车型-路段约束

1. 路段约束: `models/core.py` `Distance` 已有 `vehicle_max_seat` / `vehicle_warn_seat`
2. 车型约束: `Vehicle` 已有 `max_single_leg_minutes` / `max_daily_minutes`
3. 校验逻辑: `feasibility_engine.py` 的 `check_quote()` 中段
4. 用 seed 写预设数据，或 API `POST /api/v1/feasibility/distance` 单条加

---

## 五、关键约定（不能违反）

1. **货币命名**: 字段必须明确单位 — `cost_idr` / `price_cny`，禁止用模糊的 `price`
2. **决策可追溯**: 任何价格/赌额改动都要写 `gamble_history` 或类似审计记录
3. **AI 降级**: 没 ANTHROPIC_API_KEY 时必须走 mock，前端流程不能因此断
4. **风险护栏先于 AI**: 即使 AI 给激进建议，硬规则（最大亏损 25% / MICE 上限 / 首次合作减半）不能绕过
5. **客户文档不暴露成本**: 对外报价只显示 CNY 总价 + 简化拆分；IDR 成本只在管理员视图
6. **Pydantic v2 字段名陷阱**: `from datetime import date as _date` — 不要用 `date | None`，用 `Optional[_date]`
7. **SQLite on FUSE**: Cowork 沙箱不支持; `BWS_DATABASE_URL=sqlite:////tmp/...` 兜底
8. **分号引号**: docx-js 里中文用 `「」`, 不用 ASCII `'`; SVG 里 `&` 必转义

---

## 六、Smoke test 命令

每次改完代码（特别是 schema/engine）必须跑：

```bash
# 1. 重新初始化 DB（如果改了字段）
rm -f /tmp/bws_quote_test.db
BWS_DATABASE_URL="sqlite:////tmp/bws_quote_test.db" python scripts/init_db.py

# 2. 启动后端
cd backend
BWS_DATABASE_URL="sqlite:////tmp/bws_quote_test.db" python -m uvicorn app.main:app --port 8000

# 3. 健康检查
curl http://localhost:8000/api/v1/health

# 4. 端到端: 创建报价 + 计算
# 参考 工作脚本备份_20260505/smoke_v02.py 里的脚本
```

或者 docker:
```bash
docker compose up -d --build
docker compose logs -f bws-quote
```

---

## 七、AI 协作建议

让 Claude 改这个项目时，**先让它读这三份**：
1. 本 SKILL.md
2. `docs/06_开发日志.md`（避坑表）
3. 改动相关的具体引擎文件

不要让 AI 一上来就动 `models/core.py` — 先让它解释为什么改、影响哪些表、是否需要迁移。

---

## 七.5、深度反思:前端"看不到"问题的排查顺序

2026-05-05 v0.2.1 修登录界面时反复出现"模板里写了元素但用户看不到"的问题,共耗时约 40 分钟。沉淀以下顺序,下次按此走可压到 5 分钟内:

**排查顺序(从快到慢)**

| 步 | 动作 | 排除什么 |
|----|------|---------|
| 1 | 服务器侧 `Invoke-WebRequest` 拉 HTML/CSS/JS,grep 关键 class 名 | 服务端没出新版 |
| 2 | 看 `Cache-Control` 响应头是否含 `no-store`(本项目 `main.py` 已加全局中间件) | 浏览器缓存 |
| 3 | Edge `--inprivate` / Chrome `--incognito` 重打开 | 用户浏览器历史缓存 |
| 4 | F12 → Console 看红字(JS 报错会让 Vue 整段不挂载) | 整页 Vue 没渲染 |
| 5 | F12 → Elements 看 DOM 里到底有没有这个元素 | 区分"没渲染"与"渲染了但看不见" |
| 6 | 元素在 DOM 但不可见 → 改样式 (display/visibility/z-index/overflow) | 样式问题 |
| 7 | 元素不在 DOM → Vue 模板被组件库吞了 → 退到原生 HTML | 框架嵌套问题 |

**反模式(已踩过,不要再踩)**
- ❌ 反复改 width/margin 想"把按钮挤出来" — 元素如果根本不在 DOM 里,改样式毫无意义
- ❌ 不开 F12 就"再刷一次试试" — 没数据的修复是赌博
- ❌ 用 jsDelivr 等外部 CDN 不做兜底 — 用户网络多变,vendor 到本地是定型方案
- ❌ 在 Element Plus `<el-form>` 内放任意子节点 — 它会按 form-item 规则处理,部分场景静默丢弃

**正确防御**
- 关键交互按钮用原生 `<button>` + 自定义 class,绝不嵌 `<el-form>`
- 所有第三方 JS/CSS vendor 到 `frontend/static/vendor/`(已完成)
- 后端开发期对 HTML/CSS/JS 全部下发 `Cache-Control: no-store`(已加在 `main.py`)

---

## 七.6、口令门(v0.2.1 新增)

**默认账号:** `admin` / `123456`(在 `.env` 中改 `BWS_AUTH_USERNAME` / `BWS_AUTH_PASSWORD`)
**关闭口令门:** `BWS_AUTH_USERNAME=` 留空,所有人直接进
**Cookie:** `bws_session`,HMAC-SHA256 签名(密钥见 `BWS_AUTH_SECRET`),7 天有效

**关键文件:**
- `backend/app/routers/auth.py` — login/logout/status 三端点 + `is_authenticated()` 帮助函数
- `backend/app/main.py` — 第二段 middleware(auth_gate)在 CORS 后,白名单 `/`、`/static/*`、`/api/v1/auth/*`、`/api/v1/health`
- `backend/app/config.py` — `auth_username` / `auth_password` / `auth_secret` / `auth_required` 属性
- `frontend/index.html` — 登录卡片 v-if 区块,**用原生 `<button>` 不用 `<el-button>`**
- `frontend/static/js/app.js` — `checkAuth/doLogin/logout/cancelLogin` 方法 + 401 拦截器 + `axios.defaults.withCredentials = true`

**升级到多用户(v0.3)时的取舍点:**
- 现在的 cookie 是无状态 HMAC,改 JWT 几乎没成本
- 真上多用户要建 `users` 表 + `bcrypt` 哈希密码,口令门可作为"超管入口"保留

---

## 八、未解决问题（业务确认中）

下次开工前需用户确认（详见 `今日工作记录` 第七节）：

1. B 端旅行社是邀请制还是自助注册？
2. 价格字段对 B 端可见性策略？
3. 是否支持 USD/SGD 多币种？
4. 自费回写入口在 ERP 还是本系统？
5. AI key 公司统一采购还是 B 端自带？

---

## 九、版本演进表

| 版本 | 日期 | 关键变化 |
|------|------|---------|
| v0.1 | 2026-05-05 上午 | 立项 + 7 模块全套 + 9 设计文档 |
| v0.2 | 2026-05-05 下午 | NoGambleRule 用户可定义 + free_hours 细粒度 + 自费 category 重叠剔除 + 车型-距离绑定 |
| v0.2.1 | 2026-05-05 晚 | 单租户口令门(admin/123456 默认) + 前端 vendor 本地化 + 缓存禁用中间件 + 登录界面用原生 button |
| v0.2.2 | 2026-05-05 晚 | 按天编辑加 "+ 添加第 N 天" / "× 删除" 原生 button,可手动多日组合 |
| v0.2.3 | 2026-05-06 上午 | 审计修复(NaN/CORS)+ 入库 500 修复(date 转换/session rollback)+ AI 采集表格可编辑(类型/名称/价格/备注/区域)+ 巴厘岛区域字典 31 个 + 区域不兼容规则系统(model+CRUD+seed+feasibility 接入+UI) |
| v0.2.4 | 2026-05-06 下午 | 一日游模板完整 CRUD(详情/编辑/AI 解析+名→ID 映射)+ xls 兼容(xlrd 1.2)+ 资源库 9 类完整 CRUD + simple/{kind} CRUD + 母库导入 265 条(import_bali_data.py)+ AI prompt 加 few-shot 示例 |
| v0.2.5 | 2026-05-06 晚 | 景点互斥规则系统(model/CRUD/seed/feasibility/UI)+ QuoteBuilder 智能模板建议+排序+实时互斥提示 + 资源库类型专属筛选+分页[10,20]+价格档位 + 酒店属性自动识别(酒店/度假村/别墅) + 航班时间字段(arrival_at/departure_at)+ ALTER TABLE 兼容迁移 + gambling_engine 加航班加成 free_hours |
| **v0.3** | **2026-05-07** | **赌自费策略重设计** — 单表 `GambleStrategy` 替代 `NoGambleRule`+复杂算法。每条策略 = 一种行程组合 + 对应让利金额(skip/fixed/per_pax)。引擎按 priority 倒序评估,首条命中即停。Settings 加 "💰 赌自费策略" + "🔍 案例编辑器/预览" + "↻ 从旧规则迁移" 按钮。8 条 seed 策略覆盖典型场景。老 `NoGambleRule` 表保留作迁移源。`/settings/gamble-strategies` CRUD + `preview` + `migrate-from-no-gamble` 端点全部就绪 |
| **v0.4** | **2026-05-08** | **多用户账号系统 + 字段隐藏 + ERP 钩子** — 5 张新表(agencies/users/invitations/erp_sync_events/erp_config)+ 4 角色(super_admin/agency_owner/agent/viewer)+ 邀请制(`bws-XXXXX` 邀请码)+ bcrypt 密码 + cookie 升级带 user_id + 5 次失败锁定 15min + 老 .env 账号自动 bootstrap 成 super_admin。**字段过滤**: agent/viewer 看不到 `cost_idr_*` / `profit_cny_per_pax` / `gamble_cny_per_pax`。**Quote scope 隔离**: agent 只看自己创建的 / agency_owner 看本社 / super_admin 全权。**ERP 事件队列**: `enqueue_erp_event()` 业务事务内写 `erp_sync_events`(配置 enabled=False 时不写),管理面板可看队列+手动 mark synced/skip/retry。15 个新 admin API 端点。Smoke test 9 场景全 PASS |
| v0.5 待 | TBD | APScheduler ERP worker + Alembic 迁移 + 报价导出 PDF/Excel/Word + 前端 admin 面板 |
| v0.9.0 | 2026-05-16 | CLI 体系工程化 (4 命令组 + bws dev 一键启动) + Alembic 接入 + pytest 双轨 44 用例 (CLI subprocess + Web TestClient) + datetime.utcnow() 全替换为 now_utc() |
| **v0.9.1** | **2026-05-19** | **赌自费策略数据对齐 + legacy 清理 + 普通用户 UI 隔离**:DB gamble_strategies 补到 12 条 v0.5.2 业务对齐版 (8 老 soft-disabled);删 _check_no_gamble_rules 函数 + 兜底分支 + 3 CRUD 端点 + UI legacy 卡片 + ruleDialog 弹窗 + 6 methods;前端 main-tabs 加 isAdmin gate (agent/viewer 只看报价 + 历史);FastAPI on_event → lifespan 消 4 warning;seed._seed_gamble_strategies 改 idempotent + database.init_db 加同步钩子 |
| **v0.9.2** | **2026-05-19** | **后端 routers 权限 gate** — 堵住 agent 越权写资源/模板/设置漏洞:routers 接入 `dependencies=[Depends(require_role(...))]`. resources 14 写端点 + templates 3 写端点 → super_admin/ops_manager;settings 10 写端点 (汇率/时间预算/赌自费配置/区域规则/景点互斥/策略/迁移) → super_admin only;GET 全部保留开放(报价流程需读)。**bug**: utils/permissions.require_role factory 的 `db: Session` 缺 `Depends(get_db)` 导致 FastAPI 报 "Invalid args for response field",修复后 59 PASS。新建 backend/tests/web/test_admin_gate.py 15 用例 (agent 9 个 403 写 + 5 个 200 读 + 1 admin 回归)。conftest 加 `_agent_user` (session) + `agent_client` fixture |
| **v0.9.3** | **2026-05-19** | **行程类型 day_type + 复制天 + 景点路线 UI 美化** — QuoteDay 加 `day_type: str` (full/half/arrival/departure), pricing_engine 对 half/arrival/departure 车导 × 0.5, departure 自动跳 hotel + breakfast ON. Alembic `0001_quote_day_day_type` migration (idempotent, 检测列存在跳过). 前端每天卡片头加 4 选 1 单选 + 绿色 📋 复制按钮(深拷贝插入下一位). 景点列表 UI 重写: 圆形彩色徽章(出发绿/终点红/中间蓝) + 垂直竖线 + ▶出发/■终点 标签 + 📍 区域 chip. 修长者 input-number width:100% (之前数字框被挤<20px 输不进去) + 目的地下拉同修. 新增 8 unit test (MagicMock 直调 calculate). 67 PASS / 32s |

---

## 十、快速 troubleshooting

| 症状 | 99% 是这个原因 |
|------|--------------|
| `disk I/O error` 启动失败 | SQLite on FUSE — 改 `BWS_DATABASE_URL` 到 /tmp |
| `unsupported operand type(s) for \|: 'NoneType'` | Pydantic 字段名遮蔽类型 — 见第 5 节第 6 条 |
| `UNIQUE constraint failed: quotes.quote_no` | quote_no 同秒重复 — 已用 random 后缀修复 |
| AI 解析返回 mock 数据 | 没设置 `ANTHROPIC_API_KEY` 环境变量 |
| 改了字段但前端不显示 | 浏览器缓存(`main.py` 已加 no-cache 中间件,新部署不再有此问题);旧实例仍卡 → Edge `--inprivate` 或 Chrome `--incognito` 验证 |
| Docker 起不来 | WSL2 没装好 / 虚拟化没开 / 镜像源慢;`docker --version` OK 不代表 daemon 起来,要 `docker ps` 探活 |
| `Identifier 'X' has already been declared` | 多个 `<script>` 标签共享全局作用域,顶层 `const X` 被声明两次。统一在 `components.js` 里声明,`app.js` 直接用 |
| Vue 模板里的 `<el-button>` / 子元素不渲染 | Element Plus 的 `<el-form>` 在某些组合下静默吞掉非 form-item 直接子元素 — **关键交互按钮(登录/提交/删除确认)请用原生 `<button>` + 自定义 CSS**,不要嵌在 `<el-form>` 内 |
| jsDelivr / CDN 拉不到 | 部分网络对 jsDelivr 不稳。所有第三方资源已 vendor 到 `frontend/static/vendor/`,不再依赖外网 |
| Python 3.14 装依赖 build 失败 | pydantic-core 2.9 / Pillow 10.4 / pyo3 0.22 没 cp314 wheel。用 `py -3.12 -m venv .venv` 切回 3.12 |
| seed 脚本最后崩 `UnicodeEncodeError` | Windows console GBK,但其实数据已写入。启动加 `PYTHONIOENCODING=utf-8` |
| AI 入库 500 `SQLite Date type only accepts Python date` | mock 返回 `valid_from='2026-01-01'` 字符串,需 `_to_date()` 转换。已在 `ai_parser.py` 修复 |
| AI 入库 500 重试持续失败 PendingRollback | 单条 fail 后 session 污染,后续都炸。`confirm_extraction` 的 for 循环已加 `db.rollback()` |
| python-docx 解析假/损坏 docx 5xx | `parse_document()` 在 mock 模式短路返回示例数据,不读文件内容(已修复) |
| openpyxl `does not support .xls` | 老格式需 xlrd 1.2.0(已加到 requirements);`document_parser._extract_xls_legacy()` 自动分流 |
| requests 调 localhost 502 Bad Gateway | Windows 系统代理拦截。`Session().trust_env=False` + `proxies={"http":""}` |
| Power Shell 5.1 测中文 API 报"未关联"/乱码 | 5.1 默认 cp936 编 / ISO-8859-1 解。请求 body 用 `[Encoding]::UTF8.GetBytes()` + `Content-Type: ...; charset=utf-8`;响应用 `r.RawContentStream.ToArray()` + `[Encoding]::UTF8.GetString()` |
| ALTER TABLE ADD COLUMN 加新字段(SQLite v0.2 没 Alembic) | `database.py init_db()` 末尾加 try/except ALTER TABLE,新列幂等添加,历史数据零损失。v0.3 上 Alembic 后删除 |
| 母库 xlsx cols=16384 假象 | 列宽是元数据残留,真实列 ≤ 10。扫描时手工探测前 30 行真实列宽 |

---

**本技能持续维护. 重大变更同步更新本文件 + `docs/06_开发日志.md`.**

---

## 十二、v0.3 GambleStrategy 系统(2026-05-07)

### 架构

```
quote.calculate
   │
   ▼
gambling_engine.recommend()
   │
   ├─[1]─▶ _build_signals(quote)        # 提炼客户类型/自由小时/全程含餐/...
   │
   ├─[2]─▶ _check_gamble_strategies()   # ★ 主路径 (v0.9.1 起唯一规则路径)
   │         按 priority desc 遍历 active strategies
   │         首条 conditions 全 AND 命中 → 返回(skip/fixed/per_pax)
   │         12 条 v0.5.2 业务对齐策略含 priority=100 (无自由→不赌) +
   │         priority=1 (有自由→兜底 ¥200/人), 实际全覆盖
   │
   └─[3]─▶ 老经验值算法(自由时间因子+自费重叠+客户/季节系数)  # 最终兜底 (仅用户禁用全部策略时触发)

# v0.5.3 起 NoGambleRule 兜底分支已删除 (策略表完全覆盖, 不再需要)
```

### 关键文件

- 模型: `models/system.py::GambleStrategy`(8 字段: name/description/conditions/action/gamble_cny/priority/active/timestamps)
- Schema: `schemas.py::GambleStrategyIn` + `GambleStrategyPreviewIn`
- 引擎: `utils/gambling_engine.py::_check_gamble_strategies()` + `recommend()` 第 0a 段
- API: `routers/settings.py` — `/gamble-strategies` GET/POST/DELETE + `/preview` + `/migrate-from-no-gamble`
- 前端: `components.js` SettingsPanel 加 "💰 赌自费策略" 卡片 + 编辑弹窗 + 案例编辑器 dialog
- Seed: `seed.py::_seed_gamble_strategies()` — 8 条默认(4 skip + 3 fixed + 1 兜底)

### Action 三种取值

| action | 含义 | gamble_cny 语义 | 示例 |
|--------|------|---------------|------|
| `skip` | 不赌 | 无视(自动 0) | "MICE 短行程不赌" |
| `fixed` | 固定让利 | 单人金额 (¥/人) | "蜜月旺季让 ¥450/人" |
| `per_pax` | 按人计 | 单人金额 × 人数 = 团总 | "亲子套包让 ¥100/团" |

### 案例编辑器(preview)

`POST /settings/gamble-strategies/preview` 接受 9 个信号字段(customer_type/season/total_days/...),返回每条策略的命中状态 + 命中后停止。前端 SettingsPanel "🔍 案例编辑器/预览" 按钮可视化展示。

用户可以在 UI 里"我假想一个旅团是 X" 看哪条策略生效,验证设置是否正确。

### 迁移

- v0.5.3 起 seed._seed_no_gamble_rules 已删除 (新 DB 不再自动种 5 条老规则)
- 老 DB 残留的 NoGambleRule 数据保留 + `POST /settings/gamble-strategies/migrate-from-no-gamble` 一次性迁移端点保留
- 迁移幂等(按 name 去重),重跑只看 `migrated/skipped_duplicate` 数字
- 老 NoGambleRule 表 + 模型 + condition-types 端点保留 (condition-types 给 GambleStrategy 编辑器复用 12 种条件下拉)
- v0.9.1 起 routers/settings.py 的 list/upsert/delete /no-gamble-rules CRUD 3 端点已删除 (UI 卡片 + 弹窗一并删)

### v0.3 验证清单(已通过)

| 场景 | 期望 | 实测 |
|------|------|------|
| 蜜月旺季 5 天 + 16h 自由 | fixed ¥450/人 | ✅ |
| MICE 4 天 0 自由 | skip(自由不足或 MICE 短行程) | ✅ |
| 普通家庭 5 天 + 8h 自由 | 默认兜底 ¥200/人 | ✅ |
| 用户自定义高优 per_pax 100/人 | 覆盖更低优的 ¥450 | ✅ |
| 旧 NoGambleRule 迁移 | 幂等,不重复入库 | ✅ |

---

## 十三、v0.4 账号系统 + ERP 钩子(2026-05-08)

### 5 张新表

| 表 | 字段 | 用途 |
|---|---|---|
| `agencies` | name / short_name / contact / commission_rate / status | B 端旅行社 |
| `users` | username / password_hash(bcrypt) / role / agency_id / failed_login_count / locked_until | 用户 |
| `invitations` | code(`bws-XXXXX`) / agency_id / role / max_uses / expires_at / revoked_at | 邀请码 |
| `erp_sync_events` | event_type / entity_type / entity_id / payload(JSON) / status / retry_count | 事件队列 |
| `erp_config` | enabled / webhook_url / auth_token / retry_max | ERP 配置 |

`Quote` 加 `created_by_user_id` + `agency_id`(ALTER TABLE 兼容补丁)。

### 4 角色权限

```
super_admin    → 全部 + 资源/规则/用户/系统设置 + 跨 agency
agency_owner   → 本社全部 quote + 邀请本社 agent/viewer
agent          → 仅自己创建的 quote
viewer         → 只读 (v0.5 加分配机制)
```

### 字段过滤(隐藏成本核心)

`utils/permissions.py`:
- `can_see_costs(user)`: `super_admin` / `agency_owner` 可见
- `filter_quote_dict(d, user)`: 隐藏 `cost_idr_total / cost_cny_total / profit_cny_per_pax / gamble_cny_per_pax`
- `filter_resource_list(rows, rtype, user)`: 隐藏各资源类型的 `cost_idr_*` / `ticket_idr_*`
- `filter_hotel_with_rooms(hotels, user)`: 嵌套 rooms 双层过滤
- `filter_quotes_by_scope(query, user)`: SQL where 加 agency_id / created_by_user_id 限制

每个 list endpoint 取 `user = get_current_user(request, db)` 后 return 前过一层 filter。

### 邀请-注册流程

```
1. super_admin POST /agencies → 建社
2. super_admin POST /invitations → 邀请码 bws-XXXXX
3. B 端老板 GET /auth/invitation/{code} → 看 agency 信息
4. B 端老板 POST /auth/register → 自动登录 (role=agency_owner)
5. owner POST /invitations → 邀请本社 agent / viewer
   (owner 不能邀请 super_admin 或跨 agency,后端 403)
```

### ERP 钩子(留位不实现)

`utils/erp_hook.py::enqueue_erp_event()`:
- 业务事务内同时写 `erp_sync_events` (status=pending)
- **不调 db.commit()**,由外层业务统一提交(原子性)
- `erp_config.enabled=False` 时直接 return,不写队列(避免数据膨胀)
- v0.5 加 APScheduler worker 真正消费即可

钩子位置:
- `routers/quotes.py` PUT `/{id}/status` 状态变 accepted/lost
- `routers/gamble.py` POST `/feedback` 团结束自费回写

### 关键文件

- 模型: `models/system.py::Agency / User / Invitation / ErpSyncEvent / ErpConfig`
- Auth: `routers/auth.py` (重写, bcrypt + 邀请注册 + cookie 带 user_id)
- 权限: `utils/permissions.py` (字段过滤 + scope 限制)
- ERP: `utils/erp_hook.py` (事件入队工具) + `routers/admin.py` (15 端点统一管理)
- DB 加列: `database.py::init_db()` ALTER TABLE 加 `created_by_user_id` + `agency_id`

### v0.4 验证清单(已通过)

| Test | 场景 | 实测 |
|---|---|---|
| 1 | super_admin 用 .env 账号首登 → 自动 bootstrap | ✅ |
| 2 | super_admin 创建 agency + 邀请 agency_owner | ✅ |
| 3 | B 端老板用邀请码注册 + 自动登录 | ✅ |
| 4 | agency_owner 越权邀请 super_admin → 403 | ✅ |
| 5 | agent 看资源库 → cost_idr_* 全隐藏(admin 仍可见) | ✅ |
| 6 | agent 看 quote → cost/profit/gamble 全隐藏,price 可见 | ✅ |
| 7 | super_admin 同一份 quote → 全字段可见 | ✅ |
| 8 | ERP 启用后 quote.accepted → 写事件入队 | ✅ |
| 9 | 跨 agency 隔离 — owner B 看 quote 数=0 | ✅ |

实测数据:agent 看到 ¥5954.35/人;super_admin 看到 IDR 27,620,000 总成本 + ¥400 单人利润 + ¥11,908.70 总售价。

### v0.4 troubleshooting

| 症状 | 原因 |
|------|------|
| 老 .env 账号登录失败 | users 表已有同名用户但密码不同;走 users 表校验 |
| owner 试图改 super_admin 密码 → 403 | 设计如此,只有 super_admin 能管 super |
| ERP 队列没事件 | `erp_config.enabled` 默认 false;PUT `/erp-sync/config` 启用后才写 |
| cookie 解析失败 | 旧版 cookie 格式不兼容;重新登录即可

---

## 十一、v0.2.5 模型 / API 速查(2026-05-06 累积)

### 数据模型(新增)
- `AreaRule`(`models/system.py`) — hotel_area + excluded_attraction_area + severity + message
- `AttractionConflictRule` — attraction_a_id + attraction_b_id + severity + message(规范化 a < b)
- `Quote` 加航班 4 字段:`arrival_at` / `departure_at` / `arrival_airport` / `departure_airport`(SQLite ALTER TABLE 兼容)

### API(新增)
- `/settings/areas` — 31 个标准区域字典(`flat`/`grouped`)
- `/settings/area-rules` CRUD
- `/settings/attraction-conflicts` CRUD
- `/templates/{id}` — 详情(含景点/餐厅完整名)
- `/templates/parse-document` — AI 解析 + 名→ID 映射
- `/resources/simple/{kind}` POST/DELETE(SPA/水上/下午茶 通用)

### 引擎扩展
- `feasibility_engine.check_quote()` 在每天检查中:
  1. 区域规则:hotel.area + 任一 attraction.area 匹配 → error/warning
  2. 景点互斥:同日两 attraction_id 匹配 → error/warning
  3. 提示前缀 `[区域规则]` / `[景点互斥]`
- `gambling_engine._flight_implied_short_hours()`:首日抵达 +1h 缓冲、末日离开 -1.5h 缓冲,被压缩的小时数累加到 `free_hours_total`

### 前端核心组件
- `ResourceManager` 9 类完整 CRUD + 类型专属筛选 + 分页 [10,20] + 价格档位 + 酒店属性
- `TemplateManager` 完整 CRUD + AI 解析 + 详情 dialog
- `AiUploader` 表格可编辑(类型/名称/价格/备注/区域)
- `QuoteBuilder` 多日按钮 + 模板预览 + 智能模板建议 + 景点排序 + 互斥实时提示 + 航班 picker + 每日可用小时徽章
- `SettingsPanel` 5 张卡片:汇率 / 时间预算 / 赌自费配置 / 区域规则 / 景点互斥规则 / 不赌规则

### 母库导入脚本
- `scripts/import_bali_data.py` 解析 `02_行程产品报价/20260410巴厘岛项目成本2026年版本.xlsx` 和 `BWS碎片化整理.xlsx`,共导入 265 条
- 价格清洗规则 `parse_idr()` 识别 `Rp 25,000` / `500k` / `fit 550k 7间房以上：480k` / `1.220.000` 等格式
- 跳过项:接送机车费(模型不匹配)/ 多日游产品(系统未建模)/ 导游小费规则(应做独立规则表)


---

## 十二、v0.5 → v0.8.4 速查 (2026-05-10 一天 10 个版本)

### v0.5 — 报价导出三件套 + 反馈闭环

**3 个新文件**:
- `backend/app/utils/exports/__init__.py` + `context.py` + `excel_builder.py` + `pdf_builder.py` + `docx_builder.py`
- `backend/app/templates/quote_pdf.html.j2` (WeasyPrint 模板)
- `backend/app/routers/exports.py` — `GET /quotes/{id}/export?format=xlsx|pdf|docx`

**关键避坑**:
- weasyprint==62.3 必须锁 **pydyf==0.10.0**, pip 默认拉 0.12.x → "super has no transform" 错误
- HTTP Content-Disposition 中文文件名:`filename="ASCII"; filename*=UTF-8''escaped` 双值
- jinja2 模板用 `q.xxx` 但传参是 `quote=ctx['quote']` → 显式 remap

**赌自费回写**: `gamble_history` 表加 4 列 (strategy_id / feedback_notes / feedback_at / feedback_by); POST `/quotes/{id}/feedback` 写入,GET `/settings/strategy-stats?days=N` 出胜率统计

### v0.5.1 — 简化赌自费 UI

**用户反馈**:删掉看不懂的 5 个系数(安全比/最大亏损比/首次合作/自费毛利率/MICE上限),只保留启用开关.
**新 schema**:`GambleStrategy.extra_profit_cny` (skip 命中后反向加利润)
**前端**:策略动作改成 ⚪🛡 不赌 / ⚪🎲 赌(让利) 二选一.skip 时显示"额外加利润 ¥/人",fixed 时显示"让利金额 ¥/人"

### v0.5.2 — 赌自费业务规则升级 (5 维度)

**用户原话指引**:
> 主结构只要有自由活动不能判定不赌自费, 5 星酒店少赌, 已含水上多少赌, 全程含餐少赌, 儿童多少赌, 老年人 55+ 多少赌

**新加 7 个 condition_type**: `has_any_free_activity` / `hotel_max_star_gte/lte` / `water_count_gt/gte` / `free_days_with_meals` / `child_count_gt` / `child_ratio_gt` / `senior_count_gt` / `senior_ratio_gt`

**ItinerarySignals 加字段**: `hotel_max_star` (查 db 算) / `water_activity_count` / `free_days_with_meals` / `child_ratio` / `pax_senior` / `senior_ratio`

**Quote 新字段**: `pax_senior` (55+ 老年人, ALTER TABLE 兼容)

**12 条 seed 策略覆盖业务规则** (见 docs/今日工作记录_2026-05-10.md)

**修了 UI bug**: 命中 fixed 策略时显示"系统判定:不赌自费"(自相矛盾) → 改成根据 action 显示三种状态
- 🛡 系统判定: 不赌 (含可选"反向加利润")
- 🎲 系统判定: 赌 · 让 ¥X/人
- 不赌 (无策略命中)

### v0.6 — AI 一键上传客户行程报价

**完整新 stack**:
- `backend/app/ai/document_parser.py:parse_itinerary_intent()` — 新 prompt (与 parse_document 抽资源不同, 这个抽 quote_draft)
- `backend/app/utils/itinerary_matcher.py` (NEW) — fuzzy 匹配 (子串包含 + jaccard 字符重合) + detect_missing_fields
- `backend/app/routers/ai_parser.py` 加 `/parse-itinerary` + `/quote-from-itinerary`
- 前端 AiUploader 加 ⚡ 客户行程一键报价 卡 + 补漏 dialog

**测试用例**: 巴厘岛 The Mulia (100% match) / 金巴兰沙滩 → 金巴兰海滩 (66% fuzzy)

### v0.7 — 5 角色 + 23 功能 × 32 配额

**新加 ops_manager 角色** (公司侧 OP, 跨 agency 帮做单, 不改设置)

**新文件**: `backend/app/utils/feature_permissions.py` (集中声明)
- `FEATURES`: 23 功能 (报价/AI/导出/反馈/管理/账号 6 类)
- `FEATURE_REQUIREMENTS`: 角色 → 可用功能 allowlist
- `DEFAULT_QUOTAS`: 角色 → 功能 → (period, limit) 32 项
- `can_use_feature` / `require_feature` / `consume_quota` / `init_quotas_for_user` / `get_user_quotas`

**新表**: `usage_quotas` (user_id × feature, period, limit_count, used_count, reset_at, overridden_by_admin) + `usage_logs` (审计)

**关键设计**: `consume_quota` 内部立即 `db.commit()` — 即使后续业务挂掉, 配额已扣 (审计准确性硬要求)

**周期重置**: 月初 1 号 00:00 UTC 自动 reset (在 `_check_and_reset` 里 lazy 检查)

### v0.8 — 自助注册 + 审核 + 多步向导

**User 新字段**: status 加 `pending_review` / `rejected` 取值; `application_note` / `requested_agency_name` / `review_note` / `reviewed_by_user_id` / `reviewed_at`

**新端点**:
- `GET /auth/agencies-public` (无需登录, 注册向导用)
- `POST /auth/register-public` (无需邀请码, status='pending_review')
- `GET /admin/pending-users`
- `POST /admin/pending-users/{id}/review` (批准/拒绝, 自动建 agency, 自动 init_quotas)
- `GET /admin/usage-stats?days=7` (聚合: by_feature + by_user)

**login 端点状态友好提示**: pending_review/rejected/disabled 各给不同 403 message (不是统一 401)

**前端**: index.html 重写注册卡为 4 状态向导
- Step 0 选模式 (3 大入口)
- 邀请码注册 (Step 1 校验码 → Step 2 填账号)
- 自助申请 (Step 1 选社/角色 → Step 2 账号 → Step 3 理由)

设置页"账号管理" 加 6 个子 Tab (待审核/用户/配额/邀请码/旅行社/7天统计 + super_admin 看权限矩阵)

### v0.8.1 — 强制启用用户系统

**问题**: 用户 .env 里 `BWS_AUTH_USERNAME` 空 → `auth_required=False` → 所有 `v-if="authRequired"` 隐藏 → 退出/我的配额/账号管理 全看不到

**修法**:
- `config.py:auth_required` 永远返回 True
- `database.py:_ensure_bootstrap_admin()` 启动时检查, 没 super_admin 就用 .env 或默认 admin/admin123 自动建 (含配额初始化)
- 前端去掉所有 `authRequired` 依赖, 只看 `authenticated`
- `.env.example` 默认填 `BWS_AUTH_USERNAME=admin / BWS_AUTH_PASSWORD=admin123`

### v0.8.2 — 现代 SaaS 风格登录页

**用户反馈**: 老登录页太难看 (按钮挤一边, 文字溢出)

**重写 CSS**: `.login-card-modern` (460px 居中卡 + 圆角 12px + 深阴影 + fadeInUp 动画)
**全屏背景**: 深蓝渐变 `#1e2761 → #2c5282 → #3a7bd5` + 装饰圆斑
**3 大入口按钮**: 全宽 + 图标 + 标题 + 副标题描述 + 右箭头
**步骤进度**: el-steps 顶部
**字段输入**: `prefix` 图标 + size="large"
**底部跳转**: "还没有账号? 邀请码注册 / 自助申请"

### v0.8.3 — 防坑功能套件

**6 个关键改进**:

1. `重置admin账号.bat` — 双击解锁 + 重置密码 (`docker exec ... python -c "..."`)
2. `POST /auth/master-unlock` — 用 .env BWS_AUTH_PASSWORD 作主密钥, 解锁任意用户 + 可选重置密码 (含防爆破延迟 0.5s)
3. 登录页"账号已锁定"下加 🔓 自助解锁 链接 → 弹 modal 输主密钥
4. 默认密码警告 banner — 顶部橙色 sub-header (force_password_change=true 时显示)
5. 改密 dialog (含旧密码/新密码/再次确认 三栏)
6. 用户列表加 4 个操作: 🔓 解锁 / 🔑 改密 / 停用 / 启用

**新 admin 端点**:
- `POST /admin/users/{id}/unlock`
- `POST /admin/users/{id}/reset-password`
- `POST /admin/users/{id}/disable`
- `POST /admin/users/{id}/activate`

### v0.8.4 — 企业级 Header + 直接添加用户

**Header 重设计**:
- 老的橘紫渐变 → 纯深色 `#1a1f3a` (GitLab/Stripe 同款)
- 标题不换行 (white-space: nowrap)
- 右上角按钮收进 `el-dropdown` 用户菜单 (账号信息 / 我的配额 / 修改密码 / 退出登录)
- 默认密码警告独立 sub-header (不挤进 header)
- 头像用渐变蓝紫 + 用户名首字母

**+ 直接添加用户**: super_admin / agency_owner 可不通过邀请码直接创建用户. POST `/users` (admin.py 已有, 加 agency_owner 边界检查 + 自动 init_quotas)

### 当日累积的 7 个 .bat / .ps1 自动化脚本

- `一键启动.bat` — 简化 docker compose up
- `诊断并启动.bat` — 7 步诊断 + 自动 build + 健康检查
- `全盘搜索并启动.bat` — 不知项目位置时找
- `重置admin账号.bat` — 紧急重置 admin/admin123
- `推送到github.bat / .ps1` — git init+commit+push (处理冲突)
- `上传Release到github.bat / .ps1` — API 上传 75MB zip 到 Releases
- `push-to-github-en.ps1` — 纯英文版 (避免编码问题)

### Windows .bat / .ps1 编码踩坑(下次直接套用)

**1. .bat 必须 CRLF 行结尾**
```bash
sed -i 's/\r$//' file.bat; sed -i 's/$/\r/' file.bat
```
否则 cmd 报 `'65001' 不是命令` 之类奇怪错误

**2. .ps1 必须 UTF-8 with BOM**
```bash
printf '\xEF\xBB\xBF' > tmp; cat file.ps1 >> tmp; mv tmp file.ps1
```
否则 PowerShell 5 用 GBK 读 UTF-8 → 中文乱码 + 解析错误

**3. cmd 中文环境 enabledelayedexpansion 不可靠**
`!VAR!` 偶尔不展开 → URL 出现字面 `!GH_USER!` 字符串
**解决**: 转 PowerShell `.ps1` (支持 `$var`)

**4. 凡是有中文的脚本, 都另存一份纯英文版** (兜底)

### 当日 8 项关键 bug 速查

| Bug | 现象 | 根因 | 修复 |
|---|---|---|---|
| 401 切 Tab | 资源库 Tab 报"未登录" | 浏览器留旧 cookie | F12 Cookies Clear |
| Vue insertBefore | Element Plus 内部 ref 错乱 | v-if 频繁加删 DOM | 改 v-show |
| force_password_change UI 不消失 | 改密后 banner 还在 | 没刷新 currentUser | doChangePassword 后 await loadMe() |
| pydyf 不兼容 weasyprint | "super has no transform" | pip 默认拉 0.12.x | 锁 pydyf==0.10.0 |
| docker exec rm .git 失败 | "Operation not permitted" | Cowork 沙箱权限 | Windows 上 rmdir /s /q |
| Header v-if=authRequired 全隐藏 | 退出/账号管理 都看不到 | .env BWS_AUTH_USERNAME 空 | 强制 auth_required True |
| set /p !VAR! 不展开 | URL 出现字面 `!GH_USER!` | cmd 中文 delayedexpansion 不稳 | 转 .ps1 |
| GitHub Permission denied (publickey) | SSH 配了仍 push 失败 | 公钥没添加到 GitHub | https://github.com/settings/ssh/new |

---

## 十三、新人开工 Checklist (从 v0.8.4 接手)

1. **读 5 份 doc** (按顺序):
   - `docs/今日工作记录_2026-05-10.md` (本日全流水)
   - `docs/下次深度优化方向_2026-05-11.md` (P0/P1/P2 排好序)
   - `docs/04_赌自费算法.md` (业务规则核心)
   - `docs/08_账号权限系统设计.md` (5 角色 + 23 功能)
   - `README.md` (整体架构 + 快速开始)

2. **跑通本地**:
   - `cd 预报价系统B端版本/`
   - `cp .env.example .env` (默认 admin/admin123)
   - `docker compose up -d --build`
   - 浏览器开 http://localhost:8000 → admin/admin123 登录
   - 改密码 (顶部橙色 banner 提示)

3. **理解架构** (10 分钟):
   - backend/app/ 是 FastAPI 11 个 router
   - frontend/index.html 是单 HTML + Vue 3 (CDN, 不需要 build)
   - Docker 镜像里包含 Cairo / Pango / Noto CJK 字体 (PDF 中文必须)

4. **下一步 (按优先级)**:
   - P0: 完成 GitHub push (用户卡在 SSH 公钥添加)
   - P0: AI 真接 Anthropic 测一份真行程
   - P1: 加 Alembic 替代 ALTER TABLE
   - P1: Playwright E2E 测试

---

## 十四、bws CLI 工具 (2026-05-14 / 2026-05-16 P0 加测试套件 + 退码统一)

### 入口

- venv 已激活: `bws <group> <action>`
- 任意目录: `预报价系统B端版本\bws.bat <group> <action>` (纯 ASCII,中文 Windows cmd 友好)
- 模块直调: `python -m app.cli <group> <action>` (cwd=backend/;2026-05-16 起需要 `__main__.py`,之前是死代码)

### 命令矩阵

```
bws quote   list [-n] [--agency]        列报价单
            show <id>                   报价单详情
            calc <id> [--save]          dry-run 拆解; --save 走完整 recalc (utils/quote_recalc) — cost/feasibility/gamble/profit/price 一并落库,与 web 端 routers/quotes.py::calculate_quote 一致
bws data    import [--apply] [--only] [--json]   调 scripts/import_bali_data.py; --json 输出结构化汇总 (cron/上游集成)
            export [path]               sqlite3.iterdump → SQL 文件 (读 settings.database_url)
            backup [--tag]              DB 复制到 backend/data/backups/ (读 settings.database_url)
            restore <file> [--yes]      自动备份旧 DB 后恢复 (读 settings.database_url)
bws server  start [--no-reload]         前台 uvicorn (cwd=backend/)
            status                      探活 /api/v1/health
            stop [--yes]                netstat 找 PID → taskkill /F
bws db      init [--no-seed]            create_all + 自举 admin (2026-05-16 起 ALTER 列表删, schema 变更走 alembic)
            migrate [--revision head]   alembic upgrade (2026-05-16 起真生效)
            query "<SELECT...>" [-n]    只读 SQL, 写动词自动拒
            stats                       各表行数
bws dev     [--no-server] [--no-seed]   一键: init + migrate + uvicorn 前台 (取代 scripts/start.bat 的 step 2+3)
```

### 文件布局

```
预报价系统B端版本/
├── pyproject.toml        ← entry_point: bws = app.cli:main
├── bws.bat               ← 纯 ASCII 包装器
├── backend/app/cli/
│   ├── __init__.py       ← argparse 顶层 + UTF-8 stdio fix + CliError 翻译
│   ├── __main__.py       ← 2026-05-16 新增, 支持 python -m app.cli
│   ├── _common.py        ← print_table / confirm / CliError/BusinessError/UsageError + 退码 SSOT 注释
│   ├── quote_cmd.py
│   ├── data_cmd.py
│   ├── server_cmd.py
│   ├── db_cmd.py
│   └── dev_cmd.py        ← 2026-05-16 新增, bws dev 一键启动
└── backend/tests/        ← 2026-05-16 新增, pytest 30 用例
    ├── conftest.py       ← bws / seed_quote fixtures
    ├── test_cli_smoke.py
    ├── test_cli_db.py
    ├── test_cli_data.py
    ├── test_cli_data_import_json.py
    ├── test_cli_quote.py
    ├── test_cli_server.py
    └── test_cli_dev.py
```

### 安装

```powershell
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe -m pip install -e .
# 之后 .venv\Scripts\bws.exe 就可用
```

### 设计取舍

- **生产新依赖** — 2026-05-16 加 `alembic`(为 schema 迁移)+ `Mako`(alembic 传递依赖);**pytest 仅测试用,未进 pyproject**
- **写 SQL 兜底拒绝** — 前缀匹配 insert/update/delete/drop/alter/create/truncate/replace,要写就连 sqlite3 cli;**触发 UsageError(2)**
- **退码语义 SSOT** 在 `_common.py` 顶部:0 成功 / 1 业务错误 (BusinessError) / 2 用法错误 (UsageError, argparse 同号) / 130 Ctrl+C
- **handler 抛异常而不是 return** — `raise BusinessError("...")` / `raise UsageError("...")`,`__init__.main()` 统一翻退码 + 打 stderr 带类型前缀
- **.bat 纯 ASCII** — Write 工具默认 UTF-8,但 Windows cmd 在中文系统下按 GBK 解,中文会乱码

### 测试

- 位置: `backend/tests/test_cli_*.py`,共 27 用例
- 跑法: `.venv\Scripts\python.exe -m pytest backend/tests/ -v` (约 24s)
- 模式: subprocess 黑盒 + `tmp_path` 下临时 SQLite (通过 `BWS_DATABASE_URL` 切换),`conftest.py` 提供 `bws` runner + `seed_quote` fixture

### 2026-05-16 修的 3 个真 bug

1. `app/cli/__main__.py` 缺失 → `python -m app.cli` 跑不通(`__init__.py` 里 `if __name__ == "__main__"` 是死代码)
2. `data_cmd._db_path()` 硬编码 → 即使设了 `BWS_DATABASE_URL`,backup/export/restore 仍偷偷操作主库;现已改读 `settings.database_url`(非 sqlite 抛 UsageError)
3. `utils/quote_recalc.recalc_quote` v0.9.0 抽出来号称"router 与 CLI 共用",但 CLI 一直没接通;现已真正接通

### Alembic (2026-05-16 接入)

- `backend/alembic.ini` + `backend/migrations/env.py`(env.py 读 `settings.database_url` SSOT,sqlite 自动 `render_as_batch=True`)
- 基线: `migrations/versions/0000_baseline.py` 是**空迁移**(upgrade/downgrade 都 pass)— 表示"2026-05-16 时 `init_db()` 能建出的 schema 就是 v0 基线"
- **生产 DB 一次性**: `python -m alembic stamp 0000_baseline`(创建 `alembic_version` 表,标记已在基线);之后 `bws db migrate` 才会跑 0001+ 的真迁移
- 新增字段/改表: 改 ORM 模型 → `python -m alembic revision --autogenerate -m "..."` → 人工核对 → `bws db migrate`
- 详细操作手册 `backend/migrations/README.md`
- alembic.ini 注释必须 ASCII (configparser 在 Windows 用 GBK 读, 中文会爆 UnicodeDecodeError)

### 已知未做(真要做需专项立项)

- **彻底走 alembic 唯一 schema 来源**:当前 `init_db` 仍 `create_all` 建表(ALTER 列表已删,新字段走 alembic);真正"alembic 唯一"需要 autogenerate 0001 反映完整 v0.8.x schema + 改 `init_db` 为 "alembic upgrade head" + 探测无 `alembic_version` 表时自动 stamp。sqlite autogenerate 假阳性需要逐条人工核对,工期 1-2 小时
