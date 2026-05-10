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
   ├─[2]─▶ _check_gamble_strategies()   # ★ v0.3 主路径
   │         按 priority desc 遍历 active strategies
   │         首条 conditions 全 AND 命中 → 返回(skip/fixed/per_pax)
   │
   ├─[3]─▶ _check_no_gamble_rules()     # legacy 兜底(旧表 NoGambleRule)
   │
   └─[4]─▶ 老经验值算法(自由时间因子+自费重叠+客户/季节系数)  # 最终兜底
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

- 老 `NoGambleRule` 表 5 条 seed → seed_all 自动 + `POST /settings/gamble-strategies/migrate-from-no-gamble` 一次性 INSERT
- 迁移幂等(按 name 去重),重跑只看 `migrated/skipped_duplicate` 数字
- 老表保留不删(留作历史查询; v0.4 决定是否删)

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

