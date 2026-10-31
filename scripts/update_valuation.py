#!/usr/bin/env python3
"""Approximate trailing P/E and 10-year historical P/E statistics for GitHub Pages.

Uses SEC reported TTM income + quarter-end diluted weighted-average shares,
Yahoo Finance split-adjusted monthly CLOSE + corporate action split events.
Historical observations are aligned to the first month-end AFTER each 10-Q/10-K
filing, so unreleased earnings are not paired with an earlier stock price.
No forward P/E, no made-up missing values, no cross-currency price/EPS ratios.
"""
from __future__ import annotations
import concurrent.futures as futures
import datetime as dt
import json
import os
import statistics
import time
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
HISTORY_PATH = DATA / 'valuation_history.json'
VALUATION_PATH = DATA / 'valuation.json'


def load(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n', encoding='utf-8')


def parse_date(value):
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def today():
    return dt.datetime.now(dt.timezone.utc).date()


def tofloat(value):
    try:
        value = float(value)
        return value if 0 < value < 1e20 else None
    except (ValueError, TypeError):
        return None


def fetch_history(ticker):
    """Yahoo monthly CLOSE prices are split-adjusted (not dividend adjusted)."""
    symbol = ticker.replace('.', '-')
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe="")}'
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (compatible; LongTermInvestmentResearch/1.0)', 'Accept': 'application/json'})
    last_error = ''
    for attempt in range(2):
        try:
            res = session.get(url, params={'interval':'1mo','range':'10y','events':'splits'}, timeout=18)
            res.raise_for_status()
            item = res.json()['chart']['result'][0]
            stamps = item.get('timestamp') or []
            closes = (item.get('indicators') or {}).get('quote', [{}])[0].get('close') or []
            monthly = []
            for stamp, close in zip(stamps, closes):
                val = tofloat(close)
                if val is None:
                    continue
                day = dt.datetime.fromtimestamp(stamp, dt.timezone.utc).date()
                # A monthly bar's timestamp is its first trading day, not its closing day.
                next_month = dt.date(day.year+1, 1, 1) if day.month == 12 else dt.date(day.year, day.month+1, 1)
                reported_day = min(next_month - dt.timedelta(days=1), today())
                if reported_day <= today():
                    monthly.append({'date': reported_day.isoformat(), 'close': round(val, 5)})
            raw_splits = (item.get('events') or {}).get('splits') or {}
            splits = []
            for event in raw_splits.values():
                when = dt.datetime.fromtimestamp(event['date'], dt.timezone.utc).date()
                numer, denom = tofloat(event.get('numerator')), tofloat(event.get('denominator'))
                if numer and denom:
                    ratio = numer / denom
                    if ratio > 0:
                        splits.append({'date':when.isoformat(),'ratio':ratio})
            if len(monthly) < 18:
                raise ValueError('not enough historical monthly observations')
            return {'updated_at':today().isoformat(), 'source':'Yahoo Finance monthly Close (split-adjusted)',
                    'monthly':monthly, 'splits':sorted(splits,key=lambda x:x['date'])}, None
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
            last_error = f'{type(exc).__name__}: {str(exc)[:100]}'
            if attempt == 0:
                time.sleep(0.7)
    return None, last_error


def split_factor(splits, from_date, to_date):
    factor = 1.0
    for entry in splits:
        date = parse_date(entry.get('date'))
        if date and from_date < date <= to_date:
            ratio = tofloat(entry.get('ratio'))
            if ratio:
                factor *= ratio
    return factor


def asof_pe(row, quote_close, quote_date, splits):
    """NetIncome / diluted shares is APPROXIMATE EPS, not GAAP diluted EPS.

    Shares reported for the fiscal quarter are adjusted to the same present-day
    split basis as Yahoo's historical split-adjusted CLOSE prices.
    """
    qend = parse_date(row.get('end'))
    income = tofloat((row.get('ttm') or {}).get('netIncome'))
    shares = tofloat((row.get('q') or {}).get('shares'))
    if not qend or not income or not shares or not quote_close or not quote_date:
        return None
    equivalent_shares = shares * split_factor(splits, qend, today())
    eps = income / equivalent_shares
    pe = quote_close / eps if eps > 0 else None
    return round(pe, 3) if pe and 0 < pe < 1e5 else None


def compute(company, price, history):
    result = {'current_pe':None, 'average_pe_10y':None, 'median_pe_10y':None, 'ratio_to_average':None,
              'count':0, 'samples':[], 'price_date':price.get('date'), 'financial_date':company.get('latest_period'),
              'history_source':history.get('source') if history else None}
    if company.get('currency') != 'USD':
        result['note']='보고통화와 미국 상장 주가 통화 불일치: 자동 PER 제외'
        return result
    quote_date = parse_date(price.get('date'))
    quote_close = tofloat(price.get('close'))
    rows = (company.get('rows') or [])[-40:]
    if not rows or not quote_date or not quote_close:
        result['note']='SEC 순이익/희석 주식 수 또는 최근 종가 부족'
        return result
    splits = history.get('splits', []) if history else []
    # Without split-event history, do NOT attempt a price/shares alignment
    # across the last decade. Today-only P/E is still shown if the latest
    # fiscal quarter has no split since its end (unverified events might exist).
    if not history or not history.get('monthly'):
        result['note']='10년 주가·주식분할 이력 미확보: 현재 PER은 분할 미검증 근사값'
    eligible = [r for r in rows if parse_date(r.get('filed')) and parse_date(r.get('filed')) <= quote_date]
    if eligible:
        last = eligible[-1]
        # Protect against stale SEC filings and no released TTM figure.
        if parse_date(last.get('filed')) >= quote_date - dt.timedelta(days=500):
            result['current_pe'] = asof_pe(last, quote_close, quote_date, splits)
            result['eps_ttm_approx'] = round((last.get('ttm', {}).get('netIncome') or 0) /
                ((last.get('q', {}).get('shares') or 1) * split_factor(splits, parse_date(last['end']), today())), 5) \
                if result['current_pe'] is not None else None
    monthly = sorted([(parse_date(r.get('date')), tofloat(r.get('close'))) for r in (history or {}).get('monthly', [])], key=lambda x: x[0] or dt.date.min)
    obs=[]
    for row in rows:
        filed = parse_date(row.get('filed'))
        if not filed or filed > quote_date:
            continue
        # Use a price observed AFTER the earnings were made publicly available.
        candidate = next(((date, close) for date, close in monthly if date and close and date >= filed and
                          (date-filed).days <= 46 and date <= quote_date), None)
        if not candidate:
            continue
        d, close = candidate
        pe = asof_pe(row, close, d, splits)
        if pe is not None:
            obs.append({'period':row['end'],'price_date':d.isoformat(),'pe':pe})
    # Valid quarters with negative or zero net income never enter the mean.
    result['count'] = len(obs)
    result['samples'] = obs
    if len(obs) >= 8 and (parse_date(obs[-1]['period'])-parse_date(obs[0]['period'])).days >= 3*365:
        vals=[r['pe'] for r in obs]
        result['average_pe_10y']=round(statistics.mean(vals),2)
        result['median_pe_10y']=round(statistics.median(vals),2)
        if result['current_pe'] is not None:
            result['ratio_to_average']=round(result['current_pe']/result['average_pe_10y'],4)
    else:
        if not result.get('note'):
            result['note']='과거 PER 관측치 부족 (최소 8개 분기, 3년 이상 필요)'
    return result


def main():
    financials = load(DATA/'financials.json', {}).get('companies', {})
    prices = load(DATA/'prices.json', {}).get('companies', {})
    history_map = load(HISTORY_PATH, {'companies':{}})
    history_map.setdefault('companies',{})
    valuation = {'generated_at':dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
                 'source':'SEC EDGAR + Yahoo Finance monthly split-adjusted Close + recent closing price', 'companies':{}}
    candidates = [ticker for ticker in financials if ticker in prices]
    max_age = int(os.getenv('VALUATION_HISTORY_CACHE_DAYS','21'))
    stale=[]
    for ticker in candidates:
        existing=history_map['companies'].get(ticker)
        cached_date=parse_date((existing or {}).get('updated_at') or (existing or {}).get('last_attempt'))
        if existing and cached_date and (today()-cached_date).days < max_age and existing.get('monthly'):
            continue
        if existing and not existing.get('monthly') and cached_date and (today()-cached_date).days < 3:
            continue
        if financials[ticker].get('currency') != 'USD':
            continue
        stale.append(ticker)
    print(f'Valuation: cached price histories={len(candidates)-len(stale)}; refreshing={len(stale)}', flush=True)
    with futures.ThreadPoolExecutor(max_workers=4) as pool:
        future_map={pool.submit(fetch_history,ticker):ticker for ticker in stale}
        for completed in futures.as_completed(future_map):
            ticker=future_map[completed]
            record,error=completed.result()
            if record:
                history_map['companies'][ticker]=record
            else:
                old=history_map['companies'].get(ticker) or {}
                old['last_attempt']=today().isoformat()
                old['last_error']=error
                history_map['companies'][ticker]=old
                print('Valuation history unavailable:', ticker, error, flush=True)
    save(HISTORY_PATH,history_map)
    for ticker in candidates:
        valuation['companies'][ticker]=compute(financials[ticker],prices[ticker],history_map['companies'].get(ticker, {}))
    save(VALUATION_PATH,valuation)
    usable=sum(1 for item in valuation['companies'].values() if item['current_pe'] is not None)
    average=sum(1 for item in valuation['companies'].values() if item['average_pe_10y'] is not None)
    print(f'Valuation: current P/E={usable}, historical mean P/E={average}, total={len(candidates)}', flush=True)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
