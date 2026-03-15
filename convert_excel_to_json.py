import pandas as pd
import json

# read excel
df = pd.read_excel("Lots Interpretation for AI.xlsx")

lots = []

for _, row in df.iterrows():
    lots.append({
        "id": f"lot_{int(row['Lot No.'])}",
        "lot_number": str(int(row["Lot No."])),
        "grade": str(row["上/ 下/ 中"]),
        "interpretation_en": str(row["Interpretation"]) if not pd.isna(row["Interpretation"]) else "",
        "interpretation_zh": str(row["解签"]) if not pd.isna(row["解签"]) else ""
    })

data = {
    "free_limit": 3,
    "payment_link": "https://your-payment-link-here.com",
    "system_style": "You are a warm and clear divination assistant. Use only the provided knowledge. Identify the lot number and original interpretation first, then elaborate naturally without changing the original meaning.",
    "divination_lots": lots
}

with open("knowledge.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("knowledge.json created successfully.")