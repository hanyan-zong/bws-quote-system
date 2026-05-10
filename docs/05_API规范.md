# 05 · API 规范

> 版本 v0.1 | 2026-05-05
> Base URL: `http://localhost:8000/api/v1`
> 全部 JSON / UTF-8；时间字段 ISO 8601；错误返回 `{"error": {"code": "...", "message": "..."}}`

---

## 路由总览

| Group | Path | 说明 |
|-------|------|------|
| 资源库 | `/resources/...` | 酒店/景点/餐厅/车辆/导游/SPA/水上/下午茶/自费 |
| 距离 | `/distances` | 距离矩阵管理 |
| 模板 | `/templates` | 一日游模板 |
| 报价 | `/quotes` | 报价单 CRUD + 计算 |
| AI | `/ai/parse` | 文档上传与解析 |
| 校验 | `/feasibility/{quote_id}` | 行程合理性校验 |
| 赌自费 | `/gamble/recommend` | 赌额推荐 |
| 设置 | `/settings/...` | 汇率、时间预算、赌自费配置 |
| 导出 | `/quotes/{id}/export?format=xlsx\|pdf` | 文档导出 |

---

## 资源库（每类资源独立 endpoint）

### `GET /resources/hotels`
```
?destination_code=DPS&star=4&keyword=mulia
```
返回酒店列表（含房型）。

### `POST /resources/hotels`
请求：
```json
{
  "destination_code": "DPS",
  "name_zh": "巴厘岛丽思卡尔顿",
  "name_en": "The Ritz-Carlton Bali",
  "star": 5,
  "area": "努沙杜瓦",
  "latitude": -8.797,
  "longitude": 115.218,
  "airport_distance_min": 30,
  "rooms": [
    {"room_type": "Sawangan Junior Suite", "max_occupancy": 2,
     "breakfast_included": true,
     "cost_idr_low": 4500000, "cost_idr_high": 6200000,
     "valid_from": "2026-01-01", "valid_to": "2026-12-31"}
  ]
}
```

### `PUT /resources/hotels/{id}` / `DELETE /resources/hotels/{id}`

### 其他资源同样模式（restaurants/attractions/vehicles/guides/spa/water/tea/optional）

---

## 距离矩阵

### `GET /distances`
```
?from_type=hotel&from_id=1
```
返回该 POI 到所有其他 POI 的距离。

### `POST /distances/batch`
批量上传距离。

### `POST /distances/auto-fill`
触发 Google Distance Matrix 批量回填（v0.2）。

---

## 一日游模板

### `GET /templates?destination_code=DPS`
返回该目的地全部模板（含关联的景点/餐厅）。

### `POST /templates`
```json
{
  "destination_code": "DPS",
  "name_zh": "乌布文化一日游",
  "description": "圣猴森林+德格拉朗+乌布皇宫+乌布市场",
  "total_minutes_estimate": 480,
  "recommended_pax_min": 2,
  "recommended_pax_max": 17,
  "difficulty": "easy",
  "attractions": [
    {"attraction_id": 12, "order_index": 1, "stay_minutes": 90},
    {"attraction_id": 15, "order_index": 2, "stay_minutes": 60},
    {"attraction_id": 18, "order_index": 3, "stay_minutes": 45},
    {"attraction_id": 20, "order_index": 4, "stay_minutes": 60}
  ],
  "restaurants": [
    {"restaurant_id": 7, "meal_type": "lunch"},
    {"restaurant_id": 9, "meal_type": "lunch"}
  ]
}
```

---

## 报价单

### `POST /quotes`
创建草稿报价单。
```json
{
  "agency_name": "上海康辉",
  "customer_name": "李先生 4 人蜜月",
  "pax_adult": 2,
  "pax_child": 0,
  "start_date": "2026-08-12",
  "end_date": "2026-08-16",
  "destination_codes": ["DPS"],
  "season": "high",
  "customer_type": "honeymoon",
  "days": [
    {
      "day_index": 1, "is_free": false,
      "hotel_id": 5, "hotel_room_id": 12,
      "vehicle_id": 3, "guide_id": 2,
      "lunch_restaurant_id": 7,
      "attractions": [{"attraction_id": 12, "order_index": 1}]
    },
    {"day_index": 2, "is_free": false, "template_id": 3, ...},
    {"day_index": 3, "is_free": true, "hotel_id": 5},
    {"day_index": 4, "is_free": true, "hotel_id": 5},
    {"day_index": 5, "is_free": false, ...}
  ]
}
```
返回：`{"id": 1234, "quote_no": "Q20260505001"}`

### `POST /quotes/{id}/calculate`
触发计价 + 校验 + 赌自费推荐。返回完整计算结果（成本/售价/校验报告/赌额建议）。

### `GET /quotes/{id}` / `PUT /quotes/{id}` / `DELETE`

### `GET /quotes?status=draft&start_date_from=2026-05-01`

---

## AI 解析

### `POST /ai/parse`
表单上传，字段 `file`。
```
Content-Type: multipart/form-data

file: <binary>
hint: "酒店报价表"  (可选，告诉 AI 优先按某类资源解析)
```
返回：
```json
{
  "extraction_id": 89,
  "file_name": "JKT_HOTEL_2026.pdf",
  "file_type": "pdf",
  "extraction_summary": "识别到 12 家酒店",
  "resources": [...],
  "warnings": [...]
}
```

### `POST /ai/parse/{extraction_id}/confirm`
用户在前端编辑后确认入库：
```json
{
  "confirmed_resources": [
    {"resource_type": "hotel_room", "data": {...}},
    ...
  ]
}
```

### `GET /ai/extractions?status=pending`
查待确认的解析结果。

---

## 行程合理性校验

### `POST /feasibility/{quote_id}`
触发校验：
```json
{
  "overall_feasible": false,
  "days": [
    {
      "day_index": 1,
      "feasible": true,
      "drive_minutes": 180,
      "warnings": [],
      "errors": [],
      "ai_review": {"score": 8, "issues": [], "improved_route": []}
    },
    {
      "day_index": 2,
      "feasible": false,
      "drive_minutes": 380,
      "errors": ["总驾驶 380min 超过上限 300min"],
      "warnings": [],
      "ai_review": {
        "score": 3,
        "issues": ["跨南北过长", "晚餐绕路"],
        "improved_route": [...]
      },
      "suggestions": [
        {"type": "remove_dinner",
         "description": "去掉金巴兰晚餐，改在 Ubud 用餐",
         "delta_drive_minutes": -130,
         "patch": {"dinner_restaurant_id": 9}},
        {"type": "swap_days",
         "description": "把京打玛尼挪到 Day 3",
         "patch": {...}}
      ]
    }
  ]
}
```

### `POST /feasibility/{quote_id}/apply-suggestion`
一键应用建议：
```json
{"day_index": 2, "suggestion_index": 0}
```
返回更新后的 quote。

---

## 赌自费

### `POST /gamble/recommend`
```json
{
  "quote_id": 1234
}
```
返回：
```json
{
  "recommended_cny": 450,
  "low_bound_cny": 270,
  "high_bound_cny": 540,
  "ai_confidence": 0.78,
  "reasoning": "...",
  "configured_optional_tours": [
    {"name": "海豚日出团", "sale_price_cny": 380, "predicted_purchase_rate": 0.85, "expected_revenue_cny": 323},
    ...
  ],
  "applied_to_quote": false
}
```

### `POST /gamble/apply`
```json
{"quote_id": 1234, "applied_cny": 450}
```

### `POST /gamble/feedback`
成单后回写实际收益（反哺模型）：
```json
{
  "quote_id": 1234,
  "optional_tours_revenue_cny": 1850,
  "profit_actual_cny": 4200,
  "won_or_lost": "won"
}
```

---

## 设置

### `GET/PUT /settings/exchange-rate`
```json
{"rate_cny_to_idr": 2300, "effective_date": "2026-05-05", "set_by": "admin"}
```

### `GET/PUT /settings/time-budget`
```json
{
  "max_drive_minutes_per_day": 300,
  "morning_peak_coef": 1.4,
  "evening_peak_coef": 1.55,
  "holiday_coef": 1.65,
  "hotel_to_first_max_minutes": 90,
  "airport_buffer_minutes": 60
}
```

### `GET/PUT /settings/gamble-config`
（参考 04 文档第 8 节）

---

## 导出

### `GET /quotes/{id}/export?format=xlsx`
返回 Excel 文件流（attachment）。

### `GET /quotes/{id}/export?format=pdf`
返回 PDF 文件流（WeasyPrint）。

### `GET /quotes/{id}/export?format=docx`
返回 Word 文件流（python-docx）。

---

## 错误码

| code | 含义 |
|------|------|
| `RESOURCE_NOT_FOUND` | 资源 ID 不存在 |
| `DUPLICATE_RESOURCE` | 唯一性约束冲突 |
| `INVALID_RESOURCE_DATA` | 字段校验失败 |
| `AI_API_KEY_MISSING` | 未配置 ANTHROPIC_API_KEY |
| `AI_PARSE_FAILED` | 解析过程失败 |
| `FEASIBILITY_FAILED` | 行程不可行（详情在 detail） |
| `EXCHANGE_RATE_INVALID` | 汇率值不合法 |
| `EXPORT_FAILED` | 文档导出失败 |

---

## 认证（v0.2）

- v0.1 无认证（本地单机运行）
- v0.2 引入 JWT：登录 `/auth/login` → 获 token → Authorization: Bearer ...
- 角色：admin（资源 + 用户管理）/ agent（B 端旅行社用户，仅报价相关）/ viewer（只读）

---

## 下一篇 → `06_开发日志.md`
