import json, urllib.parse, urllib.request
def get(u, p):
    req = urllib.request.Request(u + "?" + urllib.parse.urlencode(p), headers={"User-Agent": "Mozilla/5.0 govland-tracker"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())
for tag, u in (("UDBPOLY", "https://gisfs.miamidade.gov/mdarcgis/rest/services/MD_PA_PropertySearch/MapServer/17"),
               ("UDBLINE", "https://gisweb.miamidade.gov/arcgis/rest/services/Wasd/UrbanDevelopmentBoundary_1_v1/MapServer/0")):
    try:
        m = get(u, {"f": "json"})
        print(tag + "_META", json.dumps({k: m.get(k) for k in ("name", "geometryType", "description", "editingInfo", "copyrightText")})[:900])
        d = get(u + "/query", {"where": "1=1", "outFields": "*", "outSR": 4326, "f": "geojson", "geometryPrecision": 5, "maxAllowableOffset": 0.0001})
        print(tag + "_PROPS", json.dumps([f["properties"] for f in d["features"]])[:600])
        print(tag + "_JSON " + json.dumps(d, separators=(",", ":")))
    except Exception as e:
        print(tag + "_FAIL", e)
