#!/usr/bin/env python3
"""Non-realtime daily closing-price fetch with independent public-source fallbacks.
No fictional values are emitted on provider failures. Optional Telegram alerts.
"""
from __future__ import annotations
import csv
import datetime as dt
import io
import json
import os
import sys
import time
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'

def load(p, default=None):
    try:return json.loads(p.read_text(encoding='utf8'))
    except (FileNotFoundError,ValueError):return default if default is not None else {}

def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf8')

def date_now():return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')

def close_stooq(session, ticker):
    symbol=ticker.lower()+'.us'
    r=session.get('https://stooq.com/q/l/',params={'s':symbol,'i':'d'},timeout=14)
    r.raise_for_status()
    parts=next(csv.reader(io.StringIO(r.text.strip())),[])
    # Symbol,Date,Time,Open,High,Low,Close,Volume
    if len(parts)<7 or 'N/D' in parts[1:7]:return None
    close=float(parts[6]);day=parts[1]
    if not (close>0 and len(day)==8 and day.isdigit()):return None
    return {'close':round(close,4),'date':f'{day[:4]}-{day[4:6]}-{day[6:]}','source':'Stooq','updated_at':date_now()}

def close_yahoo(session,ticker):
    symbol=ticker.replace('.','-')
    r=session.get(f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}',params={'interval':'1d','range':'5d'},timeout=14)
    r.raise_for_status()
    item=r.json()['chart']['result'][0]
    timestamps=item.get('timestamp') or []
    closes=item['indicators']['quote'][0].get('close') or []
    for stamp,close in reversed(list(zip(timestamps,closes))):
        if close and close>0:
            date=dt.datetime.fromtimestamp(stamp,dt.timezone.utc).date().isoformat()
            return {'close':round(float(close),4),'date':date,'source':'Yahoo Finance (delayed)','updated_at':date_now()}
    return None

def history_stooq(session,ticker):
    end=dt.date.today();start=end-dt.timedelta(days=375)
    sym=ticker.lower()+'.us'
    r=session.get('https://stooq.com/q/d/l/',params={'s':sym,'i':'d','d1':start.strftime('%Y%m%d'),'d2':end.strftime('%Y%m%d')},timeout=20)
    r.raise_for_status()
    data=list(csv.DictReader(io.StringIO(r.text.strip())))
    history=[]
    for row in data:
        try:
            day=row.get('Date','');close=float(row.get('Close',''))
            if len(day)==10 and close>0:history.append({'date':day,'close':round(close,4)})
        except (TypeError,ValueError):continue
    return history[-270:] if len(history)>=20 else []


def history_yahoo(session,ticker):
    sym=ticker.replace('.','-')
    r=session.get(f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}',params={'interval':'1d','range':'1y'},timeout=20)
    r.raise_for_status()
    item=r.json()['chart']['result'][0]
    history=[]
    for stamp,close in zip(item.get('timestamp') or [],item['indicators']['quote'][0].get('close') or []):
        if close and close>0:
            day=dt.datetime.fromtimestamp(stamp,dt.timezone.utc).date().isoformat()
            history.append({'date':day,'close':round(float(close),4)})
    return history[-270:] if len(history)>=20 else []


def reusable_history(previous, quote):
    """Reuse one-year candles between full refreshes; append the new closing price.

    Chart data are refreshed from the provider at most weekly in normal operation.
    A gap, stale cache or suspected split forces a full refresh. The previous
    history is never replaced by guessed intermediate daily prices.
    """
    if not isinstance(previous, dict):
        return None
    history = previous.get('history') or []
    if len(history) < 20:
        return None
    try:
        quote_date = dt.date.fromisoformat(quote['date'])
        prev_date = dt.date.fromisoformat(history[-1]['date'])
        prev_close = float(history[-1]['close'])
        quote_close = float(quote['close'])
        if quote_date < prev_date or (quote_date - prev_date).days > 5:
            return None
        if prev_close <= 0 or quote_close <= 0 or not (0.65 < quote_close / prev_close < 1.55):
            return None
        refreshed_at = previous.get('history_updated_at')
        if refreshed_at:
            refresh_date = dt.date.fromisoformat(str(refreshed_at)[:10])
            if (quote_date - refresh_date).days >= 7:
                return None
    except (KeyError, ValueError, TypeError, ZeroDivisionError):
        return None
    result = [dict(x) for x in history]
    if quote_date == prev_date:
        result[-1] = {'date':quote['date'], 'close':quote['close']}
    else:
        result.append({'date':quote['date'], 'close':quote['close']})
    # Keep a full calendar year of daily closes rather than indefinite buildup.
    cutoff = quote_date - dt.timedelta(days=375)
    return [r for r in result if dt.date.fromisoformat(r['date']) >= cutoff][-270:]


def notify_telegram(token,chat_id,message):
    r=requests.post(f'https://api.telegram.org/bot{token}/sendMessage',data={'chat_id':chat_id,'text':message},timeout=15)
    r.raise_for_status()

def alerts(prices):
    config=load(ROOT/'config'/'alerts.json')
    token=os.getenv('TELEGRAM_BOT_TOKEN','')
    chat_id=os.getenv('TELEGRAM_CHAT_ID','')
    if not config.get('enabled') or not token or not chat_id:
        print('Telegram alerts skipped (not configured).')
        return
    state_path=DATA/'alert_state.json';state=load(state_path,{})
    changed=False
    for ticker,threshold in (config.get('targets') or {}).items():
        if not isinstance(threshold,(int,float)) or threshold<=0:continue
        p=prices.get(ticker)
        if not p or not p.get('close'):continue
        close=p['close'];fired=bool(state.get(ticker,{}).get('below_alert_sent'))
        if close<=threshold and not fired:
            msg=f'📍 매수 관심 가격 도달\n{ticker}\n최근 종가: ${close:,.2f}\n목표 매수가: ${threshold:,.2f}\n기준일: {p["date"]}\n\n투자 판단 전 사업의 경쟁우위와 최근 공시를 재검토하세요. (실시간 시세 아님)'
            try:
                notify_telegram(token,chat_id,msg)
                state[ticker]={'below_alert_sent':True,'sent_at':date_now(),'threshold':threshold};changed=True
                print('Telegram sent:',ticker)
            except requests.RequestException as exc:print('Alert failed:',ticker,str(exc)[:100])
        elif close>threshold*1.02 and fired:
            state[ticker]={'below_alert_sent':False,'rearmed_at':date_now(),'threshold':threshold};changed=True
        elif fired and state.get(ticker,{}).get('threshold')!=threshold:
            # A changed threshold is a new alert condition.
            state[ticker]['below_alert_sent']=False;state[ticker]['threshold']=threshold;changed=True
    if changed:save(state_path,state)

def main():
    watches=load(DATA/'watchlists.json')
    tickers=list(dict.fromkeys(x['ticker'] for part in ('great_companies_60', 'additional_watchlist_80', 'berkshire_top_25') for x in watches[part]))
    path=DATA/'prices.json';out=load(path,{'companies':{}});out.setdefault('companies',{})
    session=requests.Session();session.headers.update({'User-Agent':'Mozilla/5.0 (compatible; InvestmentResearchDashboard/1.0)','Accept':'text/csv, application/json'})
    ok=0;errors=[];just_fetched={}
    for ticker in tickers:
        result=None
        for provider in (close_stooq,close_yahoo):
            try:result=provider(session,ticker)
            except (requests.RequestException,ValueError,KeyError,IndexError,TypeError):result=None
            if result:break
        if result:
            previous=out['companies'].get(ticker,{})
            if previous.get('date') and previous['date'] > result['date']:
                errors.append(f'{ticker} (시세 제공처 날짜 지연)')
                continue
            cached_history=reusable_history(previous,result)
            if cached_history:
                result['history']=cached_history
                result['history_source']=previous.get('history_source','')
                result['history_updated_at']=previous.get('history_updated_at') or date_now()
            else:
                for history_provider in (history_stooq,history_yahoo):
                    try:hist=history_provider(session,ticker)
                    except (requests.RequestException,ValueError,KeyError,IndexError,TypeError):hist=[]
                    if hist:
                        result['history']=hist
                        result['history_source']='Stooq' if history_provider==history_stooq else 'Yahoo Finance (delayed)'
                        result['history_updated_at']=date_now()
                        break
            if 'history' not in result and previous:
                result['history']=previous.get('history',[])
                result['history_source']=previous.get('history_source','')
                result['history_updated_at']=previous.get('history_updated_at')
            out['companies'][ticker]=result;just_fetched[ticker]=result;ok+=1
        else:errors.append(ticker)
        time.sleep(.12)
    if ok:
        out['generated_at']=date_now();out['source']='Stooq, Yahoo Finance (fallback) · delayed close';save(path,out)
    print(f'Prices: updated={ok}, unavailable={len(errors)}')
    if errors:print('Not updated:',', '.join(errors))
    alerts(just_fetched)
    return 0
if __name__=='__main__':sys.exit(main())
