"""Generate data/processing_log.csv: a fake log of documents the AI feature sent to vendors.

Change the numbers below and rerun to try different scenarios.
"""
import csv
import random
from datetime import datetime, timedelta

random.seed(7)

START = datetime(2026, 9, 21, 8, 0)   # NewAI switched on
DAYS = 14                             # two weeks of processing

# customer -> list of (country, number of people)
POPULATION = {
    "Hartmann Steuerberatung": [("de", 140)],
    "Thames Payroll Ltd": [("uk", 220), ("de", 35)],
    "Brightline CPA": [("us", 120)],
}

BASE_FIELDS = ["name", "work_email", "gross_pay", "net_pay"]
GERMAN_PAYSLIP_EXTRAS = ["church_tax", "sick_pay", "union_dues"]

rows = []
doc = 1000
for customer, groups in POPULATION.items():
    for country, people in groups:
        for p in range(people):
            fields = list(BASE_FIELDS)
            if country == "de" and random.random() < 0.6:
                fields += random.sample(GERMAN_PAYSLIP_EXTRAS, k=random.randint(1, 2))
            ts = START + timedelta(minutes=random.randint(0, DAYS * 24 * 60))
            doc += 1
            rows.append({
                "timestamp": ts.isoformat(timespec="minutes"),
                "customer": customer,
                "vendor": "NewAI",
                "document_id": f"DOC-{doc}",
                "person_id": f"{customer[:3].upper()}-{country.upper()}-{p:04d}",
                "person_country": country,
                "fields": ";".join(fields),
            })

rows.sort(key=lambda r: r["timestamp"])
with open("data/processing_log.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print(f"Wrote {len(rows)} rows to data/processing_log.csv")
