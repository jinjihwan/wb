import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from update_financials import quarter_shares
from update_valuation import asof_pe, compute, split_factor

class TestValuation(unittest.TestCase):
    def test_split_adjusted_pe(self):
        row={'end':'2024-06-30','ttm':{'netIncome':1000},'q':{'shares':100}}
        splits=[{'date':'2024-08-15','ratio':2}]
        # Without split: price 20 / EPS 10 = 2; after 2:1 split price 10 / EPS 5 = 2
        self.assertEqual(asof_pe(row, 10, __import__('datetime').date(2024,9,30), splits), 2)
        self.assertEqual(split_factor(splits,__import__('datetime').date(2024,6,30),__import__('datetime').date(2024,9,30)),2)

    def test_no_pe_negative_earnings(self):
        row={'end':'2025-01-01','ttm':{'netIncome':-10},'q':{'shares':100}}
        self.assertIsNone(asof_pe(row, 10, __import__('datetime').date(2025,5,1), []))

    def test_quarterly_shares_weighted_not_subtraction(self):
        records=[]
        for term,days,val in [('Q1',90,110),('Q2',180,105),('Q3',270,100),('FY',360,95)]:
            records.append({'fy':2025,'fp':term,'end':'2025-12-31','days':days,'val':val,'priority':0,'delay':35,'filed':'2026-02-04'})
        quarters=quarter_shares(records)
        self.assertEqual([quarters[(2025,q)][1] for q in range(1,5)],[110,100,90,80])

    def test_computation_hides_currency_mismatch(self):
        f={'currency':'EUR','rows':[],'latest_period':'2026-01-01'}
        self.assertIsNone(compute(f,{'close':100,'date':'2026-10-30'}, {})['current_pe'])

    def test_average_does_not_use_pre_filing_prices(self):
        f={'currency':'USD','latest_period':'2026-01-01','rows':[{'end':'2026-01-01','filed':'2026-02-01','q':{'shares':100},'ttm':{'netIncome':1000}}]}
        p={'close':40,'date':'2026-10-30'}
        h={'source':'Yahoo','splits':[], 'monthly':[{'date':'2026-01-31','close':10},{'date':'2026-02-28','close':30}]}
        r=compute(f,p,h)
        self.assertEqual(r['current_pe'],4)
        self.assertEqual(r['samples'][0]['pe'],3)

if __name__=='__main__': unittest.main()
