#!/usr/bin/env python3
"""Offline optional-FCEV exporter regressions; no real country/data writes."""
import copy
import math
import unittest

import build_series as bs


def csv_rows(data):
    return [{k: str(v) for k,v in r.items()} for r in data]


def build(name,data):
    return bs.build_country(name,csv_rows(data))


def validate(name,data,result):
    return bs.validate(name,csv_rows(data),result)


def rows(n=36, korea=False):
    out = []
    for i in range(n):
        r = dict(period=f'{2023+i//12}-{i%12+1:02}', time_interval='monthly',
                 variant='Whole', source='offline fixture', BEV=10+i,
                 PHEV=2+i%3, HEV=30+i%5, OTHERS=3+i%3)
        if korea:
            r['ICE'] = 200+i
        else:
            r.update(PETROL=100+2*i, DIESEL=20+i%7)
        fc = 0 if i == 25 else 1+i%2
        r['OTHERS'] += fc
        r['TOTAL'] = sum(float(v) for k,v in r.items() if k in bs.BAND_ORDER)
        out.append(r)
    return out


def split(old, start=18):
    result = copy.deepcopy(old)
    for i,r in enumerate(result):
        fc = 0 if i == 25 else 1+i%2
        r['FCEV'] = '' if i < start else fc
        if i >= start:
            r['OTHERS'] -= fc
    return result


class FcevExportTests(unittest.TestCase):
    def test_japan_split_keeps_legacy_bands_periods_and_denominator(self):
        for korea in (False, True):
            with self.subTest(korea=korea):
                old = rows(korea=korea)
                baseline = build('fixture',old)
                new = build('fixture',split(old))
                self.assertEqual({k:v for k,v in new.items() if k != 'breakdown'},baseline)
                fc = new['breakdown']['FCEV']
                self.assertEqual(fc['parent'],'OTHERS')
                self.assertEqual(fc['v'][:18],[None]*18)
                self.assertEqual(fc['v'][25],0)
                self.assertNotIn('FCEV',new['b'])
                self.assertFalse(validate('fixture',split(old),new)[0])
                for i,t in enumerate(new['t']):
                    self.assertEqual(t,old[i]['TOTAL'])
                    self.assertEqual(sum(c[i] for c in new['b'].values()),t)

    def test_absent_and_all_empty_are_not_measured_zero(self):
        old=rows()
        baseline=build('fixture',old)
        self.assertNotIn('breakdown',baseline)
        for r in old:r['FCEV']=''
        new=build('fixture',old)
        self.assertEqual(new['b'],baseline['b'])
        self.assertEqual(new['m'],baseline['m'])
        self.assertTrue(all(v is None for v in new['breakdown']['FCEV']['v']))

    def test_blank_detail_does_not_change_existing_fractional_band_rounding(self):
        data=rows()
        for r in data:
            r['OTHERS']+=0.0125;r['TOTAL']+=0.0125
        old=build('fixture',data)
        blank=[dict(r,FCEV='') for r in data]
        self.assertEqual(old['b'],build('fixture',blank)['b'])

    def test_source_total_not_band_sum_even_inside_old_tolerance(self):
        data=[dict(period=f'2024-{i:02}',BEV=i,ICE=98+i,TOTAL=99+2*i) for i in (1,2,3)]
        new=build('fixture',data)
        self.assertEqual(new['t'],[101,103,105])
        self.assertEqual(sum(v[0] for v in new['b'].values()),100)
        self.assertFalse(validate('fixture',data,new)[0])
        for r in data:r['TOTAL']+=0.125
        self.assertEqual(build('fixture',data)['t'],[101.125,103.125,105.125])

    def test_tiny_fcev_not_dropped_or_double_counted_by_tolerance(self):
        data=rows(3,korea=True)
        for r in data:r['ICE']+=10000;r['TOTAL']+=10000
        new=build('fixture',split(data,start=0))
        self.assertEqual(new['t'],[r['TOTAL'] for r in data])
        self.assertEqual(new['breakdown']['FCEV']['v'],[1,2,1])
        overlap=split(data,start=0)
        overlap[0]['OTHERS']+=1
        with self.assertRaisesRegex(ValueError,'disjoint leaves'):
            build('fixture',overlap)

    def test_invalid_confirmed_counts_fail_before_projection(self):
        for bad in (-1, math.inf, math.nan, 'not a count'):
            data=split(rows(3),start=0);data[0]['FCEV']=bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                build('fixture',data)

    def test_native_quarters_and_years_keep_whole_observation_counts(self):
        for step,interval in ((3,'quarterly'),(12,'yearly')):
            data=split(rows(4),start=1)
            for i,r in enumerate(data):
                m=2020*12+i*step+(1 if step==3 else 6)
                r['period']=f'{m//12}-{m%12+1:02}'
                r['time_interval']=interval
            new=build('fixture',data)
            self.assertEqual(new['g'],[step]*4)
            self.assertEqual(new['breakdown']['FCEV']['g'],[step]*4)
            self.assertEqual(new['breakdown']['FCEV']['v'],[None,2,1,2])
            self.assertEqual(new['t'],[r['TOTAL'] for r in data])

    def test_detail_resolution_does_not_coarsen_legacy_months(self):
        data=rows(12)
        for r in data:
            r['FCEV']=1/12
            r['TOTAL']+=1/12
        new=build('fixture',data)
        self.assertEqual(new['g'],[1]*12)
        self.assertEqual(new['breakdown']['FCEV']['g'],[12]*12)
        self.assertAlmostEqual(sum(new['breakdown']['FCEV']['v']),1)

    def test_negative_other_with_offsetting_fcev_still_fails_audit(self):
        data=split(rows(3),start=0)
        data[0]['TOTAL']-=data[0]['OTHERS']+1
        data[0]['OTHERS']=-1
        new=build('fixture',data)
        self.assertTrue(any('negative' in e for e in validate('fixture',data,new)[0]))


if __name__=='__main__':unittest.main()
