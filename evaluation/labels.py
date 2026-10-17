
from pathlib import Path
from collections import Counter
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
EXCEL = ROOT / "data" / "open_labels.xlsx"

workbook = load_workbook(EXCEL, read_only=True, data_only=True)
sheet = workbook.active

records = []

for row in sheet.iter_rows(min_row=2, values_only=True):
    video, timestamp, label = row[:3]

    if not video:
        continue

    records.append({
        "video": str(video).strip(),
        "timestamp": timestamp,
        "label": str(label).strip().lower()
    })

print("Всего видео:", len(records))
print("Метки:", dict(Counter(r["label"] for r in records)))

workbook.close()
