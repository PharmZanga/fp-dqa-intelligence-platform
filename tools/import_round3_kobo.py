import argparse
import json
import math
import re
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd


COMMODITIES = [
    {
        "name": "Implanon",
        "slug": "implanon",
        "prefix": "Implanon",
        "available_col": "Was this commodity available at the facility on the day of the assessment?",
        "scc_uom": "Implanon: Numeric Unit of Dispensing on SCC",
        "elmis_uom": "Implanon: Numeric Unit of Dispensing in eLMIS",
    },
    {
        "name": "Jadelle",
        "slug": "jadelle",
        "prefix": "Jadelle",
        "available_col": "Was this commodity available at the facility on the day of the assessment?.1",
        "scc_uom": "Jadelle: Numeric Unit of Dispensing on SCC",
        "elmis_uom": "Jadelle: Numeric Unit of Dispensing in eLMIS",
    },
    {
        "name": "DMPA-SC",
        "slug": "dmpa_sc",
        "prefix": "DMPA-SC (Sayana Press)",
        "available_col": "Was this commodity available at the facility on the day of the assessment?.2",
        "scc_uom": None,
        "elmis_uom": "DMPA-SC (Sayana Press): Numeric Unit of Dispensing in eLMIS",
    },
    {
        "name": "DMPA-IM",
        "slug": "dmpa_im",
        "prefix": "DMPA-IM (Depo-Provera)",
        "available_col": "Was this commodity available at the facility on the day of the assessment?.3",
        "scc_uom": "DMPA-IM (Depo-Provera): Numeric Unit of Dispensing on SCC",
        "elmis_uom": "DMPA-IM (Depo-Provera): Numeric Unit of Dispensing in eLMIS",
    },
    {
        "name": "COCs",
        "slug": "cocs",
        "prefix": "Combined Oral Contraceptives (COCs)",
        "available_col": "Was this commodity available at the facility on the day of the assessment?.4",
        "scc_uom": "Combined Oral Contraceptives (COCs): Numeric Unit of Dispensing on SCC",
        "elmis_uom": "Combined Oral Contraceptives (COCs): Numeric Unit of Dispensing in eLMIS",
    },
    {
        "name": "IUCD",
        "slug": "iucd",
        "prefix": "Copper T / IUCD",
        "available_col": "Was this commodity available at the facility on the day of the assessment?.5",
        "scc_uom": "Copper T / IUCD: Numeric Unit of Dispensing on SCC",
        "elmis_uom": "Copper T / IUCD: Numeric Unit of Dispensing in eLMIS",
    },
]

MONTHS = [
    ("January", "jan"),
    ("February", "feb"),
    ("March", "mar"),
]


def clean_value(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if pd.isna(value):
        return None
    if isinstance(value, str):
        value = value.strip()
        return value if value else None
    return value


def as_number(value, default=0):
    value = clean_value(value)
    if value is None:
        return default
    try:
        return int(value) if float(value).is_integer() else float(value)
    except (TypeError, ValueError):
        return default


def as_bool(value):
    value = clean_value(value)
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"yes", "y", "true", "1", "available", "functional"}


def norm(text):
    text = str(text or "").lower()
    text = text.replace("&", "and")
    text = re.sub(r"\b(urban|rural|health|centre|center|clinic|hospital|post|mini|level|mission|hahc|rhc|uhc|hp|hc|rhp|zns|day|sec|school)\b", "", text)
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def canonical_district(value):
    text = str(clean_value(value) or "").strip()
    fixes = {
        "shiwangandu": "Shiwang'andu",
        "shiwang'andu": "Shiwang'andu",
        "kapiri": "Kapiri Mposhi",
    }
    return fixes.get(text.lower(), text)


def canonical_facility_name(row):
    listed = clean_value(row.get("Facility name"))
    other = clean_value(row.get("Please type the facility name if it is not listed above"))
    if other and (not listed or "not among" in str(listed).lower()):
        return str(other).strip()
    return str(listed or other or "").strip()


def best_target_name(province, district, facility, targets):
    facility_text = str(facility or "").lower()
    if province == "Western" and district == "Luampa" and "luampa mission" in facility_text:
        return "Luampa 1st Level Hospital"
    if province == "Lusaka" and district == "Luangwa" and "luangwa boma" in facility_text:
        return "Boma Rural Health Center (Luangwa)"
    if province == "Central" and district == "Chibombo" and "chikobo" in facility_text:
        return "Chibombo RHC"
    if province == "Central" and district == "Kapiri Mposhi" and "kapiri mposhi urban" in facility_text:
        return "Kapiri Urban Health Centre"
    candidates = [
        t["facility"]
        for t in targets
        if t.get("province") == province and canonical_district(t.get("district")) == district
    ]
    if not candidates:
        return facility
    nf = norm(facility)
    if not nf:
        return facility
    best = None
    best_score = 0
    for candidate in candidates:
        nc = norm(candidate)
        if not nc:
            continue
        contains = (len(nf) >= 7 and nf in nc) or (len(nc) >= 7 and nc in nf)
        score = 1.0 if nf == nc else SequenceMatcher(None, nf, nc).ratio()
        if contains:
            score = max(score, 0.93 + min(len(nc), 20) / 1000)
        if score > best_score:
            best = candidate
            best_score = score
    return best if best and best_score >= 0.86 else facility


def date_string(value):
    value = clean_value(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.strftime("%Y-%m-%d")


def month_values(row, commodity, month_name, month_slug):
    prefix = commodity["prefix"]
    slug = commodity["slug"]
    scc = as_number(row.get(f"{prefix}: {month_name} SCC Issues"))
    elmis = as_number(row.get(f"{prefix}: {month_name} eLMIS Issues"))
    fp_register = as_number(row.get(f"{prefix}: {month_name} FP Register Clients"))
    dhis2 = as_number(row.get(f"{prefix}: {month_name} DHIS2 Clients"))
    physical = as_number(row.get(f"{prefix}: Actual Physical Count of Commodity")) if month_name == "March" else 0
    elmis_stock = as_number(row.get(f"{prefix}: Stock in eLMIS")) if month_name == "March" else 0
    return {
        "orderQuantity": as_number(row.get(f"{prefix}: {month_name} Order Quantity")),
        "physicalCount": physical,
        "elmisStock": elmis_stock,
        "physicalVsElmisDiscrepancy": as_number(row.get(f"{slug}_scc_vs_physical_count_discrepancy")) if month_name == "March" else 0,
        "monthlyConsumptionScc": scc,
        "monthlyConsumptionElmis": elmis,
        "consumptionDiscrepancy": as_number(row.get(f"{slug}_{month_slug}_issues_discrepancy"), scc - elmis),
        "quantityReceived": 0,
        "numberOfPatientsDhis2": dhis2,
        "numberOfPatientsFpRegister": fp_register,
        "patientRegisterDiscrepancy": as_number(row.get(f"{slug}_{month_slug}_fp_register_dhis2_discrepancy"), fp_register - dhis2),
    }


def uom_alignment(scc_uom, elmis_uom, physical_uom):
    values = [clean_value(scc_uom), clean_value(elmis_uom), clean_value(physical_uom)]
    recorded = [str(v).strip().lower() for v in values if v is not None]
    if len(recorded) < 3:
        return "Not recorded"
    return "Aligned" if len(set(recorded)) == 1 else "Mismatch"


def commodity_record(row, commodity):
    prefix = commodity["prefix"]
    slug = commodity["slug"]
    scc_uom = clean_value(row.get(commodity["scc_uom"])) if commodity.get("scc_uom") else None
    elmis_uom = clean_value(row.get(commodity["elmis_uom"])) if commodity.get("elmis_uom") else None
    physical_uom = scc_uom
    months = {month: month_values(row, commodity, month, month_slug) for month, month_slug in MONTHS}
    pharmacy_stockout = as_bool(row.get(f"{prefix}: Was the commodity stocked out in the pharmacy storeroom during Jan–Mar 2026?"))
    dispensing_stockout = as_bool(row.get(f"{prefix}: Was the commodity stocked out at facility level across all dispensing points during Jan–Mar 2026?"))
    return {
        "product": commodity["name"],
        "months": months,
        "availableOnAssessment": as_bool(row.get(commodity["available_col"])),
        "pharmacyStockout": pharmacy_stockout,
        "dispensingPointStockout": dispensing_stockout,
        "receivedFromZammsa": as_bool(row.get(f"{prefix}: Did the facility receive this commodity from ZAMMSA within the 3 months (Jan–Mar 2026)?"))
        or as_bool(row.get(f"{prefix}: Did the facility receive this commodity from ZAMMSA within the 3 mo..."))
        or as_bool(row.get(f"{prefix}: Did the facility receive this commodity ...")),
        "zammsaQuantityReceived": as_number(row.get(f"{prefix}: Quantity received from ZAMMSA within the 3 months"))
        or as_number(row.get(f"{prefix}: Quantity received from ZAMMSA within the...")),
        "receivedFromDho": as_bool(row.get(f"{slug.capitalize()}: Did the facility receive this commodity from the District Health Office (DHO) within the 3 months?"))
        or as_bool(row.get(f"{prefix}: Did the facility receive this commodity from the District Health Office (DHO) within the 3 months?")),
        "dhoQuantityReceived": as_number(row.get(f"{slug.capitalize()}: Quantity received during the last DHO delivery"))
        or as_number(row.get(f"{prefix}: Quantity received during the last DHO delivery")),
        "uomAlignment": uom_alignment(scc_uom, elmis_uom, physical_uom),
        "sccUom": str(scc_uom) if scc_uom is not None else "Not recorded",
        "elmisUom": str(elmis_uom) if elmis_uom is not None else "Not recorded",
        "physicalUom": str(physical_uom) if physical_uom is not None else "Not recorded",
    }


def daily_commodity_summary(product):
    months = product["months"]
    scc_elmis = 1 if any(as_number(m["physicalVsElmisDiscrepancy"]) != 0 or as_number(m["consumptionDiscrepancy"]) != 0 for m in months.values()) else 0
    fp_dhis2 = 1 if any(as_number(m["patientRegisterDiscrepancy"]) != 0 for m in months.values()) else 0
    return {
        "pharmacyStockout": 1 if product["pharmacyStockout"] else 0,
        "facilityStockout": 1 if product["dispensingPointStockout"] else 0,
        "stockoutProduct": 1 if product["pharmacyStockout"] or product["dispensingPointStockout"] else 0,
        "sccElmisDiscrepancy": scc_elmis,
        "fpDhis2Discrepancy": fp_dhis2,
    }


def root_causes(row, products):
    causes = []
    for col in [
        "Key Root Causes Identified at Facility Level/UoM mismatch",
        "Key Root Causes Identified at Facility Level/Delayed eLMIS entry",
        "Key Root Causes Identified at Facility Level/Incomplete SCC",
        "Key Root Causes Identified at Facility Level/Stock card not updated",
        "Key Root Causes Identified at Facility Level/Poor documentation",
        "Key Root Causes Identified at Facility Level/Ordering errors",
        "Key Root Causes Identified at Facility Level/eLMIS access challenges",
        "Key Root Causes Identified at Facility Level/Staff knowledge gap",
        "Key Root Causes Identified at Facility Level/DHIS2 inconsistency",
        "Key Root Causes Identified at Facility Level/Other",
    ]:
        if as_bool(row.get(col)):
            causes.append(col.split("/", 1)[1])
    if not causes:
        if any(p["uomAlignment"] == "Mismatch" for p in products):
            causes.append("UoM mismatch")
        if any(any(as_number(m["patientRegisterDiscrepancy"]) != 0 for m in p["months"].values()) for p in products):
            causes.append("DHIS2 inconsistency")
        if any(p["pharmacyStockout"] or p["dispensingPointStockout"] for p in products):
            causes.append("Stockout")
    return causes


def build_records(workbook, targets_path):
    df = pd.read_excel(workbook)
    targets = json.loads(Path(targets_path).read_text(encoding="utf-8"))["facilities"]
    daily_records = []
    product_records = []
    for _, row in df.iterrows():
        province = str(clean_value(row.get("Province")) or "").strip()
        district = canonical_district(row.get("District"))
        facility_raw = canonical_facility_name(row)
        facility = best_target_name(province, district, facility_raw, targets)
        visit_date = date_string(row.get("Date of assessment"))
        products = [commodity_record(row, commodity) for commodity in COMMODITIES]
        summaries = {p["product"]: daily_commodity_summary(p) for p in products}
        daily_records.append(
            {
                "visitDate": visit_date,
                "province": province,
                "district": district,
                "facility": facility,
                "level": str(clean_value(row.get("Facility level")) or ""),
                "assessed": True,
                "elmisFunctional": as_bool(row.get("Does the facility have eLMIS Facility Edition?")),
                "sccAvailable": True,
                "stockCardUpdated": not any(c["sccElmisDiscrepancy"] for c in summaries.values()),
                "dhis2Discrepancy": sum(c["fpDhis2Discrepancy"] for c in summaries.values()),
                "pharmacyStockout": sum(c["pharmacyStockout"] for c in summaries.values()),
                "facilityStockout": sum(c["facilityStockout"] for c in summaries.values()),
                "dedicatedStoreroom": as_bool(row.get("Dedicated Pharmacy Storeroom")),
                "lockableDoors": as_bool(row.get("Lockable Doors")),
                "functionalAC": as_bool(row.get("Adequate Storage Space")),
                "productsOnShelves": as_bool(row.get("Products Stored on Shelves")),
                "productsOffGround": as_bool(row.get("Products Off the Ground")),
                "tempChartUpdated": as_bool(row.get("Temperature Chart Updated")),
                "functionalThermometer": as_bool(row.get("Functional Thermometer")),
                "fefoFollowed": as_bool(row.get("FEFO Followed")),
                "commodities": summaries,
                "rootCauses": root_causes(row, products),
                "remarks": str(clean_value(row.get("Overall Action Points and Recommendations")) or clean_value(row.get("Overall Recommendations")) or ""),
            }
        )
        product_records.append(
            {
                "visitDate": visit_date,
                "province": province,
                "district": district,
                "facility": facility,
                "products": products,
            }
        )
    return daily_records, product_records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workbook", required=True)
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()

    repo = Path(args.repo)
    daily_records, product_records = build_records(args.workbook, repo / "data" / "round3" / "target-facilities.json")
    dates = sorted({r["visitDate"] for r in daily_records if r["visitDate"]})
    latest_date = dates[-1] if dates else ""

    existing_daily_records = []
    daily_path = repo / "data" / "round3" / "daily" / "latest.json"
    if daily_path.exists():
        try:
            existing_daily_records = json.loads(daily_path.read_text(encoding="utf-8")).get("records", [])
        except json.JSONDecodeError:
            existing_daily_records = []
    existing_prior = [r for r in existing_daily_records if r.get("visitDate") and r.get("visitDate") != latest_date]
    latest_records = [r for r in daily_records if r.get("visitDate") == latest_date]

    daily_payload = {
        "date": latest_date,
        "source": f"SRMNH DQA Round 3 export {latest_date}",
        "records": existing_prior + latest_records,
    }
    daily_path.write_text(json.dumps(daily_payload, indent=2), encoding="utf-8")

    by_date = defaultdict(list)
    for record in product_records:
        by_date[record["visitDate"]].append(record)
    detail_dir = repo / "data" / "round3" / "product-detail"
    detail_dir.mkdir(parents=True, exist_ok=True)
    for visit_date, records in by_date.items():
        detail_path = detail_dir / f"{visit_date}.json"
        if visit_date != latest_date and detail_path.exists():
            continue
        payload = {
            "date": visit_date,
            "source": f"SRMNH DQA Round 3 export {latest_date}",
            "records": records,
        }
        detail_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"wrote {len(existing_prior) + len(latest_records)} daily records")
    for visit_date in dates:
        print(f"{visit_date}: {len(by_date[visit_date])} product-detail records")


if __name__ == "__main__":
    main()
