# DQA 4 — eLMIS DQA

Dashboard: `elmis-dqa.html`. The main platform sidebar links to it as DQA 4.
`index.html?round=round4#executive-dashboard` also opens this dashboard.

The round starts with no published assessments. Round 1–3 results are not reused
as eLMIS assessments. No target registry or completion percentage is assumed.

## Import assessment results

Export all required submissions from the eLMIS KoBo project as JSON, or XLSX
using **XML question names and XML choice values**, including repeat groups.
The importer requires Python and `openpyxl` for XLSX/form lookups.

```sh
python tools/import_elmis_kobo.py results.xlsx --form eLMIS_KoBo_Date_Fixed.xlsx
node tools/test_elmis_dqa.cjs
```

For JSON use `results.json` instead. Nested repeat groups must be present as
`issue_repeat` and `rh_repeat`; XLSX repeats use `_parent_index` / `_index`.
The matching XLSForm resolves province, district and facility choice codes.
Review and commit `data/round4/elmis.json`, then publish through the existing
GitHub Pages deployment. Raw exports remain local; do not commit them.
No credentials, KoBo token or automatic live synchronization are configured.

The importer publishes selected reporting fields only. It excludes photographs,
GPS, assessor names, named action owners and free-text narratives. Owner presence
is retained as a boolean. Publish only assessment records approved for the public
dashboard.

## Indicator definitions

- Filters select date/location scope, then the latest visit per facility. Status
  and text filters apply to that latest visit. Historical visits are not summed
  into current facility counts. Same-day ties use submission time, then ID.
- Access rate uses recorded Yes/No answers only. Utilization is separate.
- Utilization follows the form's 30-day operational definitions. Unavailable
  evidence is not classified as non-use.
- Staff totals use OJT visits with valid mentored/competent counts. Missing counts
  are not zeros. Counts are visit reports, not unique staff identifiers.
- Open issues include partial, escalated, pending and not resolved. Overdue means
  an open issue's deadline is before today's date in Africa/Lusaka.
- Stock-out rate excludes unanswered / Not verified responses. None is a verified
  no-stock-out response and must be selected alone. Multiple commodity selections
  count once per facility for the facility rate.
- Stock-match rates require confirmed usable-stock basis, recorded unit/cutoff
  and both numeric balances. Zero is a valid balance. Missing values are excluded
  separately from baseline and post-intervention denominators. Quantities across
  units/products are not summed. Sampling has no fixed upper limit.
