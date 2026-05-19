"""初始化样本数据 — 让系统启动后立即有可用资源 + 模板 + 距离 + 自费项."""
from __future__ import annotations

import json
from datetime import date, time
from decimal import Decimal

from sqlalchemy.orm import Session

from . import models
from .database import session_scope, init_db


def _ensure_destinations(db: Session) -> dict[str, models.Destination]:
    rows = [
        ("DPS", "巴厘岛", "Bali", "Asia/Makassar"),
        ("CGK", "雅加达", "Jakarta", "Asia/Jakarta"),
        ("SEPA", "瑟帕岛", "Pulau Sepa", "Asia/Jakarta"),
        ("LOK", "龙目岛", "Lombok", "Asia/Makassar"),
        ("KMD", "科莫多岛", "Komodo", "Asia/Makassar"),
    ]
    out: dict[str, models.Destination] = {}
    for code, zh, idn, tz in rows:
        d = db.query(models.Destination).filter_by(code=code).first()
        if not d:
            d = models.Destination(code=code, name_zh=zh, name_id=idn, timezone=tz)
            db.add(d)
            db.flush()
        out[code] = d
    return out


def _seed_settings(db: Session) -> None:
    if not db.query(models.ExchangeRate).first():
        db.add(models.ExchangeRate(
            effective_date=date.today(),
            rate_cny_to_idr=Decimal("2300"),
            set_by="seed",
            note="默认汇率",
            is_current=True,
        ))
    if not db.query(models.TimeBudgetConfig).first():
        db.add(models.TimeBudgetConfig())
    if not db.query(models.GambleConfig).first():
        db.add(models.GambleConfig())


def _seed_hotels(db: Session, dests: dict) -> None:
    if db.query(models.Hotel).count() > 0:
        return
    samples = [
        ("DPS", "巴厘岛 The Mulia", "The Mulia Bali", 5, "努沙杜瓦", -8.797, 115.218, 30, [
            ("Mulia Suite", 2, True, 4500000, 5800000),
            ("Junior Suite Garden", 2, True, 3200000, 4100000),
        ]),
        ("DPS", "丽思卡尔顿巴厘岛", "Ritz-Carlton Bali", 5, "努沙杜瓦", -8.831, 115.220, 35, [
            ("Sawangan Junior Suite", 2, True, 5000000, 6500000),
            ("Cliff Villa", 4, True, 9500000, 12000000),
        ]),
        ("DPS", "乌布四季度假村", "Four Seasons Sayan", 5, "乌布", -8.485, 115.249, 75, [
            ("Riverfront Suite", 2, True, 8500000, 11000000),
        ]),
        ("DPS", "库塔风情酒店", "Hard Rock Hotel Bali", 4, "库塔", -8.722, 115.169, 15, [
            ("Deluxe Room", 2, True, 1500000, 2000000),
        ]),
        ("CGK", "雅加达索菲特酒店", "Sofitel Jakarta", 5, "市中心", -6.224, 106.816, 35, [
            ("Deluxe Room", 2, True, 2200000, 2800000),
        ]),
        ("SEPA", "瑟帕岛度假村", "Pulau Sepa Resort", 4, "瑟帕岛", -5.616, 106.572, 0, [
            ("Cottage Standard", 2, True, 1800000, 2400000),
            ("Cottage Family", 4, True, 3000000, 3800000),
        ]),
    ]
    for code, name_zh, name_en, star, area, lat, lng, ad, rooms in samples:
        h = models.Hotel(
            destination_id=dests[code].id,
            name_zh=name_zh,
            name_en=name_en,
            star=star,
            area=area,
            latitude=lat,
            longitude=lng,
            airport_distance_min=ad,
        )
        db.add(h)
        db.flush()
        for rt, occ, bk, low, high in rooms:
            db.add(models.HotelRoom(
                hotel_id=h.id, room_type=rt, max_occupancy=occ,
                breakfast_included=bk, cost_idr_low=low, cost_idr_high=high,
                valid_from=date(2026, 1, 1), valid_to=date(2026, 12, 31),
                supplier="seed",
            ))


def _seed_attractions(db: Session, dests: dict) -> None:
    if db.query(models.Attraction).count() > 0:
        return
    samples = [
        ("DPS", "圣猴森林", "Sacred Monkey Forest", "乌布", -8.519, 115.259, 80000, 60000, 90, time(9, 0), time(17, 0)),
        ("DPS", "德格拉朗梯田", "Tegalalang Rice Terrace", "乌布", -8.435, 115.279, 25000, 15000, 60, time(8, 0), time(18, 0)),
        ("DPS", "乌布皇宫", "Ubud Royal Palace", "乌布", -8.506, 115.262, 0, 0, 45, time(8, 30), time(17, 30)),
        ("DPS", "乌布市场", "Ubud Traditional Market", "乌布", -8.507, 115.263, 0, 0, 60, time(7, 0), time(18, 0)),
        ("DPS", "京打玛尼火山", "Mount Batur", "京打玛尼", -8.241, 115.375, 50000, 30000, 120, None, None),
        ("DPS", "圣泉寺", "Tirta Empul", "塔木巴克西林", -8.415, 115.315, 75000, 40000, 60, time(8, 0), time(18, 0)),
        ("DPS", "海神庙", "Tanah Lot", "塔巴南", -8.621, 115.087, 75000, 40000, 90, time(7, 0), time(19, 0)),
        ("DPS", "金巴兰海滩", "Jimbaran Beach", "金巴兰", -8.785, 115.165, 0, 0, 120, None, None),
        ("DPS", "乌鲁瓦图断崖", "Uluwatu Temple", "乌鲁瓦图", -8.829, 115.085, 50000, 30000, 90, time(7, 0), time(19, 0)),
        ("DPS", "蓝梦岛一日游", "Lembongan Day Trip", "蓝梦岛", -8.682, 115.453, 850000, 600000, 480, None, None),
        ("CGK", "印尼缩影公园", "Taman Mini Indonesia", "雅加达东", -6.302, 106.892, 25000, 15000, 180, time(8, 0), time(17, 0)),
        ("CGK", "国家纪念塔", "Monas", "雅加达中", -6.175, 106.827, 20000, 10000, 90, time(8, 0), time(16, 0)),
        ("SEPA", "瑟帕岛浮潜点", "Sepa Snorkeling Spot", "瑟帕岛", -5.616, 106.572, 0, 0, 120, None, None),
    ]
    for code, zh, en, area, lat, lng, ta, tc, mins, ot, ct in samples:
        db.add(models.Attraction(
            destination_id=dests[code].id, name_zh=zh, name_en=en, area=area,
            latitude=lat, longitude=lng,
            ticket_idr_adult=ta, ticket_idr_child=tc,
            recommended_minutes=mins, open_time=ot, close_time=ct,
        ))


def _seed_restaurants(db: Session, dests: dict) -> None:
    if db.query(models.Restaurant).count() > 0:
        return
    samples = [
        ("DPS", "脏鸭餐厅", "印尼餐", "both", "乌布", 250000, 60),
        ("DPS", "Murni's Warung", "印尼餐", "lunch", "乌布", 200000, 60),
        ("DPS", "金巴兰海鲜大排档", "海鲜", "dinner", "金巴兰", 350000, 90),
        ("DPS", "Naughty Nuri's", "BBQ", "both", "乌布", 280000, 60),
        ("DPS", "Sundara", "西餐", "dinner", "金巴兰", 750000, 90),
        ("CGK", "印尼传统餐厅", "印尼餐", "both", "市中心", 180000, 60),
        ("SEPA", "瑟帕岛餐厅", "海鲜+西餐", "both", "瑟帕岛", 250000, 60),
    ]
    for code, n, c, mt, area, cost, mins in samples:
        db.add(models.Restaurant(
            destination_id=dests[code].id, name_zh=n, cuisine=c,
            meal_type=mt, area=area,
            cost_idr_per_person=cost, recommended_minutes=mins,
        ))


def _seed_vehicles(db: Session, dests: dict) -> None:
    if db.query(models.Vehicle).count() > 0:
        return
    # (code, seat, type, cost, restrictions, max_leg_min, max_daily_min, terrain_note)
    samples = [
        ("DPS", 7, "Toyota Avanza", 550000, [], None, 480, "灵活, 适合所有路线"),
        ("DPS", 17, "Toyota Hiace", 750000, [], None, 420, "标准车型, 大部分路况 OK"),
        ("DPS", 25, "Mitsubishi Bus", 1200000, ["Monkey Forest", "Canggu Villa"], 150, 360, "山路单段建议 ≤2.5h"),
        ("DPS", 35, "Hino Bus", 1800000, ["Monkey Forest", "Canggu Villa", "BTDC Inner", "Ubud Center"],
         120, 300, "大车单段 ≤2h, 全天 ≤5h, 不进山路狭窄段"),
        ("CGK", 17, "Toyota Hiace", 700000, [], None, 420, None),
        ("CGK", 35, "Hino Bus", 1500000, [], 120, 300, None),
        ("SEPA", 7, "Speedboat Transfer", 2500000, [], None, None, "海上摆渡, 不计陆路"),
    ]
    for code, seat, vt, cost, restrict, leg, daily, note in samples:
        db.add(models.Vehicle(
            destination_id=dests[code].id, seat_count=seat, vehicle_type=vt,
            cost_idr_per_day=cost, restrictions=json.dumps(restrict, ensure_ascii=False),
            max_single_leg_minutes=leg, max_daily_minutes=daily, terrain_note=note,
        ))


def _seed_guides(db: Session, dests: dict) -> None:
    if db.query(models.Guide).count() > 0:
        return
    samples = [
        ("DPS", "中文导游 — 阿杜", "zh", "senior", 800000, 99, None),
        ("DPS", "中文司机 — 王师傅", "zh", "regular", 500000, 3, "仅限 2-3 人小团"),
        ("DPS", "英文导游 — Bayu", "en", "regular", 600000, 99, None),
        ("CGK", "中文导游 — 林师傅", "zh", "regular", 750000, 99, None),
    ]
    for code, n, lang, lvl, cost, mp, note in samples:
        db.add(models.Guide(
            destination_id=dests[code].id, name_zh=n, language=lang, level=lvl,
            cost_idr_per_day=cost, max_pax=mp, availability_note=note,
        ))


def _seed_simple(db: Session, dests: dict) -> None:
    if db.query(models.SpaPackage).count() == 0:
        for code, brand, pkg, dur, cost in [
            ("DPS", "Karma", "经典推油 60min", 60, 350000),
            ("DPS", "Karma", "尊享套餐 120min", 120, 650000),
            ("DPS", "Jari Menari", "巴厘岛传统按摩", 90, 450000),
        ]:
            db.add(models.SpaPackage(
                destination_id=dests[code].id, brand=brand, package_name=pkg,
                duration_minutes=dur, cost_idr_per_person=cost,
            ))
    if db.query(models.WaterActivity).count() == 0:
        for code, n, loc, cost, mins in [
            ("DPS", "蓝梦岛浮潜", "蓝梦岛", 350000, 180),
            ("DPS", "海钓", "Tanjung Benoa", 800000, 240),
            ("DPS", "滑翔伞", "Uluwatu", 1500000, 30),
            ("SEPA", "瑟帕岛跳岛浮潜", "瑟帕岛海域", 600000, 240),
        ]:
            db.add(models.WaterActivity(
                destination_id=dests[code].id, name_zh=n, location=loc,
                cost_idr_per_person=cost, duration_minutes=mins,
            ))
    if db.query(models.AfternoonTea).count() == 0:
        for code, n, ven, area, cost in [
            ("DPS", "Karma 海景下午茶", "Karma Kandara", "乌鲁瓦图", 380000),
            ("DPS", "Hanging Gardens 悬崖下午茶", "Hanging Gardens of Bali", "乌布", 450000),
        ]:
            db.add(models.AfternoonTea(
                destination_id=dests[code].id, name_zh=n, venue=ven, area=area, cost_idr_per_person=cost,
            ))


def _seed_optional_tours(db: Session, dests: dict) -> None:
    if db.query(models.OptionalTour).count() > 0:
        return
    # (code, name, sale_cny, cost_idr, audience, time, rate, category)
    samples = [
        ("DPS", "海豚日出团", 380, 350000, "蜜月,亲子", "凌晨", 0.85, "sunrise"),
        ("DPS", "巴龙舞表演", 180, 150000, "亲子,文化", "上午", 0.7, "performance"),
        ("DPS", "Spa 升级套餐", 260, 250000, "蜜月,女性", "下午", 0.6, "spa"),
        ("DPS", "蓝梦岛深度游", 680, 600000, "亲子,年轻人", "全天", 0.55, "island_trip"),
        ("DPS", "金巴兰夕阳海鲜餐升级", 220, 200000, "蜜月,家庭", "晚上", 0.5, "food_upgrade"),
        ("DPS", "购物村半日", 150, 100000, "all", "下午", 0.4, "shopping"),
        ("CGK", "千岛跳岛半日", 350, 300000, "亲子,年轻人", "上午", 0.4, "water"),
    ]
    for code, n, sp, ci, ta, bt, hp, cat in samples:
        margin = sp - ci / 2300
        db.add(models.OptionalTour(
            destination_id=dests[code].id, name_zh=n,
            sale_price_cny=sp, cost_idr=ci,
            margin_cny=Decimal(str(round(margin, 2))),
            historical_purchase_rate=hp,
            target_audience=ta, best_time=bt, category=cat,
        ))


def _seed_distances(db: Session) -> None:
    """硬编码巴厘岛核心 POI 间距离 (分钟数 + 车型限制)."""
    if db.query(models.Distance).count() > 0:
        return

    ubud_attrs = ["圣猴森林", "德格拉朗梯田", "乌布皇宫", "乌布市场"]
    ubud_ids = {n: a.id for a in db.query(models.Attraction).filter(models.Attraction.name_zh.in_(ubud_attrs)).all()
                for n in [a.name_zh]}

    other_attrs = {
        "京打玛尼火山": None, "圣泉寺": None, "海神庙": None,
        "金巴兰海滩": None, "乌鲁瓦图断崖": None, "蓝梦岛一日游": None,
    }
    for name in list(other_attrs):
        a = db.query(models.Attraction).filter_by(name_zh=name).first()
        if a:
            other_attrs[name] = a.id

    hotels = {h.name_zh: h.id for h in db.query(models.Hotel).all()}

    # 形如 (from_type, from_name, to_type, to_name, normal, peak, holiday, km, vehicle_max_seat, vehicle_warn_seat)
    # vehicle_max_seat=None 无限制; e.g. 25 表示 35 座不可走
    pairs = [
        # 乌布内部 (狭窄街道, 大车不进)
        ("attraction", "圣猴森林", "attraction", "乌布皇宫", 8, 15, 18, 1.5, 17, 7),
        ("attraction", "圣猴森林", "attraction", "乌布市场", 6, 12, 15, 1.0, 17, 7),
        ("attraction", "乌布皇宫", "attraction", "乌布市场", 3, 6, 8, 0.3, 17, 7),
        ("attraction", "乌布市场", "attraction", "德格拉朗梯田", 25, 35, 45, 12, 25, 17),
        ("attraction", "圣猴森林", "attraction", "德格拉朗梯田", 30, 40, 50, 13, 25, 17),
        # 山路 (35 座大车不能走)
        ("attraction", "德格拉朗梯田", "attraction", "京打玛尼火山", 60, 80, 95, 35, 25, 17),
        ("attraction", "乌布皇宫", "attraction", "京打玛尼火山", 90, 120, 135, 50, 25, 17),
        ("attraction", "京打玛尼火山", "attraction", "圣泉寺", 45, 60, 70, 25, 25, 17),
        ("attraction", "圣泉寺", "attraction", "德格拉朗梯田", 25, 35, 45, 12, 25, 17),
        # 跨南北 (主路, 大车 OK 但远)
        ("attraction", "京打玛尼火山", "attraction", "金巴兰海滩", 135, 175, 200, 75, None, 25),
        ("attraction", "乌布皇宫", "attraction", "金巴兰海滩", 75, 105, 120, 40, 25, 17),
        ("attraction", "乌布皇宫", "attraction", "海神庙", 75, 100, 115, 38, None, 25),
        ("attraction", "金巴兰海滩", "attraction", "乌鲁瓦图断崖", 25, 40, 50, 15, None, None),
        ("attraction", "海神庙", "attraction", "金巴兰海滩", 60, 85, 100, 35, None, 25),
        # 蓝梦岛 (含船)
        ("attraction", "金巴兰海滩", "attraction", "蓝梦岛一日游", 90, 120, 140, 0, None, None),
        # 酒店相关
        ("hotel", "巴厘岛 The Mulia", "attraction", "圣猴森林", 70, 100, 115, 35, 25, 17),
        ("hotel", "巴厘岛 The Mulia", "attraction", "金巴兰海滩", 15, 25, 30, 8, None, None),
        ("hotel", "巴厘岛 The Mulia", "attraction", "海神庙", 75, 105, 120, 40, None, 25),
        ("hotel", "丽思卡尔顿巴厘岛", "attraction", "金巴兰海滩", 20, 30, 40, 10, None, None),
        ("hotel", "乌布四季度假村", "attraction", "圣猴森林", 25, 40, 50, 12, 17, 7),
        ("hotel", "乌布四季度假村", "attraction", "德格拉朗梯田", 35, 50, 60, 18, 25, 17),
        ("hotel", "库塔风情酒店", "attraction", "金巴兰海滩", 25, 40, 50, 12, None, None),
        ("hotel", "库塔风情酒店", "attraction", "圣猴森林", 75, 100, 115, 40, 25, 17),
    ]

    for ft, fn, tt, tn, nm, pm, hm, km, vmax, vwarn in pairs:
        from_id = ubud_ids.get(fn) or other_attrs.get(fn) or hotels.get(fn)
        to_id = ubud_ids.get(tn) or other_attrs.get(tn) or hotels.get(tn)
        if from_id is None or to_id is None:
            continue
        for a_t, a_id, b_t, b_id in [(ft, from_id, tt, to_id), (tt, to_id, ft, from_id)]:
            existing = db.query(models.Distance).filter_by(
                from_type=a_t, from_id=a_id, to_type=b_t, to_id=b_id,
            ).first()
            if existing:
                continue
            db.add(models.Distance(
                from_type=a_t, from_id=a_id, to_type=b_t, to_id=b_id,
                distance_km=km, normal_minutes=nm, peak_minutes=pm, holiday_minutes=hm,
                vehicle_max_seat=vmax, vehicle_warn_seat=vwarn,
                source="seed",
            ))


def _seed_gamble_strategies(db: Session) -> None:
    """v0.5.2 业务规则升级版 — 基于用户实际经营经验:

    铁律: 主结构有自由活动 → 必须赌 (额度可以小)
    维度: 酒店级别 / 已含水上数 / 自由日含餐 / 儿童占比 / 老年(55+)占比

    幂等: 按 name 补缺, 不覆盖已有 (用户改过 priority/金额会保留)
    """
    existing_names = {n for (n,) in db.query(models.GambleStrategy.name).all()}
    strategies = [
        # ===== 1) 完全无自由活动 → 唯一可"不赌"的场景 =====
        {
            "name": "无任何自由活动 → 不赌",
            "description": "客人全程跟团, 没空买自费. 这是唯一可以完全 skip 的场景",
            "conditions": [{"type": "has_any_free_activity", "value": False}],
            "action": "skip", "gamble_cny": 0, "extra_profit_cny": 0, "priority": 100,
        },
        # ===== 2) MICE/婚礼短行程 → 不赌, 反而加价 ¥100/人 =====
        {
            "name": "MICE/婚礼短行程 → 不赌+加 ¥100/人",
            "description": "MICE/婚礼客户主活动满档, 自费成功率低; 反向多赚",
            "conditions": [
                {"type": "customer_type_in", "value": ["mice", "wedding"]},
                {"type": "total_days_lt", "value": 5},
            ],
            "action": "skip", "gamble_cny": 0, "extra_profit_cny": 100, "priority": 95,
        },
        # ===== 3) 老年人 55+ 占比超半 → 不赌+加价 =====
        {
            "name": "老年(55+)≥50% → 不赌+加 ¥80/人",
            "description": "老年客群对自费排斥强; 不让利反而加价",
            "conditions": [{"type": "senior_ratio_gt", "value": 0.5}],
            "action": "skip", "gamble_cny": 0, "extra_profit_cny": 80, "priority": 90,
        },
        # ===== 4) 5 星酒店 + 蜜月 → 少赌 (¥150/人) =====
        {
            "name": "5星酒店+蜜月 → 少赌 ¥150/人",
            "description": "高端蜜月客对自费敏感, 少让利保品质感",
            "conditions": [
                {"type": "hotel_max_star_gte", "value": 5},
                {"type": "customer_type_in", "value": ["honeymoon"]},
            ],
            "action": "fixed", "gamble_cny": 150, "extra_profit_cny": 0, "priority": 85,
        },
        # ===== 5) 5 星酒店全团 → 少赌 (¥100/人, 无论客户类型) =====
        {
            "name": "5星酒店全团 → 少赌 ¥100/人",
            "description": "高端客群, 自费购买率低, 少让利",
            "conditions": [{"type": "hotel_max_star_gte", "value": 5}],
            "action": "fixed", "gamble_cny": 100, "extra_profit_cny": 0, "priority": 80,
        },
        # ===== 6) 已含水上 ≥ 2 项 → 少赌 (¥80/人) =====
        {
            "name": "已含水上 ≥2 项 → 少赌 ¥80/人",
            "description": "水上自费空间被占, 让利意义有限",
            "conditions": [{"type": "water_count_gte", "value": 2}],
            "action": "fixed", "gamble_cny": 80, "extra_profit_cny": 0, "priority": 75,
        },
        # ===== 7) 全程含餐 + 含 SPA + 自由日含餐 → 不让利 =====
        {
            "name": "餐+SPA+自由日含餐 → 少赌 ¥50/人",
            "description": "餐和 SPA 升级空间被占, 仅留象征性让利",
            "conditions": [
                {"type": "all_meals_included", "value": True},
                {"type": "spa_already_booked", "value": True},
                {"type": "free_days_with_meals", "value": True},
            ],
            "action": "fixed", "gamble_cny": 50, "extra_profit_cny": 0, "priority": 70,
        },
        # ===== 8) 儿童占比 > 50% → 少赌 (¥100/人) =====
        {
            "name": "儿童占比>50% → 少赌 ¥100/人",
            "description": "亲子团儿童多, 自费购买决策偏保守",
            "conditions": [{"type": "child_ratio_gt", "value": 0.5}],
            "action": "fixed", "gamble_cny": 100, "extra_profit_cny": 0, "priority": 65,
        },
        # ===== 9) 蜜月/婚礼 + 旺季 + 多自由 → 大赌 (¥450/人) =====
        {
            "name": "蜜月/婚礼+旺季+多自由 → 让 ¥450/人",
            "description": "蜜月旺季客单价高且自费转化强, 大让利抢单",
            "conditions": [
                {"type": "customer_type_in", "value": ["honeymoon", "wedding"]},
                {"type": "free_hours_gt", "value": 12},
                {"type": "season_in", "value": ["high"]},
            ],
            "action": "fixed", "gamble_cny": 450, "extra_profit_cny": 0, "priority": 60,
        },
        # ===== 10) 年轻人 + 多自由 → 让 ¥350/人 =====
        {
            "name": "年轻人+多自由 → 让 ¥350/人",
            "description": "网红打卡 + 水上 + 餐升级转化率高",
            "conditions": [
                {"type": "customer_type_in", "value": ["young"]},
                {"type": "free_hours_gt", "value": 10},
            ],
            "action": "fixed", "gamble_cny": 350, "extra_profit_cny": 0, "priority": 50,
        },
        # ===== 11) 亲子 + 自由时间适中 → 让 ¥250/人 =====
        {
            "name": "亲子+自由时间 6~14h → 让 ¥250/人",
            "description": "亲子团儿童包+海豚日出 等自费转化率不错",
            "conditions": [
                {"type": "customer_type_in", "value": ["family_kids"]},
                {"type": "free_hours_gt", "value": 6},
                {"type": "free_hours_lt", "value": 14},
            ],
            "action": "fixed", "gamble_cny": 250, "extra_profit_cny": 0, "priority": 45,
        },
        # ===== 12) 兜底: 有自由活动但前面都没命中 → 让 ¥200/人 =====
        {
            "name": "兜底 — 有自由活动 → 让 ¥200/人",
            "description": "主结构铁律: 有自由就要赌, 默认让 ¥200/人",
            "conditions": [{"type": "has_any_free_activity", "value": True}],
            "action": "fixed", "gamble_cny": 200, "extra_profit_cny": 0, "priority": 1,
        },
    ]
    added = 0
    for s in strategies:
        if s["name"] in existing_names:
            continue
        db.add(models.GambleStrategy(
            name=s["name"],
            description=s["description"],
            conditions=json.dumps(s["conditions"], ensure_ascii=False),
            action=s["action"],
            gamble_cny=Decimal(str(s["gamble_cny"])),
            extra_profit_cny=Decimal(str(s.get("extra_profit_cny", 0))),
            priority=s["priority"],
            active=s.get("active", True),
            created_by="seed",
        ))
        added += 1
    if added:
        print(f"  · gamble_strategies: 补 {added} 条")


def _seed_templates(db: Session, dests: dict) -> None:
    if db.query(models.DayTripTemplate).count() > 0:
        return
    # 乌布文化一日游
    ubud_attrs_names = ["圣猴森林", "德格拉朗梯田", "乌布皇宫", "乌布市场"]
    attr_ids = {a.name_zh: a.id for a in db.query(models.Attraction).filter(models.Attraction.name_zh.in_(ubud_attrs_names)).all()}
    rest_id = db.query(models.Restaurant).filter_by(name_zh="脏鸭餐厅").first()

    t = models.DayTripTemplate(
        destination_id=dests["DPS"].id,
        name_zh="乌布文化一日游",
        name_en="Ubud Cultural Day Trip",
        description="圣猴森林 → 德格拉朗梯田 → 脏鸭午餐 → 乌布皇宫 → 乌布市场",
        total_minutes_estimate=480,
        recommended_pax_min=2, recommended_pax_max=17,
        difficulty="easy",
    )
    db.add(t)
    db.flush()
    for i, n in enumerate(ubud_attrs_names, start=1):
        if n in attr_ids:
            db.add(models.TemplateAttraction(template_id=t.id, attraction_id=attr_ids[n], order_index=i))
    if rest_id:
        db.add(models.TemplateRestaurant(template_id=t.id, restaurant_id=rest_id.id, meal_type="lunch"))

    # 京打玛尼火山日出团
    other_names = ["京打玛尼火山", "圣泉寺", "德格拉朗梯田"]
    other_ids = {a.name_zh: a.id for a in db.query(models.Attraction).filter(models.Attraction.name_zh.in_(other_names)).all()}
    t2 = models.DayTripTemplate(
        destination_id=dests["DPS"].id,
        name_zh="京打玛尼火山日出团",
        name_en="Mount Batur Sunrise",
        description="凌晨出发 → 京打玛尼日出 → 圣泉寺 → 德格拉朗梯田",
        total_minutes_estimate=600,
        difficulty="intense",
    )
    db.add(t2)
    db.flush()
    for i, n in enumerate(other_names, start=1):
        if n in other_ids:
            db.add(models.TemplateAttraction(template_id=t2.id, attraction_id=other_ids[n], order_index=i))


def _seed_area_rules(db: Session) -> None:
    """默认极限/不合理行程区域规则.可在 UI 增删改."""
    if db.query(models.AreaRule).count() > 0:
        return
    rules = [
        # 跨岛距离过远 — error
        {"hotel_area": "努沙杜瓦", "excluded_attraction_area": "罗威纳",
         "severity": "error",
         "message": "努沙杜瓦 → 罗威纳单程约 4 小时,当日往返不可行,需中转住一晚"},
        {"hotel_area": "库塔",     "excluded_attraction_area": "罗威纳",
         "severity": "error",
         "message": "库塔 → 罗威纳单程 3.5 小时,不建议当日往返"},
        {"hotel_area": "金巴兰",   "excluded_attraction_area": "罗威纳",
         "severity": "error",
         "message": "金巴兰 → 罗威纳单程 4 小时,不建议当日往返"},
        # 山区 + 南海岸不合理组合 — error
        {"hotel_area": "百度库",   "excluded_attraction_area": "乌鲁瓦图",
         "severity": "error",
         "message": "百度库山区 → 乌鲁瓦图单程 2.5 小时,加上崖顶日落需傍晚返程,深夜抵达高山危险"},
        # 乌布上山 + 海边 — warning
        {"hotel_area": "乌布",     "excluded_attraction_area": "乌鲁瓦图",
         "severity": "warning",
         "message": "乌布 → 乌鲁瓦图单程 90+ 分钟,当日往返时间紧张,建议改南部酒店"},
        {"hotel_area": "乌布",     "excluded_attraction_area": "罗威纳",
         "severity": "warning",
         "message": "乌布 → 罗威纳单程 2.5 小时,北线一日游较累"},
        # 苍古/水明漾 → 北部 — warning
        {"hotel_area": "苍古",     "excluded_attraction_area": "罗威纳",
         "severity": "warning",
         "message": "苍古 → 罗威纳单程 3 小时,海豚行程需 4:30 起床"},
        {"hotel_area": "水明漾",   "excluded_attraction_area": "罗威纳",
         "severity": "warning",
         "message": "水明漾 → 罗威纳单程 3 小时,海豚行程需早起"},
        # 沙努尔 → 西部国家公园 — warning
        {"hotel_area": "沙努尔",   "excluded_attraction_area": "门吉里岛",
         "severity": "warning",
         "message": "沙努尔 → 西部国家公园单程 3+ 小时,建议中转图阿曼住一晚"},
    ]
    for r in rules:
        db.add(models.AreaRule(
            hotel_area=r["hotel_area"],
            excluded_attraction_area=r["excluded_attraction_area"],
            severity=r["severity"],
            message=r["message"],
            active=True,
            created_by="seed",
        ))


def _seed_attraction_conflicts(db: Session) -> None:
    """默认景点互斥规则 — 通过 substring 匹配景点中文名找到 ID."""
    if db.query(models.AttractionConflictRule).count() > 0:
        return
    # 名字 substring 匹配 → ID
    def _find(kw: str) -> int | None:
        a = db.query(models.Attraction).filter(models.Attraction.name_zh.like(f"%{kw}%")).first()
        return a.id if a else None
    pairs = [
        # (kw_a, kw_b, severity, message)
        ("罗威纳",  "乌鲁瓦图", "error",   "罗威纳海豚需凌晨 5:00 出发,乌鲁瓦图日落需傍晚返,同日不可行"),
        ("罗威纳",  "情人崖",   "error",   "同上(乌鲁瓦图情人崖时间冲突)"),
        ("追海豚",  "GWK",     "error",   "海豚 5:00 + GWK 神鹰广场需傍晚,行程不合理"),
        ("圣猴森林","梯田",     "warning", "圣猴森林+梯田同区域,可加但日程紧"),
        ("水神庙",  "情人崖",   "warning", "水神庙在中部,情人崖在南部,跨区单程 2h+"),
    ]
    added = 0
    for kw_a, kw_b, sev, msg in pairs:
        a = _find(kw_a)
        b = _find(kw_b)
        if a and b and a != b:
            lo, hi = sorted([a, b])
            # 避免重复
            exists = db.query(models.AttractionConflictRule).filter_by(attraction_a_id=lo, attraction_b_id=hi).first()
            if exists:
                continue
            db.add(models.AttractionConflictRule(
                attraction_a_id=lo,
                attraction_b_id=hi,
                severity=sev,
                message=msg,
                active=True,
                created_by="seed",
            ))
            added += 1


def seed_all() -> None:
    init_db()
    with session_scope() as db:
        dests = _ensure_destinations(db)
        _seed_settings(db)
        _seed_hotels(db, dests)
        _seed_attractions(db, dests)
        _seed_restaurants(db, dests)
        _seed_vehicles(db, dests)
        _seed_guides(db, dests)
        _seed_simple(db, dests)
        _seed_optional_tours(db, dests)
        db.flush()
        _seed_distances(db)
        _seed_templates(db, dests)
        # v0.5.3: 不再 seed NoGambleRule (legacy); GambleStrategy 完全覆盖
        _seed_gamble_strategies(db)  # v0.3 主表 (idempotent: 按 name 补缺)
        _seed_area_rules(db)
        _seed_attraction_conflicts(db)
    print("✅ 样本数据已写入")


if __name__ == "__main__":
    seed_all()
