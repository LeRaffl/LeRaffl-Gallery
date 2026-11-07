#!/usr/bin/env python3
"""Offline JP/KR source activation, historical boundary and token preservation."""
import csv
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import fetch_japan as jp
import fetch_south_korea as kr
import test_fetch_south_korea as kfixtures
from csv_records import csv_records,record_ending
ROOT=Path(__file__).resolve().parent
JP={'PETROL':59876,'HEV':121955,'PHEV':3582,'DIESEL':9135,'BEV':5419,'FCEV':79,'OTHERS':1,'TOTAL':200047}
KR=kr.rows_of(kr.parse_release(kfixtures.AUG_2026))['2026-08']


def record(values,eol='\r\n'):
    out=io.StringIO(newline='');csv.writer(out,lineterminator='\r\n').writerow(values)
    return out.getvalue()[:-2]+eol


class Sources(unittest.TestCase):
    def test_japan_real_xlsx_and_pdf_exact_disjoint_counts_and_total(self):
        x=(ROOT/'fixtures/202605081028169165.xlsx').read_bytes()
        pdf=(ROOT/'fixtures/202605081027423166.pdf').read_bytes()
        for m,fc,other,total in [(1,79,1,200047),(2,29,0,211362),(3,29,0,265438),(4,14,0,223369)]:
            a=jp.parse_xlsx(x,2026,m);b=jp.parse_pdf(pdf,2026,m)
            self.assertEqual(a,b);self.assertEqual((a['FCEV'],a['OTHERS'],a['TOTAL']),(fc,other,total))
            self.assertEqual(sum(v or 0 for k,v in a.items() if k!='TOTAL'),a['TOTAL'])
        self.assertEqual(jp.parse_xlsx(x,2026,1),JP)

    def test_market_top_stays_legacy_inclusive_for_all_existing_sample_sheets(self):
        for filename,year,months in [('202605081028169165.xlsx',2026,range(1,5)),('燃料別登録台数統計（2022年1月~12月）.xlsx',2022,range(1,13))]:
            x=(ROOT/'fixtures'/filename).read_bytes();ranks=jp.parse_xlsx_makers(x)
            for m in months:
                fuels=jp.parse_xlsx(x,year,m);units,total=ranks[f'{year}-{m:02d}']
                self.assertEqual(total,fuels['TOTAL']);self.assertFalse(any(k[0]=='FCEV' for k in units))
                for k in jp.MAKER_CLASSES:
                    expected=fuels[k]+((fuels['FCEV'] or 0) if k=='OTHERS' else 0)
                    self.assertEqual(sum(n for (cat,_,_),n in units.items() if cat==k),expected)

    def test_workbook_missing_optional_cell_is_not_reported_zero(self):
        for fc in [None,'',' ','-','--',' - ',' -- ',0,5]:
            row=[None]*18;row[13]=fc;row[15]=3
            self.assertEqual(jp._xlsx_total_row_to_fuels(tuple(row))['FCEV'],fc if isinstance(fc,int) else None)

    def test_short_pdf_without_confirmed_cell_keeps_combined_other(self):
        for fc,others in [(None,7),(0,7),(3,4)]:
            counts=[1000,50,10,20,10,7,1097]
            text='燃料別メーカー別登録台数（乗用車）2027年1月\n'+' '.join(f'{n:,} 100.0' for n in counts)
            reader=SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda:text)])
            with patch('pypdf.PdfReader',return_value=reader),patch.object(jp,'_pdf_fcev_cell',return_value=fc):
                out=jp.parse_pdf(b'unused',2027,1)
            self.assertEqual((out['FCEV'],out['OTHERS'],out['TOTAL']),(fc,others,1097))

    def test_physical_pdf_cell_blank_unknown_printed_zero_known(self):
        words=[dict(text='乗用車計',x0=1,x1=10,top=100),dict(text='ＦＣＶ',x0=50,x1=60,top=10),dict(text='その他(*)',x0=100,x1=110,top=10)]
        for token,expected in [(None,None),('0',0),('2',2)]:
            w=words+([dict(text=token,x0=60,x1=65,top=101)] if token else [])
            page=SimpleNamespace(extract_words=lambda:w)
            with patch('pdfplumber.open') as mocked:
                mocked.return_value.__enter__.return_value.pages=[page]
                self.assertEqual(jp._pdf_fcev_cell(b'unused',0,5),expected)

    def test_korea_real_source_hydrogen_excluded_from_ice_and_other(self):
        self.assertEqual(KR,dict(BEV=31060,FCEV=312,PHEV=1334,HEV=36102,OTHERS=0,ICE=41112,TOTAL=109920))
        self.assertEqual(sum(v for k,v in KR.items() if k!='TOTAL'),KR['TOTAL'])
        p=kr.parse_release(kfixtures.AUG_2026);p['parts']['FCEV'][-1]+=1
        with self.assertRaisesRegex(kr.ParseError,'original TOTAL'):kr.rows_of(p)
        # A vanished mandatory source row is schema drift, not FCEV=0.
        with self.assertRaises(kr.ParseError):kr.parse_release(kfixtures.AUG_2026.replace('수소차 1,292 1,085 312','missing 1,292 1,085 312'))


class Writers(unittest.TestCase):
    def fixture(self,country,eol='\r\n',final=True,with_fc=False):
        mod,counts=(jp,JP) if country=='jp' else (kr,KR)
        cols=[k for k in mod.CSV_COLUMNS if with_fc or k!='FCEV']+['extra']
        vals=dict(jp.build_row('2026-01',counts,'source') if country=='jp' else dict(zip(kr.CSV_COLUMNS,csv_records(kr.render_line('2026-01',counts))[0][0])))
        vals['FCEV']='';vals['OTHERS']=f"{counts['OTHERS']+(counts['FCEV'] or 0):.5e}"
        vals['BEV']=f"{counts['BEV']:.7e}";vals['notes']='note, "quoted"\r\nsecond\nline';vals['extra']='001.2300, "custom"'
        return mod,counts,cols,vals,record(cols,eol),record([vals.get(k,'') for k in cols],eol if final else '')

    def write(self,country,path,period,counts,force=False,notes=''):
        if country=='jp':return jp.upsert_row(str(path),period,jp.build_row(period,counts,notes),force)
        return kr.upsert(path,{period:kr.render_line(period,counts,notes)},force)

    def rows(self,path):
        with path.open(newline='') as f:return list(csv.DictReader(f))

    def test_on_demand_migration_preserves_every_old_token_record_and_final_ending(self):
        for country in ['jp','kr']:
            for eol in ['\n','\r\n','\r']:
                for final in [False,True]:
                    with self.subTest(country=country,eol=eol,final=final),tempfile.TemporaryDirectory() as d:
                        mod,counts,cols,vals,head,old=self.fixture(country,eol,final)
                        path=Path(d)/'country.csv';path.write_bytes((head+old).encode())
                        self.write(country,path,'2027-01',counts)
                        text=path.read_bytes().decode();recs=csv_records(text)
                        self.assertEqual(recs[0][0],cols+['FCEV'])
                        self.assertEqual(recs[0][1],head[:-len(eol)]+',FCEV'+eol)
                        old_body=old[:-len(eol)] if final else old
                        self.assertEqual(recs[1][1],old_body+','+eol)
                        self.assertEqual(bool(record_ending(recs[-1][1])),final)
                        rows=self.rows(path);self.assertEqual(rows[0]['FCEV'],'')
                        self.assertEqual(float(rows[1]['FCEV']),counts['FCEV'])
                        self.assertEqual(float(rows[1]['OTHERS']),counts['OTHERS'])
                        self.assertEqual(rows[0]['extra'],vals['extra']);self.assertEqual(rows[0]['notes'],vals['notes'])
                        self.assertEqual(float(rows[1]['TOTAL']),counts['TOTAL'])
                        before=path.read_bytes();self.write(country,path,'2027-01',counts,True)
                        self.assertEqual(path.read_bytes(),before)

    def test_existing_unknown_stays_inclusive_even_on_force_with_no_schema_only_write(self):
        for country in ['jp','kr']:
            for with_fc in [False,True]:
                with self.subTest(country=country,with_fc=with_fc),tempfile.TemporaryDirectory() as d:
                    _,counts,_,vals,head,old=self.fixture(country,with_fc=with_fc)
                    path=Path(d)/'country.csv';before=(head+old).encode();path.write_bytes(before)
                    self.write(country,path,'2026-01',counts,True,vals['notes'])
                    self.assertEqual(path.read_bytes(),before)
                    self.write(country,path,'2027-01',counts)
                    migrated=path.read_bytes();self.write(country,path,'2026-01',counts,True,vals['notes'])
                    self.assertEqual(path.read_bytes(),migrated)
                    self.assertEqual(self.rows(path)[0].get('FCEV',''),'')

    def test_missing_historical_gap_does_not_activate_fcev(self):
        for country in ['jp','kr']:
            with self.subTest(country=country),tempfile.TemporaryDirectory() as d:
                _,counts,_,_,head,old=self.fixture(country)
                path=Path(d)/'country.csv';path.write_bytes((head+old).encode())
                self.write(country,path,'2025-12',counts,True)
                rows=self.rows(path);self.assertNotIn('FCEV',rows[0]);self.assertEqual(float(rows[0]['OTHERS']),counts['OTHERS']+counts['FCEV'])

    def test_new_zero_vs_unavailable_and_later_optional_unknown_is_not_backfilled(self):
        for country in ['jp','kr']:
            with self.subTest(country=country),tempfile.TemporaryDirectory() as d:
                _,counts,_,_,head,old=self.fixture(country)
                path=Path(d)/'country.csv';path.write_bytes((head+old).encode())
                zero=dict(counts,FCEV=0,OTHERS=counts['OTHERS']+counts['FCEV'])
                unknown=dict(zero,FCEV=None)
                self.write(country,path,'2027-01',zero);self.write(country,path,'2027-02',unknown)
                rows=self.rows(path);self.assertEqual(float(rows[1]['FCEV']),0);self.assertEqual(rows[2]['FCEV'],'')
                self.write(country,path,'2027-02',counts,True)
                self.assertEqual(self.rows(path)[2]['FCEV'],'')

    def test_unavailable_fallback_never_erases_an_existing_confirmed_split(self):
        for country in ['jp','kr']:
            with self.subTest(country=country),tempfile.TemporaryDirectory() as d:
                _,counts,_,_,head,old=self.fixture(country)
                path=Path(d)/'country.csv';path.write_bytes((head+old).encode())
                self.write(country,path,'2027-01',counts)
                unknown=dict(counts,FCEV=None,OTHERS=counts['OTHERS']+counts['FCEV'])
                before=path.read_bytes();self.write(country,path,'2027-01',unknown,True)
                self.assertEqual(path.read_bytes(),before)
                unknown['OTHERS']+=1
                with self.assertRaisesRegex(ValueError,'confirmed source split'):
                    self.write(country,path,'2027-01',unknown,True)
                self.assertEqual(path.read_bytes(),before)

    def test_korea_replacement_keeps_unknown_extra_and_notes(self):
        with tempfile.TemporaryDirectory() as d:
            _,counts,_,_,head,old=self.fixture('kr')
            path=Path(d)/'kr.csv';path.write_bytes((head+old).encode());self.write('kr',path,'2027-01',counts)
            # The extra belongs to a corrected row too, not only untouched rows.
            rows=self.rows(path);row=rows[1];row['extra']='keep, me';row['notes']='keep\nnotes'
            recs=csv_records(path.read_bytes().decode());cols=recs[0][0]
            path.write_bytes((recs[0][1]+recs[1][1]+record([row[c] for c in cols])).encode())
            revised=dict(counts,BEV=counts['BEV']+1,TOTAL=counts['TOTAL']+1)
            self.write('kr',path,'2027-01',revised)
            updated=self.rows(path)[1];self.assertEqual(updated['extra'],'keep, me');self.assertEqual(updated['notes'],'keep\nnotes')

    def test_korea_drift_fails_atomically_and_old_self_throttle_compares_legacy_bucket(self):
        with tempfile.TemporaryDirectory() as d:
            _,counts,cols,vals,head,old=self.fixture('kr');self.assertEqual(kr.differs(counts,vals),[])
            path=Path(d)/'kr.csv'
            for malformed in [head+old+'2026-02,too,few\n',head+old+old,head+'2026-01,"unclosed']:
                path.write_bytes(malformed.encode());before=path.read_bytes()
                with self.assertRaises((ValueError,csv.Error)):self.write('kr',path,'2027-01',counts)
                self.assertEqual(path.read_bytes(),before)

if __name__=='__main__':unittest.main()
