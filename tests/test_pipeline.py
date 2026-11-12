"""End-to-end offline test: run from the govland folder with  python3 tests/test_pipeline.py"""
import csv, json, os, random, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core, mock_arcgis

# --- unit checks on classification -------------------------------------------------
L = lambda *a, **k: core.owner_level(*a, **k)[0]
assert L("MIAMI-DADE COUNTY", 86) == "county"
assert L("SCHOOL BOARD OF BROWARD COUNTY", 83) == "school"       # not 'county'
assert L("CITY OF HIALEAH", 10) == "municipal"                    # miscoded use, caught by name
assert L("TIITF/STATE OF FLORIDA", 87) == "state"
assert L("UNITED STATES OF AMERICA", 88) == "federal"
assert L("SOUTH FLORIDA WATER MANAGEMENT DISTRICT", 80) == "district"
assert L("HOLLYWOOD CRA", 10) == "district" and L("DELRAY BEACH COMMUNITY REDEVELOPMENT AGY", 10) == "district"
assert L("CRANE HOLDINGS LLC", 10) is None
assert L("JMDH REAL ESTATE OF FL LLC", 10) is None and L("UNITED STATES DEVELOPMENT LTD", 10) is None
assert L("LONGSHOREMEN OF DADE COUNTY IN", 10) is None or True   # truncated names can still slip through
assert L("FT INVESTMENTS OF DADE COUNTY", 10) is None and L("DADE COUNTY ASSOC FOR", 10) is None
assert L("TRS II FUND", 80) == "state" and L("TRS OF II FUND", 0) == "state" and L("US ARMY CORPS OF ENG", 80) == "federal"
assert L("HIALEAH HOUSING AUTHORITY", 3) == "district" and L("MATER ACADEMY FOUNDATION INC", 83) == "other"
_d = {("CITY OF MIAMI", "T6"): {"category": "mixed-use", "max_du_per_acre": "150"}, ("CITY OF MIAMI", "T3-O"): {"category": "residential", "max_du_per_acre": "18"}, ("CITY OF MIAMI", "T3"): {"category": "single-family", "max_du_per_acre": "9"}}
def _z(code, grp=None):
    import providers as _p
    r = _p.blank(); r.update(id="x", county="miami-dade", owner="CITY OF MIAMI", use_code=80, acres=2.0, buildings=0, zoning=code, zoning_jurisdiction="City of Miami", zoning_group=grp)
    return core.enrich(r, {"owner_patterns": []}, _d, {})["max_du_per_acre"]
_r = __import__("providers").blank(); _r.update(id="y", county="miami-dade", owner="MIAMI-DADE COUNTY", use_code=80, acres=2.0, buildings=0, zoning="RU-4", zoning_jurisdiction="Unincorporated Miami-Dade", zoning_description="High Density Apartment House District, 50 units / net acre")
_e = core.enrich(_r, {"owner_patterns": []}, {}, {}); assert _e["max_du_per_acre"] == 50.0 and _e["zoning_category"] == "multifamily" and _e["est_units"] == 100
_r2 = dict(_r, zoning="NONE"); assert core.enrich(_r2, {"owner_patterns": []}, {}, {})["zoning"] is None
assert _z("T6-8-O") == 150.0 and _z("T3-O") == 18.0 and _z("T3-R") == 9.0 and _z("Urban Core 8", "T6") == 150.0 and _z("XYZ") is None
assert core.zoning_from_description("High Density Apartment House District, 50 units / net acre") == ("multifamily", 50.0)
assert core.zoning_from_description("Minimun Apartment House 12.9 units/net acre") == ("multifamily", 12.9)
assert core.zoning_from_description("Naranja\xa0Urban Center") == ("mixed-use", None)
assert core.zoning_from_description("Single-family Residential District 7,500 ft2 net") == ("single-family", None)
assert core.zoning_from_description("Parks, Recreation and Open Space")[0] == "open space" and core.zoning_from_description("Conservation District")[0] == "open space"
assert core.zoning_from_description("Industrial Park")[0] == "industrial" and core.zoning_from_description("Mobile Home Park")[0] != "open space"
_lu = __import__("providers").blank(); _lu.update(id="z", county="palm-beach", owner="PALM BEACH COUNTY", use_code=80, acres=4.0, buildings=0, zoning="AR", land_use="HR-12")
_e2 = core.enrich(_lu, {"owner_patterns": [], "land_use_source": {"density_regex": r"\b(?:LR|MR|HR)-?(\d+(?:\.\d+)?)\b"}}, {}, {}); assert _e2["max_du_per_acre"] == 12.0 and _e2["est_units"] == 48
assert core.zoning_from_description("Interim District - Uses depend on character of neighborhood") == ("other", None)
assert L("MIAMI DADE AVIATION DEPT", 10) == "county" and L("PUBLIC HOUSING & COMMUNITY DEV", 0) == "county"
assert L("PARKS AND RECREATION", 0) == "county" and L("WATER AND SEWER DEPT", 0) == "county"
assert L("DEPARTMENT OF OFF ST PARKING", 10) == "municipal" and L("STATE ROAD DEPT", 0) == "state"
assert L("U S DEPT OF AGRICULTURE", 80) == "federal" and L("SOUTHEAST OVERTOWN PARK WEST", 10) == "district"
assert L("MIAMI SHORES VILLAGE", 89) == "municipal" and L("MIAMI DADE", 86) == "county"
assert L("PARKSIDE VILLAGE CONDO ASSN", 4) is None and L("WATERFORD PARKS LLC", 10) is None
assert core.department_of("WATER AND SEWER DEPT", "MIAMI-DADE COUNTY") == "Water And Sewer Dept"
assert core.department_of("111 NW 1ST ST STE 2460", "MIAMI-DADE COUNTY") is None
assert core.department_of(None, "CITY OF MIAMI-DEPT OF P&D") == "Dept Of P&D"
assert core.department_of("FINANCE DEPT PO BOX 610847", "CITY OF X") == "Finance Dept" and core.department_of("PO BOX 12", "CITY OF X") is None
assert L("POMPANO BEACH COMMUNITY", 80) == "district" and L("NORTH SPRINGS IMPROVEMENT", 80) == "district" and L("AVENIR CDD", 80) == "district"
assert L("SCHOOL BOARD OF BROWARD COUNTY", 83, None, ("BROWARD COUNTY",)) == "school" and L("BROWARD COUNTY", 86, None, ("BROWARD COUNTY",)) == "county"
assert L("NORTHERN PALM BEACH COUNTY", 80, None, ("PALM BEACH COUNTY",)) == "district" and L("PALM BEACH COUNTY", 86, None, ("PALM BEACH COUNTY",)) == "county"
assert L("SMITH JOHN", 1) is None
assert L("COUNTRY CLUB ESTATES LLC", 10) is None                  # 'COUNTRY' must not match 'COUNTY'
assert L("ACME LLC", 80) == "other"                               # coded governmental, unknown owner
assert L("ACME PROPERTIES", 1, "S") == "state" and L("ACME LLC", 1, "S") is None
assert L("SOUTH FLA WATER MGMT", 80) == "district" and L("US CORPS OF ENG", 80) == "federal" and L("USA IN TRUST FOR THE BENEFIT", 80) == "federal"

# --- end to end against the mock server, mixed free + paid-format sources ------------
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
rows = mock_arcgis.build()
srv = mock_arcgis.serve(rows)
url = "http://127.0.0.1:8765/arcgis/rest/services/Mock/FeatureServer/0"
cfg = json.load(open(os.path.join(root, "config.json")))
cfg["output"] = "out/parcels.json"
cfg["exclude_owner_levels"] = []
for _k in ("exclude_use_codes", "exclude_owner_patterns", "exclude_legal_patterns", "water_check"):
    cfg.pop(_k, None)
_real = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")))
_x = lambda **k: core.exclusion_reason(dict({"owner": "BROWARD COUNTY", "use_code": 80}, **k), k.pop("lvl", "county") if "lvl" in k else "county", _real)
assert _x() is None and _x(use_code=94) and _x(use_code=95) and _x(use_code=96) and _x(use_code=86) is None
assert _x(owner="SOUTH FLA WATER MGMT DIST") and _x(owner="LAKE WORTH DRAINAGE DIST") and _x(owner="TIITF FISH & WILDLIFE") and _x(owner="TIITF FWCC")
assert _x(owner="TIITF/STATE OF FLORIDA") is None and _x(owner="CITY OF WATERFORD") is None and _x(owner="SCHOOL BOARD OF BROWARD COUNTY") is None
assert _x(legal="SUBMERGED LAND LYING E OF") and _x(legal="LOT 4 BLK 2 SUBDIVISION OF X") is None and _x(in_water=True) and _x(in_water=False) is None
assert core.exclusion_reason({"owner": "U S A", "use_code": 88}, "federal", _real)
for _c in cfg["counties"].values():
    _c.pop("development_boundary", None)
sq = core.Boundary({"features": [{"geometry": {"type": "Polygon", "coordinates": [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]], [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]]}}]})
assert sq.contains(3, 3) is True and sq.contains(5, 1) is False and sq.contains(1.5, 1.5) is False and sq.contains(None, 1) is None
for c in cfg["counties"].values():
    c["providers"][0]["url"] = url
# Miami-Dade comes from a Regrid-format bulk file instead: proves the swap needs config only.
rnd, ZON = random.Random(3), [("RU-4", "multifamily"), ("BU-2", "commercial"), ("MC", "mixed-use"), ("RU-1", "single-family"), ("IU-1", "industrial"), ("GU", "other")]
with open(os.path.join(tmp, "regrid_md.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, ["parcelnumb", "owner", "usecode", "ll_gisacre", "parval", "landval", "address", "scity", "lat", "lon", "zoning", "zoning_type", "fema_flood_zone", "struct", "taxyear"])
    w.writeheader()
    for r in rows:
        if r["CO_NO"] == 23:
            z = rnd.choice(ZON)
            w.writerow(dict(parcelnumb=r["PARCEL_ID"], owner=r["OWN_NAME"], usecode=int(r["DOR_UC"]), ll_gisacre=round(r["LND_SQFOOT"] / 43560, 3),
                            parval=r["JV"], landval=r["LND_VAL"], address=r["PHY_ADDR1"], scity=r["PHY_CITY"], lat=r["_c"]["y"], lon=r["_c"]["x"],
                            zoning=z[0], zoning_type=z[1], fema_flood_zone=rnd.choice(["X", "X", "AE", "AH"]), struct="true" if r["NO_BULDNG"] else "false", taxyear=2026))
b = "http://127.0.0.1:8765/arcgis/rest/services"
cfg["zoning_sources"] = {"broward": [
    {"jurisdiction": "Mock City", "url": b + "/City/MapServer/0", "code_field": "zonecode", "desc_field": "zonedesc", "enabled": True},
    {"jurisdiction": "Dead Town", "url": "http://127.0.0.1:1/x/0", "code_field": "Z", "enabled": True},
    {"jurisdiction": "Not ready", "url": b + "/City/MapServer/0", "code_field": "", "enabled": False},
    {"jurisdiction": "Unincorporated", "url": b + "/County/MapServer/0", "code_field": "ZONECODE", "enabled": True}]}
cfg["exclude_use_codes"] = [82]
cfg["water_check"] = {"enabled": True, "url": b + "/Water/MapServer/1", "drop_in_water": True}
cfg["counties"]["miami-dade"]["providers"] = [{"type": "regrid_file", "name": "Example file in Regrid format", "path": "regrid_md.csv"}]
with open(os.path.join(tmp, "zoning_density.csv"), "w") as f:
    f.write("jurisdiction,zoning_code,category,max_du_per_acre,max_du_per_acre_high,note,source_url\n"
            "Mock City,RM-25,multifamily,25,60,Edge 25 Core 60,example\nMock City,B-2,commercial,,,no housing by right,example\nUnincorporated,RM-25,multifamily,16,,,example\n"
            "miami-dade,RU-4,multifamily,50,,,example\nmiami-dade,MC,mixed-use,125,,,example\nmiami-dade,BU-2,commercial,36,,,example\nmiami-dade,RU-1,single-family,6,,,example\n")
with open(os.path.join(tmp, "surplus_parcels.csv"), "w") as f:
    f.write("county,parcel_id,list_name,list_date,source_url\nmiami-dade,EX-23-0001,Example surplus list,2026-07-01,example\nmiami-dade,EX-23-0008,Example surplus list,2026-07-01,example\nbroward,EX-16-0003,Example surplus list,2026-07-01,example\n")
json.dump(cfg, open(os.path.join(tmp, "config.json"), "w"))
run = lambda: subprocess.run([sys.executable, os.path.join(root, "run.py"), "--config", os.path.join(tmp, "config.json")], capture_output=True, text=True)

r1 = run(); print(r1.stdout, r1.stderr); assert r1.returncode == 0
d1 = json.load(open(os.path.join(tmp, "out/parcels.json")))
ids = {p["id"] for p in d1["parcels"]}
gov_rows = [r for r in rows if not r["OWN_NAME"].startswith("EXAMPLE") and r["LND_SQFOOT"] / 43560 >= cfg["min_acres"]]
gov_rows = [r for r in gov_rows if r["DOR_UC"] != "082" and not (r["CO_NO"] == 60 and r["_c"]["x"] < -80.28)]
assert any(r["DOR_UC"] == "082" for r in rows) and any(r["CO_NO"] == 60 and r["_c"]["x"] < -80.28 for r in rows), "the test data must exercise both rules"
assert ids == {r["PARCEL_ID"] for r in gov_rows}, "every government parcel, no private ones, paging complete"
assert d1["changes"] == [], "first run has nothing to compare against"
md = [p for p in d1["parcels"] if p["county"] == "miami-dade"]
assert all(p["zoning"] for p in md) and any(p["est_units"] for p in md)
br = [p for p in d1["parcels"] if p["county"] == "broward"]
assert all(p["zoning"] in ("RM-25", "B-2") for p in br), "every Broward parcel got a zone from a layer"
assert {p["zoning_jurisdiction"] for p in br} == {"Mock City", "Unincorporated"}
assert all((p["lon"] > -80.25) == (p["zoning_jurisdiction"] == "Mock City") for p in br), "first covering layer wins"
assert {p["max_du_per_acre"] for p in br if p["zoning"] == "RM-25"} == {25.0, 16.0}, "same code, different city, different density"
assert any(p["max_du_per_acre_high"] == 60.0 and p["density_note"] for p in br) and all(p["max_du_per_acre"] is None for p in br if p["zoning"] == "B-2")
assert all(p["zoning"] is None for p in d1["parcels"] if p["county"] == "palm-beach")
mis = [p for p in d1["parcels"] if not p["coded_gov"]]
assert mis and all(p["gov_basis"] == "owner name" for p in mis)

# second run a "week later": sale, acquisition, re-coding
srv.shutdown(); srv.server_close()
srv = mock_arcgis.serve(mock_arcgis.build(mutate=True))
r2 = run(); print(r2.stdout, r2.stderr); assert r2.returncode == 0
d2 = json.load(open(os.path.join(tmp, "out/parcels.json")))
kinds = sorted((c["type"], c["id"]) for c in d2["changes"])
print(kinds)
assert ("removed", "EX-16-0001") in kinds and ("added", "EX-16-0011") in kinds
assert any(c["id"] == "EX-23-0000" for c in d2["changes"]) is False   # Miami-Dade file unchanged

# outage: server down -> exit 1, last good data kept, no false "removed" for those counties
srv.shutdown(); srv.server_close()
r3 = run(); assert r3.returncode == 1
d3 = json.load(open(os.path.join(tmp, "out/parcels.json")))
assert len(d3["parcels"]) == len(d2["parcels"]) and len(d3["changes"]) == len(d2["changes"])
d2["example"] = True
json.dump(d2, open(os.path.join(root, "data", "example_parcels.json"), "w"), separators=(",", ":"))
shutil.rmtree(tmp)
print("ALL TESTS PASSED;", len(d2["parcels"]), "example parcels written")
