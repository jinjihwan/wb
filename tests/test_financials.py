import json
import sys
import unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'scripts'))
from update_financials import quarter_flows,quarter_instants,compute_rows,safe_ratio,detect_currency

class TestFinance(unittest.TestCase):
    def test_q4_from_year_to_date(self):
        records=[]
        for fp,end,days,value in [('Q1','2025-03-31',90,100),('Q2','2025-06-30',181,240),('Q3','2025-09-30',273,360),('FY','2025-12-31',365,500)]:
            records.append(dict(fy=2025,fp=fp,end=end,days=days,val=value,priority=0,delay=35,filed=end,tag='Revenue'))
        quarters=quarter_flows(records)
        self.assertEqual([quarters[(2025,q)][1] for q in range(1,5)],[100,140,120,140])
    def test_standalone_quarter_preferred(self):
        rec=[dict(fy=2025,fp='Q2',end='2025-06-30',days=d,val=v,priority=0,delay=40,filed='2025-08-01') for d,v in [(90,70),(180,180)]]
        self.assertEqual(quarter_flows(rec)[(2025,2)][1],70)
    def test_safe_ratio(self):
        self.assertIsNone(safe_ratio(100,0))
        self.assertEqual(safe_ratio(25,100),25)
    def test_lists_count(self):
        w=json.loads((root/'data/watchlists.json').read_text())
        self.assertEqual(len(w['great_companies_60']),60)
        self.assertEqual(len(w['berkshire_top_25']),25)
        self.assertEqual(len(set(x['ticker'] for k in ('great_companies_60','berkshire_top_25') for x in w[k])),81)
    def test_currency_detection(self):
        data={'facts':{'ifrs-full':{'Revenue':{'units':{'EUR':[{'form':'20-F'}]*3,'USD':[{'form':'20-F'}]}}}}}
        self.assertEqual(detect_currency(data),'EUR')
    def test_empty_data(self):
        self.assertEqual(compute_rows({'facts':{}},'CTAS'),[])
if __name__=='__main__':unittest.main()

class TestPerShareFacts(unittest.TestCase):
    def test_diluted_eps_usd_per_share(self):
        from update_financials import fact_entries, FLOW_TAGS, quarter_flows
        facts={'us-gaap':{'EarningsPerShareDiluted':{'units':{'USD/shares':[
            {'form':'10-Q','fy':2026,'fp':'Q1','start':'2026-01-01',
             'end':'2026-03-31','filed':'2026-04-20','val':1.25}]}}}}
        out=quarter_flows(fact_entries(facts,FLOW_TAGS['epsDiluted'],'USD/shares'))
        self.assertEqual(out[(2026,1)][1],1.25)
