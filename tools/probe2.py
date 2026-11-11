"""Fetch county and city boundaries from the Census Bureau's TIGERweb service and print them (compact) to the log."""
import json, urllib.parse, urllib.request
B = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb"
def get(u, p):
    req = urllib.request.Request(u + "?" + urllib.parse.urlencode(p), headers={"User-Agent": "Mozilla/5.0 govland-tracker"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())
def layer(svc, name):
    m = get("%s/%s/MapServer" % (B, svc), {"f": "json"})
    names = [(l["id"], l["name"]) for l in m["layers"]]
    hit = [i for i, n in names if n == name] or [i for i, n in names if n.endswith(name)]
    print("LAYERS", svc, names[:60]); return "%s/%s/MapServer/%d" % (B, svc, hit[0])
common = {"f": "geojson", "outSR": 4326, "geometryPrecision": 4}
c = get(layer("State_County", "Counties") + "/query", dict(common, where="STATE='12' AND COUNTY IN ('086','011','099','087','021','051','085','043','093')", outFields="NAME,BASENAME,COUNTY", maxAllowableOffset=0.0005))
print("COUNTIES_JSON " + json.dumps(c, separators=(",", ":")))
p = get(layer("Places_CouSub_ConCity_SubMCD", "Incorporated Places") + "/query", dict(common, where="STATE='12'", geometry="-80.9,25.1,-80.0,27.0", geometryType="esriGeometryEnvelope", inSR=4326, spatialRel="esriSpatialRelIntersects", outFields="NAME,BASENAME", maxAllowableOffset=0.0004))
print("PLACES_JSON " + json.dumps(p, separators=(",", ":")))
