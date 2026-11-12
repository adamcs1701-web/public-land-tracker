"""Offline checks for the commission-records matcher:  python3 tests/test_records.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import records as R

assert R.roll_addr_key("9250 W FLAGLER ST") == "9250|FLAGLER"
assert R.roll_addr_key("10071 60TH ST N") == "10071|N 60 ST"
assert R.roll_addr_key("100 NE 1 AVE") == "100|NE 1 AVE" and R.roll_addr_key("100 NW 1 ST") == "100|NW 1 ST"
assert R.roll_addr_key("EVERGLADES") is None and R.roll_addr_key("") is None
t = "lease of land located at 9250 West Flagler Street, Miami; also 100 N.E. 1st Avenue and 1515 West Cypress Creek Road."
k = R.text_addr_keys(t)
assert "9250|FLAGLER" in k and "1515|CYPRESS CREEK" in k and "100|NE 1 AVE" in k, k
assert R.text_folios("Folio Nos. 30-4004-024-0010 and 30-4004-000-0282; parcel 5042 01 01 0010; 504201010010") == {"3040040240010", "3040040000282", "504201010010"}
assert R.text_folios("Resolution R-894-26 dated 10-20-2026, phone 305-375-5000") == set()
assert R.tags_of("directing negotiation of a 99-year ground lease") == ["ground lease", "lease"]
assert "conveyance" in R.tags_of("authorizing conveyance by County Deed") and "deed" in R.tags_of("by County Deed")
assert "lease" not in R.tags_of("please release the funds")
cache = {"miami-dade": {"261810": {"gov": "x", "folios": ["3040040240010"], "addrs": ["9250|FLAGLER"], "tags": ["lease"]}},
         "broward": {"1": {"gov": "y", "folios": [], "addrs": ["1515|CYPRESS CREEK"], "tags": ["lease"]}}}
parcels = [{"county": "miami-dade", "id": "3040040240010", "address": ""}, {"county": "miami-dade", "id": "999", "address": "9250 W FLAGLER ST"},
           {"county": "broward", "id": "5", "address": "1515 W CYPRESS CREEK RD"}, {"county": "broward", "id": "6", "address": "9250 W FLAGLER ST"}]
items, bp = R.match(parcels, cache)
assert bp["miami-dade|3040040240010"] == [["miami-dade:261810", "folio"]] and bp["miami-dade|999"] == [["miami-dade:261810", "address"]]
assert bp["broward|5"] == [["broward:1", "address"]] and "broward|6" not in bp, bp
print("RECORDS TESTS PASSED")
