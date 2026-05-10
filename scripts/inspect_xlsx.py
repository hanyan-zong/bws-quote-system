"""临时:扫描两个源文件的 sheet/header 结构."""
import sys, openpyxl, json
sys.stdout.reconfigure(encoding="utf-8")

FILES = [
    r"C:\Users\001\balijob\02_行程产品报价\20260410巴厘岛项目成本2026年版本.xlsx",
    r"C:\Users\001\balijob\02_行程产品报价\BWS碎片化整理.xlsx",
]

for f in FILES:
    print("=" * 90)
    print("FILE:", f.rsplit("\\", 1)[-1])
    wb = openpyxl.load_workbook(f, data_only=True)
    for sname in wb.sheetnames:
        ws = wb[sname]
        print(f"\n-- Sheet: {sname}  rows={ws.max_row} cols={ws.max_column}")
        # 前 5 行
        for i, row in enumerate(ws.iter_rows(values_only=True, max_row=5), start=1):
            print(f"   row{i}: {row}")
