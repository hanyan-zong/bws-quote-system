# 今日工作记录 · 2026-05-16

> 关键词:**bws CLI 体系工程化完成** — 测试套件 + 退码语义统一 + Alembic + bws dev + init_db 重构 + 3 个真 bug 修复 + GitHub 新仓库 v0.9 release

> 触发:用户单输入 "cli" → "继续未做事情" 连续 4 轮指令推进 12 个 Step + 收尾

---

## 一、动机:解决 `下次深度优化方向_2026-05-14_CLI.md` 列的全部 P0/P1

| 5/14 列的待办 | 今天完成情况 |
|---|---|
| 🔴 P0 CLI 测试套件 | ✅ `backend/tests/` 30 用例,subprocess + tmp SQLite fixture |
| 🔴 P0 `bws quote calc --save` 完整 recalc | ✅ 接通 `utils/quote_recalc.recalc_quote` |
| 🟡 P1 退码语义统一 | ✅ CliError/BusinessError(1)/UsageError(2)/130 SSOT 在 `_common.py` |
| 🟡 P1 `bws data import` JSON 输出 | ✅ `--json` + 正则解析子脚本汇总 |
| 🟢 P2 Shell 补全 | ❌ 未做(收益偏低,工期与 alembic 单源冲突) |

**附加未在 5/14 计划中、临场决定做的事**:
- ✅ Alembic 接入(memory 里 P0,但 5/14 文档没列)
- ✅ `bws dev` 一键启动(取代 `scripts/start.bat` 的 step 2+3)
- ✅ 删 `init_db()` 的 19 条 ALTER 兼容列表
- ✅ GitHub 新仓库 `bws-quote-system` + v0.9 Release

---

## 二、Step 1-12 推进日志(每步反思后接下一步)

按 `feedback_no_fantasy_reflect_each_step.md` 纪律,每完成一个最小可验证单元就停下来 reflect/verify/optimize/deep-think。

### Step 1 — tests 骨架 + smoke 测试
- 新建 `backend/tests/__init__.py` + `conftest.py`(`bws` runner + `tmp_db_url` fixture) + `test_cli_smoke.py`(5 用例)
- venv 装 `pytest 9.0.3`
- **顺手发现真 bug #1**: `python -m app.cli` 跑不通 — `app/cli/__init__.py` 里 `if __name__ == "__main__"` 是死代码,需要 `app/cli/__main__.py`。补好后 5/5 PASS。

### Step 2 — db 命令测试
- `test_cli_db.py` 4 用例:`init --no-seed` / `stats` / `query SELECT` / `query` 拒绝写
- `query` 拒绝写当时还返 1,标注为 Step 4 改 2 后收紧

### Step 3 — 退码语义统一(纯加性,无回归)
- `_common.py` 顶部加退码 SSOT 注释 + `CliError` / `BusinessError(=1)` / `UsageError(=2)`
- `cli/__init__.main()` catch CliError 翻退码 + 打 `[Type] msg` 到 stderr
- 此步未改任何 handler 行为,9/9 PASS

### Step 4 — 各 cmd 改用新异常类
- db_cmd query 写拒绝 → UsageError(2)
- quote_cmd show/calc 找不到 → BusinessError(1)
- data_cmd import/export/backup/restore 缺失 → BusinessError(1)
- **顺手发现真 bug #2**: `data_cmd._db_path()` 硬编码 `DATA_DIR/bws_quote.db`,**不读 `settings.database_url`** — `bws data backup` 即使设了 `BWS_DATABASE_URL` 也偷偷操作主库。改为解析 `settings.database_url`(非 sqlite 抛 UsageError)
- 测试 12 PASS

### Step 5 — quote 命令测试
- 空表 / 找不到 id / agency filter — 7 用例

### Step 6 — server_cmd 退码一致性
- `start` 端口占用 / `status` 不可达 → BusinessError(1)
- 测试用 `--port 1`(肯定不通)+ `--host 127.0.0.1`(避免出网),2 用例
- `stop` 透传 taskkill 退码保留(透传外部命令是合理设计)

### Step 7 — quote 有数据的测试
- conftest 加 `seed_quote` fixture:subprocess 跑内联 ORM 在 tmp_db 塞一条 Quote,返回 id
- 测试数据全 ASCII 避 PowerShell `-c` 中文编码坑
- list 显示 seeded / show 完整字段 / agency filter 真过滤 — 3 用例

### Step 8 — `bws data import --json`
- `_cmd_import` 加 `--json` 选项,捕获子脚本 stdout
- 抽 `_parse_import_summary(stdout) -> dict[str, dict[str, int]]` 纯函数,正则匹配 `parsed=N ok=N fail=N` 行
- 3 个单测覆盖正常/异常/中文 kind + 1 个 CLI 集成测试

### Step 9 — `bws quote calc --save` 走完整 recalc
- **顺手发现真 bug #3**: `utils/quote_recalc.recalc_quote` v0.9.0 注释明确说"router 与 CLI 共用入口",但 **CLI 当年没接通** — `_cmd_calc --save` 只回写 cost_*,所谓"修复 CLI 漂移"是空话
- 接通后:`--save` 走完整 5 步(cost + feasibility + gamble + profit + price + GambleHistory),与 web 端 `routers/quotes.py::calculate_quote` 完全一致
- 加 2 个落库验证测试:`bws db query SELECT profit_cny_per_pax FROM quotes WHERE id=<seeded>` 验证写了 / dry-run 验证不写

### Step 10a-d — Alembic 接入
- 装 alembic 1.18.4 + Mako 1.3.12 到 venv
- `alembic init backend/migrations`,改 `env.py` 走 `settings.database_url` SSOT,sqlite 自动 `render_as_batch=True`
- **踩 GBK 坑**:`alembic.ini` 加中文注释 → configparser 在 Windows 用 GBK 读 → `UnicodeDecodeError`。改 ASCII
- 手写 `migrations/versions/0000_baseline.py` 空 baseline(不 autogenerate,避免假阳性 diff)
- `_cmd_migrate` 改调 `alembic.command.upgrade(cfg, args.revision)`,加 `--revision` 参数,异常翻 BusinessError
- 2 个 migrate 测试:sqlite3 直查 `alembic_version` 表 + 幂等性
- `migrations/README.md` 写明生产 DB 一次性 `alembic stamp 0000_baseline` 步骤(我从未动过你的生产 DB)

### Step 11 — `bws dev` 一键启动
- 顶层新命令 `bws dev`,顺序跑 `db init` + `db migrate` + `server start`
- 复用 `db_cmd._cmd_init` / `db_cmd._cmd_migrate` / `server_cmd._cmd_start` 三个内部函数(零漂移)
- `--no-server` 给测试用(避免阻塞起 uvicorn)
- 2 个测试

### Step 12 — 删 `init_db()` 的 ALTER 列表
- 用户决策选 A(直接删)
- `init_db` 从 75 行 → 11 行,只剩 `Base.metadata.create_all` + `_ensure_bootstrap_admin`
- docstring 改写新策略 + v0.7 第三方升级路径
- 30 PASS 零回归(证据:ORM 已定义全列,create_all 在新 DB 上等价 ALTER 后的老 DB)

---

## 三、修的 3 个真 bug(都是"顺手发现"的烂尾)

| # | 文件 | 性质 | 影响 |
|---|---|---|---|
| 1 | `app/cli/__main__.py` 缺失 | 模块入口未实现 | `python -m app.cli` 跑不通,但 `bws` entry_point 能用 — 长期没人发现 |
| 2 | `data_cmd._db_path()` 硬编码 | SSOT 漂移 | **数据安全隐患** — 测试/隔离环境下 `bws data backup` 操作的是生产 DB |
| 3 | `quote_recalc.recalc_quote` CLI 没接通 | 实现烂尾 | **数据正确性隐患** — `--save` 字面上"保存了重算结果",但实际只写 cost_*,其他派生字段保持脏数据 |

**共同教训**:每个 bug 都有 v0.x 时的"承诺",但缺少**自动化检测机制**(测试套件)→ 谎话留在代码里多版本。今天加的 30 测试就是为防下次。

---

## 四、GitHub 新仓库流程

由用户指令"建立一个新的库自动上传 并且大开最新的版本给我看"触发:

1. 装 gh CLI(winget,踩 PATH 不同步坑,用 `[Environment]::GetEnvironmentVariable + Process` 解决)
2. 用户在浏览器跑 `gh auth login --git-protocol ssh --web` 完成 OAuth(15 秒,**唯一无法自动化的步骤** — GitHub 平台规则)
3. `gh repo create hanyan-zong/bws-quote-system --private --description "..."` 建空仓库
4. `git remote add bws-quote-system <SSH URL>`(保留 origin = bwsb-)
5. `git push -u bws-quote-system main` → 5 commits 全部推上(默认推送目标切到新仓库)
6. `git tag -a v0.9` + push tag
7. `gh release create v0.9` 升级为 GitHub Release(带 notes 页)
8. `gh repo edit --add-topic ...` 加 10 个 topics
9. Branch protection 尝试失败 — Free Private 不支持(老版 + Rulesets 都禁),用户选 D 跳过

**最终 URL**:https://github.com/hanyan-zong/bws-quote-system  
**Release**: https://github.com/hanyan-zong/bws-quote-system/releases/tag/v0.9

---

## 五、最终状态

| 维度 | 之前 | 今天后 |
|---|---|---|
| CLI 测试用例 | 0 | **30 PASS** (28s) |
| 退码 SSOT | 散乱(各 cmd return 1) | `_common.py` 顶部统一 |
| schema 迁移 | `init_db()` 75 行 ALTER 兼容层 | alembic(`bws db migrate` 真生效),`init_db` 11 行 |
| 一键启动 | `scripts/start.bat`(只 bat) | `bws dev`(跨平台 + 测试可验) |
| 真 bug | 3 个被埋多版本 | 全部修 + 测试守护 |
| GitHub | 单 remote `bwsb-` | + 新 private `bws-quote-system`(v0.9 release) |

**全套件 30 PASS,28s。生产 DB 未动。**

---

## 六、关键决策与权衡

1. **空 baseline migration 而非 autogenerate**:autogenerate 在 sqlite 上对默认值/约束有假阳性,会污染 baseline。手写空 baseline + 文档化"未来 0001 起反映真实变更"是更克制的方案。代价:留下"alembic 唯一来源"未完成的尾巴
2. **保留 `bwsb-` 老 remote**:不破坏用户已有引用;新 remote `bws-quote-system` 是默认 push 目标。日后想切回 `git branch --set-upstream-to=origin/main main`
3. **删 ALTER 列表的安全性论证**:用户 DB 已在 v0.8.4,ORM 模型已含全列,`create_all` 在新 DB 拿全;**对当前用户 100% 无影响**。v0.7 第三方升级路径在 docstring 写明
4. **Branch protection 跳过**:Free Private 不支持,单人开发风险极低
5. **pytest 不进 pyproject.toml**:仅测试用,不污染生产依赖

---

## 七、文件改动总账

| 类型 | 数量 | 列表 |
|---|---|---|
| 修改的源码 | 7 | `cli/__init__.py` / `_common.py` / `data_cmd.py` / `db_cmd.py` / `quote_cmd.py` / `server_cmd.py` / `database.py` |
| 新建的源码 | 3 | `cli/__main__.py` / `cli/dev_cmd.py` / `utils/quote_recalc.py` (之前未 commit) |
| 新建的测试 | 8 | conftest + 7 个 test_cli_*.py |
| Alembic 框架 | 4 | alembic.ini + migrations/env.py + 0000_baseline.py + migrations/README.md |
| 文档 | 3 | SKILL 第十四节 / migrations/README.md / 本文件 + 下次方向 |
| 其他 | 1 | .gitignore 加 `bws_export_*.sql` 规则 |
| **合计** | **26** | |

---

## 八、给下次的提示

详见 `下次深度优化方向_2026-05-16_alembic单源.md`,重点:
- 🔴 P0 alembic 单源 — 让 `init_db()` 不再 create_all,完全靠 alembic upgrade(独立专项,1-2h + sqlite autogenerate 假阳性核对)
- 🟡 P1 把 ALTER 列表的历史迁成 0001/0002... 真实 migration 而不是纯靠 ORM 反推(可选,看是否要"完整 migration history")
- 🟢 P2 Shell 补全(5/14 列的 P2,今天没做)
- 🟢 P2 把 `scripts/start.bat` 删了或改成 `bws dev` 包装
