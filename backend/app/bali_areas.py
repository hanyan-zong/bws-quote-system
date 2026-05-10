"""巴厘岛标准区域字典 — AI 提取/手动归类时统一用这套中文名."""

# 按地理大区分组,前端可分组展示
BALI_AREAS_GROUPED = {
    "南部 · 海滩度假区": [
        "努沙杜瓦",   # Nusa Dua
        "贝洛阿",     # Benoa
        "金巴兰",     # Jimbaran
        "库塔",       # Kuta
        "勒吉安",     # Legian
        "水明漾",     # Seminyak
        "苍古",       # Canggu
        "乌鲁瓦图",   # Uluwatu
        "佩坎杜",     # Pecatu
    ],
    "中部 · 文化山林": [
        "乌布",        # Ubud
        "登巴萨",      # Denpasar
        "沙努尔",      # Sanur
        "塔巴南",      # Tabanan
    ],
    "中北 · 高山火山": [
        "百度库",      # Bedugul
        "金塔玛尼",    # Kintamani
        "巴杜尔",      # Mount Batur
    ],
    "东部 · 潜水文化": [
        "卡朗加森",    # Karangasem
        "阿曼德",      # Amed
        "图兰本",      # Tulamben
        "齐齐党",      # Tirta Gangga
    ],
    "北部 · 海豚温泉": [
        "罗威纳",      # Lovina
        "新加拉惹",    # Singaraja
    ],
    "西部 · 国家公园": [
        "尼加拉",      # Negara
        "门吉里岛",    # Menjangan
    ],
    "外岛": [
        "佩尼达岛",    # Nusa Penida
        "蓝梦岛",      # Nusa Lembongan
        "切宁安岛",    # Nusa Ceningan
        "吉利岛",      # Gili
        "龙目岛",      # Lombok
        "科莫多",      # Komodo
        "瑟帕岛",      # Sepa Island
    ],
}

# 扁平列表,用于校验和 AI prompt
BALI_AREAS = [a for group in BALI_AREAS_GROUPED.values() for a in group]
