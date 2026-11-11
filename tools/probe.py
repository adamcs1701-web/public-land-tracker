"""Diagnostic: find which query parameter a layer rejects. Prints only schema facts and one sample row."""
import json, sys, urllib.parse, urllib.request
URL = sys.argv[1].rstrip("/")
def get(path, params):
    u = URL + path + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "govland-tracker/0.1"}), timeout=120) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}
m = get("", {"f": "json"})
ft = {f["name"]: f["type"] for f in m.get("fields", [])}
print("fields of interest:", {k: ft.get(k) for k in ["CO_NO", "DOR_UC", "PARCEL_ID", "OWN_NAME", "LND_SQFOOT", "NO_BULDNG", "JV", "LND_VAL", "PHY_ADDR1", "PHY_CITY", "PUBLIC_LND", "ASMNT_YR", "OBJECTID"]})
print("objectIdField:", m.get("objectIdField"), "| maxRecordCount:", m.get("maxRecordCount"), "| pagination:", (m.get("advancedQueryCapabilities") or {}).get("supportsPagination"), "| centroid:", (m.get("advancedQueryCapabilities") or {}).get("supportsReturningGeometryCentroid"))
base = {"f": "json", "returnGeometry": "false", "resultRecordCount": 2}
tests = [
 ("co only, int", {"where": "CO_NO=23", "outFields": "PARCEL_ID,DOR_UC,CO_NO"}),
 ("co only, str", {"where": "CO_NO='23'", "outFields": "PARCEL_ID,DOR_UC,CO_NO"}),
 ("uc str 3", {"where": "CO_NO=23 AND DOR_UC='080'", "outFields": "PARCEL_ID,DOR_UC"}),
 ("uc str 2", {"where": "CO_NO=23 AND DOR_UC='80'", "outFields": "PARCEL_ID,DOR_UC"}),
 ("uc int", {"where": "CO_NO=23 AND DOR_UC=80", "outFields": "PARCEL_ID,DOR_UC"}),
 ("uc IN str", {"where": "CO_NO=23 AND DOR_UC IN ('080','086')", "outFields": "PARCEL_ID,DOR_UC"}),
 ("uc IN int", {"where": "CO_NO=23 AND DOR_UC IN (80,86)", "outFields": "PARCEL_ID,DOR_UC"}),
 ("all outFields", {"where": "CO_NO=23", "outFields": "PARCEL_ID,CO_NO,OWN_NAME,DOR_UC,LND_SQFOOT,NO_BULDNG,JV,LND_VAL,PHY_ADDR1,PHY_CITY,PUBLIC_LND,ASMNT_YR"}),
 ("centroid", {"where": "CO_NO=23", "outFields": "PARCEL_ID", "returnCentroid": "true", "outSR": 4326}),
 ("orderBy+offset", {"where": "CO_NO=23", "outFields": "PARCEL_ID", "orderByFields": "OBJECTID", "resultOffset": 0}),
 ("like", {"where": "CO_NO=23 AND OWN_NAME LIKE '%CITY OF %'", "outFields": "PARCEL_ID,OWN_NAME,DOR_UC"}),
 ("geometry", {"where": "CO_NO=23", "outFields": "PARCEL_ID", "returnGeometry": "true", "outSR": 4326, "resultRecordCount": 1}),
]
for name, p in tests:
    d = get("/query", dict(base, **p))
    if "error" in d:
        print("FAIL %-16s %s" % (name, str(d["error"])[:160]))
    else:
        f = d.get("features", [])
        s = json.dumps(f[0])[:260] if f else "no rows"
        print("OK   %-16s n=%d %s" % (name, len(f), s))
for name, w in [("gov int", "CO_NO=23 AND DOR_UC IN (80,81,82,83,84,85,86,87,88,89)"), ("gov str3", "CO_NO=23 AND DOR_UC IN ('080','081','082','083','084','085','086','087','088','089')"), ("gov str2", "CO_NO=23 AND DOR_UC IN ('80','81','82','83','84','85','86','87','88','89')"), ("public_lnd", "CO_NO=23 AND PUBLIC_LND IS NOT NULL AND PUBLIC_LND<>' '")]:
    print("COUNT %-10s" % name, get("/query", {"f": "json", "where": w, "returnCountOnly": "true"}))
