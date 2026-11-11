import json, urllib.parse, urllib.request
def get(u, p):
    req = urllib.request.Request(u + "?" + urllib.parse.urlencode(p), headers={"User-Agent": "govland-tracker/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())
T = [("MIAMI", "https://gis.miami.gov/gis/rest/services/Zoning/ZoningMiami21/MapServer/5", "M21_ZONE,Transect_Desc,Transect,Map_Code,Bldg_Height,Intensity",
      [(-80.1918, 25.7743), (-80.2400, 25.7700), (-80.2000, 25.8100), (-80.2550, 25.7300), (-80.1900, 25.7900)]),
     ("GABLES", "https://cgportal.coralgables.com/egswa/rest/services/EnerGov/DisplayMap/MapServer/21", "Zone,Zone_Desc",
      [(-80.2590, 25.7500), (-80.2684, 25.7215), (-80.2600, 25.7480), (-80.2780, 25.7400)])]
for tag, u, f, pts in T:
    for lon, lat in pts:
        try:
            d = get(u + "/query", {"geometry": "%s,%s" % (lon, lat), "geometryType": "esriGeometryPoint", "inSR": 4326, "spatialRel": "esriSpatialRelIntersects", "outFields": f, "returnGeometry": "false", "f": "json"})
            print(tag, lon, lat, json.dumps([x["attributes"] for x in d.get("features", [])])[:400] if "error" not in d else d["error"])
        except Exception as e:
            print(tag, "FAIL", e)
    try:
        d = get(u + "/query", {"where": "1=1", "outFields": f, "returnGeometry": "false", "returnDistinctValues": "true", "f": "json"})
        vals = sorted({json.dumps(x["attributes"], sort_keys=True) for x in d.get("features", [])})
        print(tag, "DISTINCT", len(vals)); [print(tag, "VAL", v[:300]) for v in vals[:120]]
    except Exception as e:
        print(tag, "DISTINCT FAIL", e)
