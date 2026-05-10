"""扫描剩余 sheet 的真实数据."""
import sys, openpyxl
sys.stdout.reconfigure(encoding="utf-8")

TARGETS = [
    (r"C:\Users\001\balijob\02_行程产品报价\BWS碎片化整理.xlsx", "高端下午茶"),
    (r"C:\Users\001\balijob\02_行程产品报价\BWS碎片化整理.xlsx", "疗愈+瑜伽"),
    (r"C:\Users\001\balijob\02_行程产品报价\BWS碎片化整理.xlsx", "巴厘岛酒店整理"),
    (r"C:\Users\001\balijob\02_行程产品报价\BWS碎片化整理.xlsx", "高端酒店"),
    (r"C:\Users\001\balijob\02_行程产品报价\BWS碎片化整理.xlsx", "巴厘岛车费"),
    (r"C:\Users\001\balijob\02_行程产品报价\BWS碎片化整理.xlsx", "泗水"),
    (r"C:\Users\001\balijob\02_行程产品报价\BWS碎片化整理.xlsx", "科莫多"),
    (r"C:\Users\001\balijob\02_行程产品报价\20260410巴厘岛项目成本2026年版本.xlsx", "泗水"),
    (r"C:\Users\001\balijob\02_行程产品报价\20260410巴厘岛项目成本2026年版本.xlsx", "科莫多"),
]

cache = {}
for path, sname in TARGETS:
    if path not in cache:
        cache[path] = openpyxl.load_workbook(path, data_only=True)
    ws = cache[path][sname]
    print(f"\n{'#' * 90}")
    print(f"FILE {path.rsplit(chr(92),1)[-1]}  Sheet: {sname}")

    # 找有效列宽(扫前 30 行)
    real_cols = 0
    for row in ws.iter_rows(values_only=True, max_row=30):
        for i, c in enumerate(row, 1):
            if c is not None:
                real_cols = max(real_cols, i)
    print(f"  rows={ws.max_row}  effective_cols={real_cols}")

    # 打印前 30 行
    for i, row in enumerate(ws.iter_rows(values_only=True, max_row=30), 1):
        row = row[:real_cols]
        if not any(c not in (None, "") for c in row):
            continue
        cells = [str(c)[:80] if c is not None else "" for c in row]
        print(f"  R{i:>3}: " + " | ".join(cells))
