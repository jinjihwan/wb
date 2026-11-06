#!/usr/bin/env python3
"""Write a reproducible 161-company data coverage report after scheduled refresh.

Coverage is a diagnostic only; missing non-applicable metrics must not be
mistaken for a failed SEC filing. Keeps every original source JSON intact.
"""
from __future__ import annotations
import csv
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
METRICS = ('revenue', 'operatingIncome', 'netIncome', 'cfo', 'capex', 'shares', 'epsDiluted')
TTM_METRICS = ('netIncome', 'cfo', 'capex', 'fcf', 'roe', 'roic')
FINANCIAL_TICKERS = {'ACIC', 'AII', 'ALLY', 'AMAL', 'AMSF', 'ASIC', 'AXP', 'BAC', 'BSVN', 'CARE', 'CASH', 'CB', 'CBNA', 'CBOE', 'COF', 'GCBC', 'HBNC', 'HRTG', 'JEF', 'LKFN', 'NRIM', 'OBT', 'PBAM', 'PFBC', 'PGR', 'PLBC', 'RCBC', 'RLI', 'ROOT', 'UVE'}


def read(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return {}


def tickers():
    watches = read(DATA / 'watchlists.json')
    return {item['ticker']: item['name'] for group in ('great_companies_60', 'additional_watchlist_80', 'berkshire_top_25')
            for item in watches.get(group, [])}


def run():
    financials = read(DATA / 'financials.json').get('companies') or {}
    prices = read(DATA / 'prices.json').get('companies') or {}
    valuations = read(DATA / 'valuation.json').get('companies') or {}
    names = tickers()
    today = dt.datetime.now(dt.timezone.utc).date()
    rows = []
    for ticker, name in names.items():
        fin = financials.get(ticker) or {}
        px = prices.get(ticker) or {}
        val = valuations.get(ticker) or {}
        periods = fin.get('rows') or []
        latest = periods[-1] if periods else {}
        quarter = latest.get('q') or {}
        ttm = latest.get('ttm') or {}
        missing_latest = [metric for metric in TTM_METRICS
                          if metric not in ttm and not (ticker in FINANCIAL_TICKERS and metric == 'roic')]
        metric_counts = {metric: sum(1 for p in periods if (p.get('q') or {}).get(metric) is not None)
                         for metric in METRICS}
        complete = sum(1 for p in periods if all((p.get('q') or {}).get(m) is not None
                                                     for m in ('revenue', 'operatingIncome', 'netIncome', 'cfo', 'capex')))
        last = fin.get('latest_period')
        try:
            fin_age = (today - dt.date.fromisoformat(last)).days
        except (ValueError, TypeError):
            fin_age = None
        price_history = px.get('history') or []
        flags = []
        if not periods:
            flags.append('재무 데이터 없음')
        elif fin_age is not None and fin_age > 185:
            flags.append('최근 재무 기준일 지연')
        if not isinstance(px.get('close'), (float, int)):
            flags.append('주가 없음')
        if missing_latest:
            flags.append('최신 TTM 일부 미산출')
        if ticker not in FINANCIAL_TICKERS and not (metric_counts['shares'] or metric_counts['epsDiluted']):
            flags.append('희석주식수·EPS 모두 없음')
        if val and val.get('excluded_count'):
            flags.append('과거 PER 극단치 검증 필요')
        if fin.get('currency') not in ('USD', None):
            flags.append('보고통화 USD 아님, PER 제외')
        rows.append({
            'ticker':ticker, 'name':name, 'currency':fin.get('currency'),
            'financial_periods':len(periods), 'latest_financial_period':last,
            'financial_age_days':fin_age, 'complete_core_quarters':complete,
            'latest_ttm_missing':missing_latest, 'metric_quarter_counts':metric_counts,
            'price_date':px.get('date'), 'price_history_days':len(price_history),
            'current_pe_available':val.get('current_pe') is not None,
            'average_pe_available':val.get('average_pe_10y') is not None,
            'pe_excluded_outliers':val.get('excluded_count', 0),
            'flags':flags,
        })
    result = {'generated_at':dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
              'companies_total':len(rows),
              'summary':{
                  'price_available':sum('주가 없음' not in r['flags'] for r in rows),
                  'full_40_period_rows':sum(r['financial_periods'] >= 40 for r in rows),
                  'latest_ttm_fcf_available':sum('fcf' not in r['latest_ttm_missing'] for r in rows),
                  'latest_ttm_roic_available_nonfinancial':sum('roic' not in r['latest_ttm_missing'] and r['ticker'] not in FINANCIAL_TICKERS for r in rows),
                  'current_pe_available':sum(r['current_pe_available'] for r in rows),
                  'average_pe_available':sum(r['average_pe_available'] for r in rows),
              }, 'companies': rows}
    (DATA / 'collection_status.json').write_text(json.dumps(result, ensure_ascii=False,
                                              separators=(',',':'))+'\n',encoding='utf-8')
    with (DATA / 'collection_status.csv').open('w',newline='',encoding='utf-8-sig') as handle:
        writer=csv.writer(handle)
        writer.writerow(['Ticker','기업','보고통화','분기수','재무기준일','재무경과일',
                         '완전한 핵심지표 분기수','최근 TTM 누락','주가일','주가 이력일수',
                         '현재 PER','10년 평균 PER','극단 PER 제외','진단'])
        for r in rows:
            writer.writerow([r['ticker'],r['name'],r['currency'],r['financial_periods'],
                             r['latest_financial_period'],r['financial_age_days'],
                             r['complete_core_quarters'],','.join(r['latest_ttm_missing']),
                             r['price_date'],r['price_history_days'],
                             'O' if r['current_pe_available'] else 'X',
                             'O' if r['average_pe_available'] else 'X',
                             r['pe_excluded_outliers'], '; '.join(r['flags'])])
    print('Data audit:', len(rows), 'tickers;', result['summary'])
    return result

if __name__ == '__main__':
    run()
