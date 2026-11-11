import json, sys, time, urllib.parse, urllib.request
URL = sys.argv[1].rstrip("/")
def get(params, post=False):
    t = time.time()
    try:
        data = urllib.parse.urlencode(params)
        req = urllib.request.Request(URL + "/query" + ("" if post else "?" + data), data=data.encode() if post else None, headers={"User-Agent": "Mozilla/5.0 govland-tracker"})
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.loads(r.read().decode())
    except Exception as e:
        d = {"error": str(e)}
    return d, time.time() - t
def show(name, p, post=False):
    d, dt = get(dict({"f": "json"}, **p), post)
    if "error" in d: print("FAIL %-22s %5.1fs %s" % (name, dt, str(d["error"])[:110]))
    elif "count" in d: print("OK   %-22s %5.1fs count=%s" % (name, dt, d["count"]))
    else:
        f = d.get("features", []); print("OK   %-22s %5.1fs n=%d xfer=%s %s" % (name, dt, len(f), d.get("exceededTransferLimit"), json.dumps(f[0])[:230] if f else ""))
GOV = "DOR_UC IN ('080','081','082','083','084','085','086','087','088','089','090')"
ENV = {"geometry": "-80.9,25.1,-80.1,25.98", "geometryType": "esriGeometryEnvelope", "inSR": 4326, "spatialRel": "esriSpatialRelIntersects"}
O = {"returnGeometry": "false", "resultRecordCount": 3}
for i in range(3): show("count co=23 #%d" % i, {"where": "CO_NO=23", "returnCountOnly": "true"})
show("rows co=23", dict(O, where="CO_NO=23", outFields="PARCEL_ID,DOR_UC"))
show("rows co=23 POST", dict(O, where="CO_NO=23", outFields="PARCEL_ID,DOR_UC"), post=True)
show("rows gov only", dict(O, where=GOV, outFields="PARCEL_ID,DOR_UC,CO_NO"))
show("rows oid range", dict(O, where="OBJECTID BETWEEN 1 AND 50000 AND " + GOV, outFields="PARCEL_ID,DOR_UC,CO_NO,OWN_NAME"))
show("count oid range", {"where": "OBJECTID BETWEEN 1 AND 50000 AND " + GOV, "returnCountOnly": "true"})
show("oid range big page", dict(where="OBJECTID BETWEEN 1 AND 200000 AND " + GOV, outFields="PARCEL_ID,CO_NO,OWN_NAME,DOR_UC,LND_SQFOOT,NO_BULDNG,JV,LND_VAL,PHY_ADDR1,PHY_CITY,PUBLIC_LND,ASMNT_YR", returnGeometry="false", returnCentroid="true", outSR=4326))
show("envelope + gov", dict(O, where=GOV, outFields="PARCEL_ID,DOR_UC,CO_NO", **ENV))
show("envelope + gov count", dict(where=GOV, returnCountOnly="true", **ENV))
show("envelope+gov+centroid", dict(O, where=GOV + " AND CO_NO=23", outFields="PARCEL_ID,CO_NO,OWN_NAME,DOR_UC,LND_SQFOOT", returnCentroid="true", outSR=4326, **ENV))
show("max oid", {"where": "1=1", "outStatistics": json.dumps([{"statisticType": "max", "onStatisticField": "OBJECTID", "outStatisticFieldName": "m"}])})
show("oid stats co=23", {"where": "CO_NO=23", "outStatistics": json.dumps([{"statisticType": "min", "onStatisticField": "OBJECTID", "outStatisticFieldName": "lo"}, {"statisticType": "max", "onStatisticField": "OBJECTID", "outStatisticFieldName": "hi"}])})
