#!/usr/bin/env python3
"""Collect SEC Company Facts for the 60+25 watchlists into static GitHub Pages JSON.

SEC facts are public and unauthenticated, but requests MUST identify a real contact
in SEC_USER_AGENT. The site is still deployable if SEC access is unavailable.
Financial metrics are estimates from standardized XBRL tags, not audited calculations.
"""
from __future__ import annotations
import datetime as dt
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
TZ = dt.timezone.utc
FORMS = {'10-Q', '10-K', '10-Q/A', '10-K/A', '20-F', '20-F/A', '40-F', '40-F/A', '6-K', '6-K/A'}
FLOW_TAGS = {
    'revenue': ['RevenueFromContractWithCustomerExcludingAssessedTax', 'RevenueFromContractWithCustomerIncludingAssessedTax', 'Revenues', 'SalesRevenueNet', 'SalesRevenueGoodsNet', 'SalesRevenueServicesNet', 'TotalRevenuesAndOtherIncome', 'Revenue', 'RevenueFromContractsWithCustomers'],
    'operatingIncome': ['OperatingIncomeLoss', 'ProfitLossFromOperatingActivities'],
    'netIncome': ['NetIncomeLoss', 'ProfitLoss', 'ProfitLossAttributableToOwnersOfParent'],
    'cfo': ['NetCashProvidedByUsedInOperatingActivities', 'CashFlowsFromUsedInOperatingActivities'],
    'capex': ['PaymentsToAcquirePropertyPlantAndEquipment', 'PaymentsToAcquireProductiveAssets', 'PurchaseOfPropertyPlantAndEquipment', 'PurchaseOfPropertyPlantAndEquipmentAndIntangibleAssets'],
    'taxExpense': ['IncomeTaxExpenseBenefit', 'IncomeTaxExpenseContinuingOperations', 'IncomeTaxExpenseContinuingOperations'],
    'pretaxIncome': ['IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest', 'IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments', 'ProfitLossBeforeTax'],
    'interestExpense': ['InterestExpense', 'InterestExpenseNonOperating', 'FinanceCosts'],
    'shares': ['WeightedAverageNumberOfDilutedSharesOutstanding', 'WeightedAverageNumberOfSharesOutstandingDiluted'],
    # Reported diluted EPS is a safer fall-back when diluted shares are not
    # present in SEC Company Facts (e.g. multi-class issuers).
    'epsDiluted': ['EarningsPerShareDiluted', 'DilutedEarningsLossPerShare', 'DilutedEarningsPerShare'],
}
INSTANT_TAGS = {
    'cash': ['CashAndCashEquivalentsAtCarryingValue', 'CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents', 'CashAndCashEquivalents'],
    'equity': ['StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest', 'Equity'],
    'assets': ['Assets'],
    'longDebt': ['LongTermDebtNoncurrent', 'LongTermDebtAndCapitalLeaseObligations', 'LongTermDebt', 'LongTermBorrowings'],
    'currentDebt': ['LongTermDebtCurrent', 'LongTermDebtAndCapitalLeaseObligationsCurrent', 'CurrentPortionOfLongTermDebt', 'CurrentPortionOfLongTermBorrowings'],
    'shortDebt': ['ShortTermBorrowings', 'ShortTermDebt', 'ShortTermLoansPayable'],
}
FINANCIAL_SCHEMA_VERSION = 2
FINANCIAL_TICKERS = {'AXP', 'BAC', 'PGR', 'CB', 'RLI', 'ALLY', 'COF', 'JEF', 'CBOE'}


def nowiso() -> str:
    return dt.datetime.now(TZ).isoformat(timespec='seconds').replace('+00:00', 'Z')


def parse_date(s: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def load_json(p: Path, default: dict | None = None) -> dict:
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return default or {}


def save_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n', encoding='utf-8')


def get_session(user_agent: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({'User-Agent': user_agent, 'Accept': 'application/json', 'Accept-Encoding': 'gzip, deflate'})
    return s


def request_json(s: requests.Session, url: str) -> dict:
    for attempt in range(3):
        try:
            res = s.get(url, timeout=24)
            res.raise_for_status()
            return res.json()
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError('Unreachable')


def fact_entries(facts: dict, tags: list[str], unit: str = 'USD') -> list[dict]:
    """Merge fallback concepts, preferring higher-priority tags, but without double counting."""
    seen: set[tuple] = set()
    merged = []
    for priority, tag in enumerate(tags):
        for ns in ('us-gaap', 'ifrs-full', 'dei'):
            concept = facts.get(ns, {}).get(tag, {})
            units = concept.get('units', {})
            keys = [unit] if unit in units else (["shares"] if unit == 'shares' and 'shares' in units else [])
            for key in keys:
                for item in units.get(key, []):
                    if item.get('form') not in FORMS:
                        continue
                    end, filed = parse_date(item.get('end')), parse_date(item.get('filed'))
                    if not end or not filed or not isinstance(item.get('val'), (int, float)):
                        continue
                    delay = (filed-end).days
                    # Comparative annual facts should not overwrite direct contemporary reports.
                    if delay < 0 or delay > 265:
                        continue
                    try:
                        fy = int(item['fy'])
                    except (KeyError, ValueError, TypeError):
                        continue
                    fp = item.get('fp', '')
                    if fp not in ('Q1', 'Q2', 'Q3', 'FY'):
                        continue
                    start = parse_date(item.get('start'))
                    days = (end-start).days+1 if start else None
                    identity = (fy, fp, str(end), days)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    merged.append(dict(fy=fy, fp=fp, end=str(end), start=str(start) if start else None, days=days, val=float(item['val']), priority=priority, delay=delay, filed=str(filed), tag=tag))
    return merged


def preferred(candidates: list[dict]) -> dict | None:
    if not candidates:
        return None
    return min(candidates, key=lambda r: (r['priority'], r['delay'], r['filed']))


def quarter_flows(items: list[dict]) -> dict[tuple[int, int], tuple[str, float]]:
    """Extract three-month facts, and derive standalone quarters from YTD filings.

    Returns (fiscal_year, fiscal_quarter) -> (quarter_end, amount). Q4 is derived
    from FY less 9-month YTD, or FY less three individually reported quarters.
    """
    groups: dict[int, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in items:
        if r['days'] is None:
            continue
        groups[r['fy']][r['fp']].append(r)
    result = {}
    for fy, terms in groups.items():
        byterm = {}
        for term in ('Q1', 'Q2', 'Q3', 'FY'):
            opts = terms.get(term, [])
            direct = preferred([v for v in opts if 60 <= v['days'] <= 127])
            ytd_len = {'Q1': (60, 127), 'Q2': (155, 245), 'Q3': (245, 332), 'FY': (331, 401)}[term]
            ytd = preferred([v for v in opts if ytd_len[0] <= v['days'] <= ytd_len[1]])
            if direct or ytd:
                byterm[term] = (direct, ytd)
        qvals = {}
        for q in (1, 2, 3):
            term = f'Q{q}'
            direct, ytd = byterm.get(term, (None, None))
            record = direct or ytd
            if direct:
                val = direct['val']
            elif ytd and q == 1:
                val = ytd['val']
            elif ytd:
                prev = byterm.get(f'Q{q-1}', (None, None))[1]
                val = (ytd['val']-prev['val']) if prev else None
            else:
                val = None
            if val is not None and record:
                qvals[q] = (record['end'], val)
                result[(fy, q)] = (*qvals[q], (direct or ytd)['filed'])
        annual = byterm.get('FY', (None, None))[1]
        if annual:
            nine = byterm.get('Q3', (None, None))[1]
            if nine:
                val = annual['val']-nine['val']
            elif all(q in qvals for q in (1, 2, 3)):
                val = annual['val']-sum(qvals[q][1] for q in (1, 2, 3))
            else:
                val = None
            if val is not None:
                result[(fy, 4)] = (annual['end'], val, annual['filed'])
    return result


def quarter_shares(items: list[dict]) -> dict[tuple[int, int], tuple[str, float, str]]:
    """Quarterly weighted-average diluted shares are averages, NOT additive flows.

    Convert cumulative shares to discrete-quarter averages with day weighting;
    do not derive Q4 by subtracting averages as if they were earnings.
    """
    groups: dict[int, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for item in items:
        if item['days'] is not None:
            groups[item['fy']][item['fp']].append(item)
    result = {}
    for fy, periods in groups.items():
        cumulative = {}
        for q, term in enumerate(('Q1', 'Q2', 'Q3', 'FY'), 1):
            options = periods.get(term, [])
            lo, hi = {1:(60,127),2:(155,245),3:(245,332),4:(331,401)}[q]
            ytd = preferred([r for r in options if lo <= r['days'] <= hi])
            direct = preferred([r for r in options if 60 <= r['days'] <= 127]) if q < 4 else None
            if ytd:
                cumulative[q] = ytd
            if direct:
                val, source = direct['val'], direct
            elif ytd and q == 1:
                val, source = ytd['val'], ytd
            elif ytd and (q-1) in cumulative:
                prev = cumulative[q-1]
                elapsed = ytd['days'] - prev['days']
                val = (ytd['val']*ytd['days'] - prev['val']*prev['days'])/elapsed if elapsed > 0 else None
                source = ytd
            else:
                val, source = None, None
            if val is not None and val > 0 and source:
                result[(fy,q)] = (source['end'], val, source['filed'])
    return result


def quarter_instants(items: list[dict]) -> dict[tuple[int, int], tuple[str, float]]:
    result = {}
    byperiod: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for r in items:
        if r['days'] is not None:
            continue
        q = {'Q1': 1, 'Q2': 2, 'Q3': 3, 'FY': 4}.get(r['fp'])
        if q:
            byperiod[(r['fy'], q)].append(r)
    for period, opts in byperiod.items():
        best = preferred(opts)
        if best:
            result[period] = (best['end'], best['val'], best['filed'])
    return result


def sum_nonnull(values: list[float | None], min_count: int) -> float | None:
    numbers = [v for v in values if isinstance(v, (int, float))]
    return sum(numbers) if len(numbers) >= min_count else None


def safe_ratio(a, b, multiplier=100) -> float | None:
    return round(multiplier * a / b, 4) if a is not None and b not in (None, 0) else None


def clean(v):
    if v is None:
        return None
    if abs(v) > 1e23:
        return None
    return round(float(v), 5)


def detect_currency(companyfacts: dict) -> str:
    """Choose the reporting denomination; never convert EUR/GBP into fictitious USD."""
    facts = companyfacts.get('facts', {})
    counts = {currency: 0 for currency in ('USD', 'EUR', 'GBP', 'CHF', 'CAD', 'JPY')}
    for tag in FLOW_TAGS['revenue']:
        for ns in ('us-gaap', 'ifrs-full'):
            units = facts.get(ns, {}).get(tag, {}).get('units', {})
            for currency in counts:
                counts[currency] += sum(1 for r in units.get(currency, []) if r.get('form') in FORMS)
    return max(counts, key=lambda k: counts[k])


def compute_rows(companyfacts: dict, ticker: str, currency: str = 'USD') -> list[dict]:
    facts = companyfacts.get('facts', {})
    flow_by_name = {
        key: (quarter_shares if key == 'shares' else quarter_flows)(
            fact_entries(facts, tags,
                'shares' if key == 'shares' else f'{currency}/shares' if key == 'epsDiluted' else currency))
        for key, tags in FLOW_TAGS.items()
    }
    instant_by_name = {key: quarter_instants(fact_entries(facts, tags, currency)) for key, tags in INSTANT_TAGS.items()}
    keys = set()
    for lookup in [*flow_by_name.values(), *instant_by_name.values()]:
        keys.update(lookup.keys())
    points = []
    for fy, quarter in sorted(keys):
        qvals, valid_ends = {}, []
        for key, store in flow_by_name.items():
            record = store.get((fy, quarter))
            if record:
                valid_ends.append(record[0]);qvals[key] = record[1]
        for key, store in instant_by_name.items():
            record = store.get((fy, quarter))
            if record:
                valid_ends.append(record[0]);qvals[key] = record[1]
        if not valid_ends:
            continue
        date = max(valid_ends, key=lambda x: (valid_ends.count(x), x))
        income_record = flow_by_name.get('netIncome', {}).get((fy, quarter))
        filing_date = income_record[2] if income_record else None
        # Exclude obsolete or clearly unrelated dates, without making any data up.
        if parse_date(date) and parse_date(date) < dt.date.today()-dt.timedelta(days=365*13):
            continue
        cfo, capex = qvals.get('cfo'), qvals.get('capex')
        if capex is not None:
            qvals['capex'] = abs(capex)
        if cfo is not None and capex is not None:
            qvals['fcf'] = cfo - abs(capex)
        gross_debt = [qvals.get('longDebt'), qvals.get('currentDebt'), qvals.get('shortDebt')]
        if gross_debt[0] is not None or gross_debt[1] is not None or gross_debt[2] is not None:
            qvals['totalDebt'] = sum(gross_debt[i] or 0 for i in range(len(gross_debt)))
        if 'totalDebt' in qvals and qvals.get('cash') is not None:
            qvals['netDebt'] = qvals['totalDebt'] - qvals['cash']
        if qvals.get('equity') is not None and qvals.get('totalDebt') is not None and qvals.get('cash') is not None:
            qvals['investedCapital'] = qvals['equity']+qvals['totalDebt']-qvals['cash']
        qvals['operatingMargin'] = safe_ratio(qvals.get('operatingIncome'), qvals.get('revenue'))
        qvals['fcfMargin'] = safe_ratio(qvals.get('fcf'), qvals.get('revenue'))
        points.append({'end':date,'label':f'FY{fy} Q{quarter}','fy':fy,'fq':quarter,'filed':filing_date,'q':{k:clean(v) for k,v in qvals.items()},'ttm':{}})
    # SEC facts may contain multiple fiscal calendars during fiscal year changes.
    points.sort(key=lambda r:(r['end'],r['fy'],r['fq']))
    unique={}
    for r in points:
        if r['end'] not in unique or len(r['q'])>len(unique[r['end']]['q']):
            unique[r['end']]=r
    points=sorted(unique.values(),key=lambda r:r['end'])
    flow_keys=['revenue','operatingIncome','netIncome','cfo','capex','fcf','taxExpense','pretaxIncome','interestExpense','epsDiluted']
    for i,p in enumerate(points):
        t={}
        if i >= 3:
            recent=points[i-3:i+1]
            contiguous=all((recent[j]['fy']*4+recent[j]['fq'])-(recent[j-1]['fy']*4+recent[j-1]['fq'])==1 for j in range(1,4))
            if contiguous:
                for key in flow_keys:
                    vals=[r['q'].get(key) for r in recent]
                    if all(v is not None for v in vals):
                        t[key]=clean(sum(vals))
                share_vals=[r['q'].get('shares') for r in recent]
                if all(v is not None for v in share_vals):
                    t['shares']=clean(sum(share_vals)/4)
                t['operatingMargin']=safe_ratio(t.get('operatingIncome'),t.get('revenue'))
                t['fcfMargin']=safe_ratio(t.get('fcf'),t.get('revenue'))
                interest=t.get('interestExpense')
                if interest and interest>0 and t.get('operatingIncome') is not None:
                    t['interestCoverage']=safe_ratio(t['operatingIncome'],interest,1)
                if i>=4:
                    old=points[i-4]['q']
                    eq0,eq1=old.get('equity'),p['q'].get('equity')
                    if eq0 is not None and eq1 is not None and (eq0+eq1)>0:
                        t['roe']=safe_ratio(t.get('netIncome'),(eq0+eq1)/2)
                    cap0,cap1=old.get('investedCapital'),p['q'].get('investedCapital')
                    pre,tax=t.get('pretaxIncome'),t.get('taxExpense')
                    if ticker not in FINANCIAL_TICKERS and cap0 is not None and cap1 is not None and cap0+cap1>0 and pre and pre>0 and tax is not None:
                        rate=tax/pre
                        if 0 <= rate <= 0.5:
                            op=t.get('operatingIncome')
                            if op is not None:
                                t['roic']=safe_ratio(op*(1-rate),(cap0+cap1)/2)
        for key in ['cash','equity','assets','totalDebt','netDebt','investedCapital']:
            if key in p['q']:
                t[key]=p['q'][key]
        p['ttm']={k:v for k,v in t.items() if v is not None}
    return points[-40:]


def main():
    path=DATA/'financials.json'
    current=load_json(path, {'companies':{}})
    current.setdefault('companies', {})
    user_agent=os.getenv('SEC_USER_AGENT','').strip()
    if not user_agent:
        print('SEC_USER_AGENT secret missing — keep existing financials and deploy empty state if needed.')
        return 0
    max_age=int(os.getenv('FINANCIAL_MAX_AGE_HOURS','72'))
    force=os.getenv('FORCE_FINANCIALS','false').lower() in ('true','1','yes')
    watches=load_json(DATA/'watchlists.json')
    by_ticker={x['ticker']:x for part in ('great_companies_60','berkshire_top_25') for x in watches[part]}
    s=get_session(user_agent)
    try:
        raw=request_json(s,'https://www.sec.gov/files/company_tickers.json')
    except Exception as exc:
        print(f'SEC ticker lookup unavailable: {exc}. Existing data retained.');return 0
    lookup={v['ticker'].upper():int(v['cik_str']) for v in raw.values()}
    aliases={'MRSH':'MMC','LLYVK':'LLYVA','LEN':'LEN.B'}
    updated=0;failed=[];skipped=0
    for ticker,c in by_ticker.items():
        old=current['companies'].get(ticker,{})
        date=old.get('updated_at')
        try:
            age=(dt.datetime.now(TZ)-dt.datetime.fromisoformat(date.replace('Z','+00:00'))).total_seconds()/3600 if date else 1e8
        except (ValueError,TypeError):age=1e8
        if (not force and age < max_age and old.get('schema_version') == FINANCIAL_SCHEMA_VERSION
                and all('filed' in r for r in old.get('rows', []))):
            skipped+=1;continue
        cik=lookup.get(ticker) or lookup.get(aliases.get(ticker,''))
        if not cik:
            failed.append(f'{ticker}: CIK not found');continue
        try:
            data=request_json(s,f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json')
            currency=detect_currency(data)
            rows=compute_rows(data,ticker,currency)
            current['companies'][ticker]={
                'name':c['name'],'ticker':ticker,'cik':cik,'currency':currency,'latest_period':rows[-1]['end'] if rows else None,
                'updated_at':nowiso(),'schema_version':FINANCIAL_SCHEMA_VERSION,'rows':rows,'coverage':{'periods':len(rows),'metrics':{k:sum(1 for row in rows if row['q'].get(k) is not None or row['ttm'].get(k) is not None) for k in FLOW_TAGS.keys()}}
            }
            updated+=1
        except Exception as exc:
            failed.append(f'{ticker}: {type(exc).__name__}: {str(exc)[:90]}')
        time.sleep(.38)
    if updated:
        current['generated_at']=nowiso();current['source']='SEC EDGAR Company Facts'
        save_json(path,current)
    print(f'Financials: updated={updated}, cached={skipped}, failed={len(failed)}, known={len(current["companies"])}')
    for item in failed:print('Warning:',item)
    return 0


if __name__=='__main__':
    sys.exit(main())
