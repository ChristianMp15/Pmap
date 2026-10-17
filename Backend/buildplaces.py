"""Turn an OpenStreetMap export (export.geojson) into places.json for the PinkMap app.

Usage:  python build_places.py                      (reads export.geojson, writes places.json)
        python build_places.py my_export.geojson    (use another file)

Each place becomes [id, name, latitude, longitude, kind].
Polygons (parks, campuses) are reduced to their center point.
Run it again any time you add more places to the export.
"""
import json
import sys
from collections import Counter

SRC = sys.argv[1] if len(sys.argv) > 1 else "export.geojson"
OUT = "places.json"
# Rough box around greater Houston; anything outside is skipped so a stray point can't break the map.
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = 29.3, 30.3, -96.2, -94.8


def ring_center(ring):
    """Area-weighted center of one polygon ring (falls back to the average of the points)."""
    area = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        cross = x1 * y2 - x2 * y1
        area += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(area) < 1e-12:
        return sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)
    return cx / (3 * area), cy / (3 * area)


def ring_area(ring):
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1])) / 2)


def center_of(geom):
    t = geom["type"]
    if t == "Point":
        return geom["coordinates"][0], geom["coordinates"][1]
    if t == "Polygon":
        return ring_center([tuple(p[:2]) for p in geom["coordinates"][0]])
    if t == "MultiPolygon":  # use the biggest piece
        biggest = max(geom["coordinates"], key=lambda poly: ring_area([tuple(p[:2]) for p in poly[0]]))
        return ring_center([tuple(p[:2]) for p in biggest[0]])
    return None


def kind_of(p):
    for key in ("leisure", "amenity", "tourism", "building"):
        if p.get(key):
            return p[key]
    return "place"


def main():
    with open(SRC, encoding="utf-8") as f:
        features = json.load(f)["features"]

    rows, skipped = [], Counter()
    for ft in features:
        p = ft["properties"]
        name = (p.get("name") or "").strip()
        if not name:  # no name means nobody can search for it, so skip it
            skipped["no name"] += 1
            continue
        c = center_of(ft["geometry"])
        if not c:
            skipped["odd shape"] += 1
            continue
        lon, lat = c
        if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
            skipped["outside Houston"] += 1
            continue
        street = " ".join(x for x in [p.get("addr:housenumber"), p.get("addr:street")] if x)
        rows.append({"id": p.get("@id", ""), "name": name, "street": street,
                     "lat": round(lat, 6), "lon": round(lon, 6), "kind": kind_of(p)})

    # Same name used more than once (e.g. two "Memorial Park" entries): add the street, else a number.
    counts = Counter(r["name"].lower() for r in rows)
    seen = Counter()
    for r in rows:
        if counts[r["name"].lower()] > 1:
            seen[r["name"].lower()] += 1
            r["name"] += f" ({r['street']})" if r["street"] else f" (#{seen[r['name'].lower()]})"

    out = [[r["id"], r["name"], r["lat"], r["lon"], r["kind"]] for r in sorted(rows, key=lambda r: r["name"].lower())]
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Wrote {len(out)} places to {OUT}. Skipped: {dict(skipped)}")
    print("By kind:", dict(Counter(r["kind"] for r in rows).most_common()))


if __name__ == "__main__":
    main()