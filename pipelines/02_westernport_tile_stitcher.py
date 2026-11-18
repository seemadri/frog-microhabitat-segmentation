"""
02_westernport_tile_stitcher.py
===============================
Downloads free XYZ aerial imagery tiles for any bounding box in Victoria
(default: Western Port Bay) and stitches them into a georeferenced WGS84
GeoTIFF ready for Python/MATLAB habitat analysis.

Tile sources:
  - ESRI World Imagery : ~50 cm over Victoria/Western Port
  - Google Satellite   : ~50 cm fallback
"""

import math
import os
import io
import time
import numpy as np
import requests
from PIL import Image
import rasterio
from rasterio.transform import from_bounds
from rasterio.crs import CRS

# ─────────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────────
BBOX = {
    "west":  145.200,
    "south": -38.530,
    "east":  145.215,
    "north": -38.515,
}

# Zoom level: 17 (~1.2 m/px), 18 (~60 cm/px), 19 (~30 cm/px)
ZOOM = 18
OUTPUT_FILE = "westernport_aerial.tif"

TILE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
TILE_DELAY = 0.05


def lat_lon_to_tile(lat, lon, zoom):
    """Convert WGS84 lat/lon to XYZ slippy-tile indices at given zoom."""
    lat_r = math.radians(lat)
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n)
    return x, y


def tile_to_lat_lon(x, y, zoom):
    """Convert tile XY indices to top-left corner lat/lon."""
    n = 2 ** zoom
    lon = x / n * 360.0 - 180.0
    lat_r = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    lat = math.degrees(lat_r)
    return lat, lon


def download_tile(x, y, z, url_template, retries=3):
    """Download a single 256x256 tile as a PIL Image."""
    url = url_template.replace("{x}", str(x)).replace("{y}", str(y)).replace("{z}", str(z))
    headers = {"User-Agent": "Mozilla/5.0 (academic research)"}
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                return Image.open(io.BytesIO(r.content)).convert("RGB")
            print(f"  HTTP {r.status_code} for tile ({x},{y}) — retrying...")
        except Exception as e:
            print(f"  Error {e} for tile ({x},{y}) — retrying ({attempt + 1}/{retries})...")
        time.sleep(1)
    return None


def main():
    west, south, east, north = BBOX["west"], BBOX["south"], BBOX["east"], BBOX["north"]

    x_min, y_min = lat_lon_to_tile(north, west, ZOOM)
    x_max, y_max = lat_lon_to_tile(south, east, ZOOM)

    tile_size = 256
    canvas_w = (x_max - x_min + 1) * tile_size
    canvas_h = (y_max - y_min + 1) * tile_size

    lat_mid = (north + south) / 2
    meters_per_px = 156543.03392 * math.cos(math.radians(lat_mid)) / (2 ** ZOOM)
    print(f"Zoom {ZOOM} | Canvas: {canvas_w}x{canvas_h} px | Approx res: {meters_per_px:.2f} m/px")

    canvas = Image.new("RGB", (canvas_w, canvas_h), (0, 0, 0))
    failed = 0

    for i, x in enumerate(range(x_min, x_max + 1)):
        for j, y in enumerate(range(y_min, y_max + 1)):
            tile_img = download_tile(x, y, ZOOM, TILE_URL)
            if tile_img is not None:
                canvas.paste(tile_img, (i * tile_size, j * tile_size))
            else:
                failed += 1
            time.sleep(TILE_DELAY)

    if failed > 0:
        print(f"Warning: {failed} tiles failed to download.")

    lat_nw, lon_nw = tile_to_lat_lon(x_min, y_min, ZOOM)
    lat_se, lon_se = tile_to_lat_lon(x_max + 1, y_max + 1, ZOOM)

    img_bands = np.moveaxis(np.array(canvas), -1, 0)
    transform = from_bounds(lon_nw, lat_se, lon_se, lat_nw, canvas_w, canvas_h)

    with rasterio.open(
        OUTPUT_FILE,
        "w",
        driver="GTiff",
        height=canvas_h,
        width=canvas_w,
        count=3,
        dtype=np.uint8,
        crs=CRS.from_epsg(4326),
        transform=transform,
        compress="lzw",
    ) as dst:
        dst.write(img_bands[0], 1)
        dst.write(img_bands[1], 2)
        dst.write(img_bands[2], 3)
        dst.update_tags(1, name="Red")
        dst.update_tags(2, name="Green")
        dst.update_tags(3, name="Blue")

    print(f"Saved {OUTPUT_FILE} ({os.path.getsize(OUTPUT_FILE)/1e6:.1f} MB).")


if __name__ == "__main__":
    main()
