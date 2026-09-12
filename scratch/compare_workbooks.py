import openpyxl

file_curr = 'output/Total_Ledger.xlsx'
file_v1 = 'output/Total_Ledger_v1.xlsx'

print("=== Loading Total_Ledger_v1.xlsx (Before Python edit) ===")
wb_v1 = openpyxl.load_workbook(file_v1, data_only=False)
print("Sheets in v1:", wb_v1.sheetnames)
for sheetname in wb_v1.sheetnames:
    ws = wb_v1[sheetname]
    pivots = getattr(ws, '_pivots', [])
    drawings = getattr(ws, '_drawings', [])
    images = getattr(ws, '_images', [])
    print(f"Sheet '{sheetname}': pivots={len(pivots)}, drawings={len(drawings)}, images={len(images)}")

print("\n=== Loading Total_Ledger.xlsx (After Python edit) ===")
wb_curr = openpyxl.load_workbook(file_curr, data_only=False)
print("Sheets in curr:", wb_curr.sheetnames)
for sheetname in wb_curr.sheetnames:
    ws = wb_curr[sheetname]
    pivots = getattr(ws, '_pivots', [])
    drawings = getattr(ws, '_drawings', [])
    images = getattr(ws, '_images', [])
    print(f"Sheet '{sheetname}': pivots={len(pivots)}, drawings={len(drawings)}, images={len(images)}")

# Check Zip archive contents for slicers, charts, drawings, shapes
import zipfile

def inspect_zip(filename):
    print(f"\n--- Zip Inspection of {filename} ---")
    with zipfile.ZipFile(filename, 'r') as z:
        names = z.namelist()
        slicers = [n for n in names if 'slicer' in n.lower()]
        drawings = [n for n in names if 'drawing' in n.lower()]
        charts = [n for n in names if 'chart' in n.lower()]
        pivot_tables = [n for n in names if 'pivot' in n.lower()]
        controls = [n for n in names if 'control' in n.lower() or 'item' in n.lower()]
        print(f"Slicers xml count: {len(slicers)} -> {slicers}")
        print(f"Drawings xml count: {len(drawings)} -> {drawings}")
        print(f"Charts xml count: {len(charts)} -> {charts}")
        print(f"Pivot tables xml count: {len(pivot_tables)} -> {pivot_tables}")

inspect_zip(file_v1)
inspect_zip(file_curr)
