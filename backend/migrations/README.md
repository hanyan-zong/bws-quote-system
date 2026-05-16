# Alembic 迁移指南

2026-05-16 接入。在此之前所有 schema 变更走 `app/database.py::init_db()` 的
`ALTER TABLE ADD COLUMN` 兼容层(无版本控制)。从今天起新增的 schema
改动**必须**走 alembic revision。

## 生产 DB 一次性初始化(只跑一次,然后就不用管了)

生产 DB 已经有 v0.8.x schema(`init_db()` 的 ALTER 列表跑完的结果)。
**不要**让 alembic 跑 baseline 的 upgrade,因为它会以为表都没建过。
正确做法是 stamp:

```powershell
cd 预报价系统B端版本/backend
$env:BWS_DATABASE_URL = "sqlite:///data/bws_quote.db"  # 或生产实际值
..\.venv\Scripts\python.exe -m alembic stamp 0000_baseline
```

这会创建 `alembic_version` 表,只写一条 `0000_baseline`,标记"你已经在基线了"。
之后 `bws db migrate` 就只跑 0001 及以后的真迁移。

## 日常加新字段 / 改表

```powershell
cd 预报价系统B端版本/backend
# 1. 改 ORM 模型 (app/models/*.py)
# 2. 让 alembic 比对模型和当前 DB, 自动生成迁移文件
..\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "add foo column"
# 3. 检查生成的 migrations/versions/<rev>_add_foo_column.py 是否合理
#    (autogenerate 对 sqlite 有限制, 默认值/约束改动需要人工核对)
# 4. 应用
..\.venv\Scripts\bws.exe db migrate
```

## 不要做的事

- **不要**在 `app/database.py::init_db()` 的 ALTER 列表里加新行
  — 那是 v0.8 之前的兼容层,只读不写
- **不要**autogenerate 一个跟 baseline 同时间的迁移(0001 不应该重复创建已有的表)
- **不要**在 sqlite 上跑 `ALTER TABLE DROP COLUMN`(原生不支持);用 alembic batch mode
  (env.py 里已经开了 `render_as_batch=True`)

## 跑迁移的几种方式

| 命令 | 作用 |
|---|---|
| `bws db migrate` | 等价 `alembic upgrade head` |
| `bws db migrate --revision <rev>` | upgrade 到指定版本 |
| `python -m alembic current` | 看当前版本 |
| `python -m alembic history` | 看所有版本 |
| `python -m alembic downgrade -1` | 回退一版(慎用) |
| `python -m alembic stamp head` | 强标记到 head(不真跑 — 给生产 DB 初始化用) |

## env.py 关键决定

- `sqlalchemy.url` 从 `app.config.settings.database_url` 注入(SSOT,不在 alembic.ini 里重复)
- `target_metadata = Base.metadata` + import `app.models` 触发 ORM 类注册
- `render_as_batch=True` for sqlite — 让 ALTER 走临时表 + copy + rename
