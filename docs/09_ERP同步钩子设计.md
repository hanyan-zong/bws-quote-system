# 09 · ERP 同步钩子深度优化思考 (v0.4)

> 版本 v0.4 | 2026-05-08
> 用户决策：**自费回写暂不写入 ERP，但保留 API 和随时写入 ERP 机制**

---

## 一、问题定义

### 业务背景
公司有现成 ERP 系统（母库 `07_ERP系统/`，PHP CodeIgniter）。
当前预报价系统是"前置工具" — 出报价单。
未来某天，业务员说"成单了"时：
- 该 quote 应推到 ERP 创建订单
- 该 quote 关联的客户信息应同步
- 团结束后财务录入实际自费数据，应回流 ERP 财务模块

### 决策（用户原话）
> "自费回写不用写入 ERP 暂时，但是要保留 API 和随时写入 ERP 机制深度优化思考"

**翻译**：
1. **不实现** — 这次不真的对接 ERP（避免双向耦合 + 联调成本）
2. **必须留接口** — 数据要能在事件发生时记录下来（事件队列）
3. **必须留机制** — 未来想接 ERP 时，加一个 worker 消费队列就能用，不用动核心业务代码
4. **深度优化思考** — 想清楚事件类型 + 重试 + 失败处理 + 可观测性

---

## 二、设计原则

### 1. 解耦核心业务与 ERP
> 核心业务任何时候都不能因为"ERP 挂了" / "ERP 接口慢" 而失败。

实现方式：**事件队列模式**（outbox pattern）

```
┌──────────────────────────────────────────────────┐
│  核心业务 (Quote create/update/feedback)          │
│  ↓ 事务内同时写一条事件                            │
│  ┌────────────────────┐                          │
│  │ erp_sync_events     │  ← 仅写本地 SQLite       │
│  │ (status=pending)    │                          │
│  └─────┬───────────────┘                          │
└────────┼─────────────────────────────────────────┘
         │ (异步)
         ▼
┌──────────────────────┐
│  ErpSyncWorker        │  ← v0.5 才真正实现
│  ─ 轮询 pending       │
│  ─ POST 到 ERP webhook│
│  ─ 失败重试 + 指数退避 │
│  ─ 成功 status=synced │
└──────────────────────┘
```

### 2. 至少一次投递（at-least-once）
- 业务事务 + 事件 INSERT 在同一 SQL transaction
- worker 处理失败 → 不删事件 → 下次重试
- 重试 5 次后转 `failed` 状态 → 人工干预

### 3. 幂等性靠 ERP 端做（建议）
- 事件 payload 带唯一标识（如 `quote_no`）
- ERP webhook 端用 `quote_no` 做主键 UPSERT
- 重复投递不引发重复订单

### 4. 可观测性
- super_admin 面板能看队列：pending / synced / failed 计数
- 失败事件能看完整 payload + 最后错误信息 + 重试次数
- 手动重试按钮

---

## 三、数据模型

### `erp_sync_events`

```python
class ErpSyncEvent(Base):
    __tablename__ = "erp_sync_events"

    id: int PK
    event_type: str(40)         # 见下表
    entity_type: str(40)        # quote / gamble_history / agency / user
    entity_id: int              # 关联 ID
    payload: Text (JSON)        # 完整事件载荷（含上下文）

    status: str(20)             # pending / synced / failed / skipped
    retry_count: int = 0
    max_retries: int = 5
    next_retry_at: DateTime NULL  # 指数退避用
    last_error: Text NULL
    last_attempt_at: DateTime NULL

    created_at: DateTime
    synced_at: DateTime NULL
    synced_by_user_id: int FK NULL  # 手动标记同步的人
    correlation_id: str(40) NULL    # 可选 — 把多个事件串起来
```

### 事件类型清单

| event_type | 触发时机 | payload 关键字段 |
|------------|---------|-----------------|
| `quote.accepted` | quote.status 变 accepted | quote_no, agency_name, customer_name, pax, dates, price_cny_total, days[] |
| `quote.cancelled` | quote.status 变 lost | quote_no, reason |
| `gamble.feedback` | POST /gamble/feedback | quote_no, optional_tours_revenue_cny, profit_actual_cny, won_or_lost |
| `agency.created` | super_admin 建新社 | agency_id, name, contact |
| `agency.suspended` | agency.status 变 suspended | agency_id |
| `user.created` | 新用户激活（注册成功） | user_id, agency_id, role |

---

## 四、API 设计

### 列队列

```
GET /api/v1/erp-sync/events
  ?status=pending|synced|failed|skipped
  &event_type=quote.accepted
  &page=1&page_size=50
```

返回：
```json
{
  "total": 42,
  "summary": {"pending": 5, "synced": 30, "failed": 2, "skipped": 5},
  "items": [
    {
      "id": 123,
      "event_type": "quote.accepted",
      "entity_type": "quote",
      "entity_id": 456,
      "payload": {...},
      "status": "pending",
      "retry_count": 0,
      "created_at": "2026-05-08T10:32:00Z"
    }
  ]
}
```

### 手动操作

```
POST /api/v1/erp-sync/events/{id}/mark-synced
   body: {note: "已在 ERP 手动建单 / external_ref: ORD-2026-1234"}

POST /api/v1/erp-sync/events/{id}/skip
   body: {reason: "测试数据，不入 ERP"}

POST /api/v1/erp-sync/events/{id}/retry
   → 立即触发一次同步尝试 (v0.5 worker 接入后才真生效；v0.4 仅重置 status=pending)
```

### 配置

```
GET /api/v1/erp-sync/config
PUT /api/v1/erp-sync/config
   body: {
     enabled: false,                      # v0.4 默认关闭
     webhook_url: "https://erp.bwstravel.com/webhook/v1",
     auth_token: "...",                    # 加密存储
     retry_max: 5,
     retry_backoff_seconds: 60             # 第 N 次重试前等 N×60s
   }
```

存储建议：用 `gamble_config` 同款 key-value 表（或单独 `erp_config` 表）。AUTH token 用 Fernet 加密。

---

## 五、Hook 在哪些地方钉？

### A · Quote 状态机改动

`routers/quotes.py` 加 PUT `/quotes/{id}/status`：

```python
@router.put("/{quote_id}/status")
def update_quote_status(quote_id, payload: QuoteStatusIn, db, user):
    quote = db.get(Quote, quote_id)
    old_status = quote.status
    quote.status = payload.status
    db.flush()

    # ★ 钉子
    if old_status != "accepted" and quote.status == "accepted":
        _enqueue_erp_event(db, "quote.accepted", "quote", quote.id, _quote_payload(quote))
    elif old_status != "lost" and quote.status == "lost":
        _enqueue_erp_event(db, "quote.cancelled", "quote", quote.id,
                          {"quote_no": quote.quote_no, "reason": payload.reason})
    db.commit()
```

辅助函数（放 `utils/erp_hook.py`）：

```python
def _enqueue_erp_event(db: Session, event_type: str, entity_type: str,
                      entity_id: int, payload: dict, correlation_id: str | None = None):
    """统一入口 — 检查启用状态后写事件队列."""
    cfg = _load_erp_config(db)
    if not cfg.enabled:
        # 完全关闭 → 不写队列(避免数据膨胀)。可选：写但 status=skipped 留审计
        return
    db.add(ErpSyncEvent(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=json.dumps(payload, ensure_ascii=False),
        status="pending",
        correlation_id=correlation_id,
    ))
    # 不 commit, 让外层业务 commit 一起写（保证事务一致性）
```

> **重要**：不在钩子里 `db.commit()`，由外层业务事务统一提交。这样如果业务回滚（如计算失败），事件也跟着回滚，不会出现"业务失败但事件已发"的脏数据。

### B · gamble feedback

`routers/gamble.py` POST `/feedback`：

```python
def feedback(payload, db, user):
    history = ...  # 已有逻辑
    history.optional_tours_revenue_cny = payload.optional_tours_revenue_cny
    ...
    # ★ 钉子
    _enqueue_erp_event(db, "gamble.feedback", "gamble_history", history.id, {
        "quote_no": history.quote.quote_no,
        "optional_tours_revenue_cny": float(payload.optional_tours_revenue_cny),
        "profit_actual_cny": float(payload.profit_actual_cny),
        "won_or_lost": payload.won_or_lost,
    })
    db.commit()
```

### C · agency / user 变更（v0.4.1 加）

延迟到 v0.4.1：等 user/agency router 写完后再补钩子。当前 v0.4 先把核心两个事件（quote.accepted + gamble.feedback）打通即可。

---

## 六、ERP 端协议提案（给未来对接团队）

> 给 ERP（PHP）端开发者的接口约定 — v0.5 实施

### Webhook endpoint

```
POST https://erp.bwstravel.com/webhook/v1/bws-quote-events
Headers:
  Authorization: Bearer <token>
  X-Bws-Event-Type: quote.accepted
  X-Bws-Event-Id: 123
  X-Bws-Idempotency-Key: <quote_no>     # 用 quote_no 做幂等键
Body: { ...payload... }
```

ERP 端要求：
1. 200/201 → 同步成功
2. 4xx → 数据有问题，标记 failed，**不重试**（人工修）
3. 5xx / timeout → 标记重试，指数退避（60s, 120s, 240s, 480s, 960s）
4. 重复投递（同 idempotency key）→ ERP 端用 UPSERT 不要建重复订单

### Payload 示例 (`quote.accepted`)

```json
{
  "event_id": 123,
  "event_type": "quote.accepted",
  "occurred_at": "2026-05-08T10:32:00+08:00",
  "agency": {
    "id": 1,
    "name": "上海康辉",
    "short_name": "SHKH"
  },
  "quote": {
    "quote_no": "Q20260508103200001",
    "customer_name": "李先生 蜜月",
    "pax_adult": 2,
    "pax_child": 0,
    "start_date": "2026-08-12",
    "end_date": "2026-08-16",
    "destination_codes": ["DPS"],
    "season": "high",
    "customer_type": "honeymoon",
    "exchange_rate": 2300.00,
    "cost_idr_total": 28280000.00,
    "cost_cny_total": 12295.65,
    "profit_cny_per_pax": 400.00,
    "gamble_cny_per_pax": 450.00,
    "price_cny_per_pax": 6340.91,
    "price_cny_total": 12681.82,
    "feasibility_status": "warning"
  },
  "days": [
    {"day_index": 1, "date": "2026-08-12", "is_free": false,
     "hotel_id": 5, "hotel_room_id": 12, "vehicle_id": 3, "guide_id": 2,
     "lunch_restaurant_id": 7, "attractions": [{"id": 12}, {"id": 15}]},
    ...
  ],
  "created_by_user": {"id": 8, "username": "wang_zh", "role": "agency_owner"}
}
```

---

## 七、Worker 设计（v0.5 实施）

### 选型对比

| 方案 | 优点 | 缺点 |
|-----|------|------|
| FastAPI BackgroundTasks | 原生，零依赖 | 进程内，重启丢任务 |
| Celery + Redis | 成熟，重试机制完善 | 增加 Redis 运维负担 |
| **APScheduler 轮询 SQLite** | 进程内 + 数据持久化 + 简单 | 单实例（v0.5 单租户够用） |
| Cron + 独立 Python 脚本 | 解耦最彻底 | 增加部署复杂度 |

**推荐 APScheduler**：

```python
# app/utils/erp_worker.py (v0.5 创建)
from apscheduler.schedulers.background import BackgroundScheduler

def sync_pending_events():
    with session_scope() as db:
        cfg = _load_erp_config(db)
        if not cfg.enabled:
            return
        events = db.query(ErpSyncEvent).filter_by(status="pending").filter(
            (ErpSyncEvent.next_retry_at.is_(None)) |
            (ErpSyncEvent.next_retry_at <= datetime.utcnow())
        ).limit(20).all()
        for ev in events:
            try:
                _post_to_erp(cfg, ev)
                ev.status = "synced"
                ev.synced_at = datetime.utcnow()
            except RetryableError as e:
                ev.retry_count += 1
                ev.last_error = str(e)
                if ev.retry_count >= ev.max_retries:
                    ev.status = "failed"
                else:
                    ev.next_retry_at = datetime.utcnow() + timedelta(
                        seconds=cfg.retry_backoff_seconds * (2 ** ev.retry_count))
            except FatalError as e:
                ev.status = "failed"
                ev.last_error = str(e)

scheduler = BackgroundScheduler()
scheduler.add_job(sync_pending_events, "interval", minutes=1)
scheduler.start()
```

启动时机：在 `main.py::create_app()` 的 `@app.on_event("startup")` 里启动。

---

## 八、监控与告警（v0.5+）

- super_admin 面板"🔄 ERP 同步队列"卡片：
  - 大数字：pending / synced / failed
  - 失败列表 + 一键重试按钮 + 详情查看 payload/error
  - 折线图：过去 7 天每日成功率
- 当 failed 计数 > 5 → 弹 toast 警告
- 集成到通用 logging：失败事件 ERROR 级别，便于 Sentry 抓

---

## 九、deferred 决策（不做但留位）

| 项 | 暂不做 | 何时做 |
|---|--------|-------|
| 事件回放接口 | ✗ | v0.6（重大故障恢复） |
| 双向同步（ERP → quote） | ✗ | v1.0（先单向跑稳） |
| 事件版本化（schema 演进） | ✗ | 出现 v2 payload 时再加 |
| 与 Kafka / RabbitMQ 集成 | ✗ | 上 PG + 数据量 > 100k 事件/天 才考虑 |

---

## 十、v0.4 落地 checklist（最小可用）

- [ ] `models/system.py` 加 `ErpSyncEvent`
- [ ] `models/system.py` 加 `ErpConfig`（key-value，单条）
- [ ] `utils/erp_hook.py` `_enqueue_erp_event()` 工具函数
- [ ] `routers/quotes.py` 加 PUT `/status` + 钩子
- [ ] `routers/gamble.py` 加钩子（POST /feedback）
- [ ] `routers/erp_sync.py`（新文件）4 个端点
- [ ] 前端 super_admin 看到 "🔄 ERP 同步队列" 卡片（仅展示，无 worker）
- [ ] 默认 `erp_config.enabled=false` — 不写事件，等真正要用时再开

---

**核心思想：留接口不留代码包袱。** 一行 `enabled=false` 让事件机制完全静默，业务零负担。等 v0.5 真要对接时打开开关 + 加 worker 即可。
