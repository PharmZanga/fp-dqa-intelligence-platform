"""Prepare DQA 4 public dashboard data from a KoBo JSON or XML-value XLSX export.

Only explicitly selected reporting fields are published. Names of assessors,
action owners, GPS, photographs and free-text narratives are not exported.
"""
import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path


def clean(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value).strip() if value is not None else ""


def field(record, name):
    if name in record:
        return record[name]
    return next((value for key, value in record.items() if key.split('/')[-1] == name), None)


def number(value):
    if value is None or clean(value) == "":
        return None
    try:
        result = float(value)
        return result if result >= 0 and result != float('inf') else None
    except (TypeError, ValueError):
        return None


def read_export(path):
    if path.suffix.lower() == '.json':
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        return data.get('results', []) if isinstance(data, dict) else data
    if path.suffix.lower() != '.xlsx':
        raise ValueError('Use a KoBo JSON export or XLSX export with XML field names and values.')
    from openpyxl import load_workbook
    workbook = load_workbook(path, read_only=True, data_only=True)
    sheets = {}
    for sheet in workbook:
        values = iter(sheet.values)
        headers = next(values, ())
        sheets[sheet.title] = [dict(zip(headers, row)) for row in values if any(v is not None for v in row)]
    main = next((rows for rows in sheets.values() if rows and any(str(k).split('/')[-1] == 'visit_date' for k in rows[0])), None)
    if main is None:
        raise ValueError('No assessment sheet with visit_date found. Export XML field names, not question labels.')
    by_index = {clean(row.get('_index')): row for row in main}
    for repeat in ['issue_repeat', 'rh_repeat']:
        sheet = next((rows for name, rows in sheets.items() if name.split('/')[-1] == repeat), [])
        for child in sheet:
            parent = by_index.get(clean(child.get('_parent_index')))
            if parent is None:
                raise ValueError(f'Cannot link {repeat} row to its parent assessment.')
            parent.setdefault(repeat, []).append(child)
    return main


def load_reference(path):
    from openpyxl import load_workbook
    workbook = load_workbook(path, read_only=True, data_only=True)
    rows = iter(workbook['choices'].values)
    headers = next(rows)
    mappings = {}
    for row in rows:
        item = dict(zip(headers, row))
        mappings.setdefault(item.get('list_name'), {})[clean(item.get('name'))] = clean(item.get('label'))
    return mappings


def normalize(rows, mappings):
    output = []
    for row in rows:
        get = lambda name: field(row, name)
        if not get('visit_date'):
            continue
        identity = get('_uuid') or get('_id')
        if not identity:
            raise ValueError('Each submission must include _uuid or _id.')
        province, district, facility = [clean(get(k)) for k in ['province', 'district', 'facility']]
        for list_name, value in [('province', province), ('district', district), ('facility', facility)]:
            if value not in mappings.get(list_name, {}):
                raise ValueError(f'Unknown {list_name} code {value!r}. Supply the matching XLSForm with --form.')
        stockouts = clean(get('rh_stockout_commodities')).split()
        for question, allowed_values in [('elmis_available', {'yes', 'no'}), ('util_status', {'active', 'limited', 'inactive', 'unavailable'}), ('ojt_done', {'yes', 'no'})]:
            value = clean(get(question))
            if value and value not in allowed_values:
                raise ValueError(f'{question} must use XML choice values, not choice labels.')
        allowed = set(mappings.get('rh_stockout', {}))
        if set(stockouts) - allowed:
            raise ValueError('Stock-out answers must use XML choice values, not choice labels.')
        if set(stockouts) & {'none', 'not_verified'} and len(stockouts) != 1:
            raise ValueError('None and Not verified must be selected alone.')
        issue_rows, stock_rows = get('issue_repeat') or [], get('rh_repeat') or []
        if not isinstance(issue_rows, list) or not isinstance(stock_rows, list):
            raise ValueError('Repeat groups must be included as arrays in the JSON export.')
        if number(get('issue_count')) and not issue_rows:
            raise ValueError('Issue count is nonzero but issue repeat records are missing.')
        if number(get('rh_count')) and clean(get('elmis_available')) == 'yes' and clean(get('util_status')) in ['active', 'limited'] and not stock_rows:
            raise ValueError('RH sample count is nonzero but commodity repeat records are missing.')
        record = {
            'id': clean(identity), 'submittedAt': clean(get('_submission_time')),
            'visitDate': clean(get('visit_date'))[:10], 'facilityId': facility,
            'province': mappings['province'][province], 'district': mappings['district'][district],
            'facility': mappings['facility'][facility], 'accessible': clean(get('elmis_available')),
            'utilization': clean(get('util_status')), 'ojtDone': clean(get('ojt_done')),
            'staffMentored': number(get('staff_mentored')), 'staffCompetent': number(get('staff_competent')),
            'stockouts': stockouts, 'issues': [], 'commodities': []
        }
        for issue in issue_rows:
            take = lambda key: field(issue, key)
            record['issues'].append({
                'category': clean(take('issue_category')), 'status': clean(take('issue_status')),
                'hasOwner': bool(clean(take('issue_owner'))), 'deadline': clean(take('deadline'))[:10],
                'followupOutcome': clean(take('issue_followup_outcome')) if clean(take('issue_followup_done')) == 'yes' else 'Not yet followed up'
            })
        for stock in stock_rows:
            take = lambda key: field(stock, key)
            record['commodities'].append({
                'commodity': clean(take('rh_commodity')), 'unit': clean(take('rh_unit')),
                'cutoff': clean(take('stock_cutoff')), 'basisConfirmed': clean(take('stock_basis_confirmed')),
                'physicalBefore': number(take('physical_before')), 'elmisBefore': number(take('elmis_before')),
                'physicalAfter': number(take('physical_after')), 'elmisAfter': number(take('elmis_after'))
            })
        output.append(record)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export', type=Path)
    parser.add_argument('--form', type=Path, required=True, help='Matching eLMIS XLSForm, used to resolve facility/location codes.')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'data/round4/elmis.json')
    args = parser.parse_args()
    records = normalize(read_export(args.export), load_reference(args.form))
    if not records:
        raise ValueError('No assessments found; refusing to overwrite results with an empty import.')
    if len({r['id'] for r in records}) != len(records):
        raise ValueError('Duplicate submission IDs found.')
    result = {'schemaVersion': 1, 'round': 'round4', 'title': 'eLMIS DQA', 'updatedAt': datetime.now(timezone.utc).isoformat(), 'records': records}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
    print(f'Prepared {len(records)} eLMIS assessment records: {args.output}')


if __name__ == '__main__':
    main()
