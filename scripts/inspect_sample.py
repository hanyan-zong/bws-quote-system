"""读关键 sheet 的前 25 行 + 列宽精简."""
import sys, openpyxl
sys.stdout.reconfigure(encoding="utf-8")

TARGETS = [
    (r"C:\Users\001\balijob\02_行程产品报价\20260410巴厘岛项目成本2026年版本.xlsx", "巴厘岛项目门票"),
    (r"C:\Users\001\balijob\02_行程产品报价\20260410巴厘岛项目成本2026年版本.xlsx", "酒店"),
    (r"C:\Users\001\balijob\02_行程产品报价\20260410巴厘岛项目成本2026年版本.xlsx", "车费"),
    (r"C:\Users\001\balijob\02_行程产品报价\20260410巴厘岛项目成本2026年版本.xlsx", "导游小费+赌"),
    (r"C:\Users\001\balijob\02_行程产品报价\BWS碎片化整理.xlsx", "巴厘岛车费"),
    (r"C:\Users\001\balijob\02_行程产品报价\BWS碎片化整理.xlsx", "巴厘岛一日游"),
    (r"C:\Users\001\balijob\02_行程产品报价\BWS碎片化整理.xlsx", "巴厘岛酒店整理"),
    (r"C:\Users\001\balijob\02_行程产品报价\BWS碎片化整理.xlsx", "高端酒店"),
    (r"C:\Users\001\balijob\02_行程产品报价\BWS碎片化整理.xlsx", "高端下午茶"),
    (r"C:\Users\001\balijob\02_行程产品报价\BWS碎片化整理.xlsx", "疗愈+瑜伽"),
]


def load(path):
    return openpyxl.load_workbook(path, data_only=True)


seen = {}
for path, sname in TARGETS:
    if path not in seen:
        seen[path] = load(path)
    wb = seen[path]
    ws = wb[sname]
    print(f"\n{'#' * 90}")
    print(f"FILE {path.rsplit(chr(92), 1)[-1]}  Sheet: {sname}  rows={ws.max_row}")
    # 找有效列宽(去掉 16384 cols 假象)
    real_cols = 0
    for row in ws.iter_rows(values_only=True, max_row=3):
        for i, c in enumerate(row, 1):
            if c is not None:
                real_cols = max(real_cols, i)
    print(f"  effective cols={real_cols}")
    for i, row in enumerate(ws.iter_rows(values_only=True, max_row=25), 1):
        # 截断到 real_cols
        row = row[:real_cols]
        # 跳过全空行
        if not any(c not in (None, "") for c in row):
            continue
        cells = [str(c) if c is not None else "" for c in row]
        print(f"  R{i:>3}: " + " | ".join(cells))
