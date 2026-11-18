"""
01_quail_island_rgb_gmm.py
==========================
Downloads high-resolution RGB aerial imagery (~0.88 m/px) over northern
Quail Island, Victoria, computes visible spectral indices (VARI and ExG),
segments pixels into 4 micro-habitat classes via a Gaussian Mixture Model
(GMM), applies a 3x3 modal denoising filter, and exports to HDF5 and PNG.

Reproduces the habitat extraction pipeline in Sections 2.4 & 3.4 (Figs. 4 & 10)
of Arroyo-Vazquez et al. (MATRIX Annals).
"""

import os
import requests
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.crs import CRS
from pyproj import Geod
from sklearn.mixture import GaussianMixture
from scipy import ndimage
import h5py
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap

# ─────────────────────────────────────────────
# 1. CONFIGURATION
# ─────────────────────────────────────────────
BBOX = {
    "west": 145.275,
    "south": -38.245,
    "east": 145.295,
    "north": -38.230,
}
IMG_WIDTH = 2000
IMG_HEIGHT = 2000

RAW_TIFF = "quail_island_esri.tif"
OUTPUT_H5 = "quail_habitat_matrix.h5"
OUTPUT_PNG = "quail_island_habitat_denoised.png"


def download_quail_island_imagery():
    """Fetch RGB imagery from ArcGIS World Imagery REST export endpoint."""
    export_url = (
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
        f"?bbox={BBOX['west']},{BBOX['south']},{BBOX['east']},{BBOX['north']}"
        f"&bboxSR=4326&size={IMG_WIDTH},{IMG_HEIGHT}&imageSR=4326&format=tiff&f=image"
    )
    print("Requesting high-resolution aerial imagery for Quail Island...")
    response = requests.get(export_url, timeout=60)
    response.raise_for_status()

    with open(RAW_TIFF, "wb") as f:
        f.write(response.content)

    # Ensure explicit WGS84 georeferencing metadata is attached
    with rasterio.open(RAW_TIFF) as src:
        img = src.read([1, 2, 3])

    transform = from_bounds(
        BBOX["west"], BBOX["south"], BBOX["east"], BBOX["north"],
        IMG_WIDTH, IMG_HEIGHT
    )
    with rasterio.open(
        RAW_TIFF,
        "w",
        driver="GTiff",
        height=IMG_HEIGHT,
        width=IMG_WIDTH,
        count=3,
        dtype=img.dtype,
        crs=CRS.from_epsg(4326),
        transform=transform,
    ) as dst:
        dst.write(img)

    # Compute true geodesic ground resolution
    geod = Geod(ellps="WGS84")
    _, _, dist_m = geod.inv(BBOX["west"], BBOX["south"], BBOX["east"], BBOX["south"])
    res_m = dist_m / IMG_WIDTH
    print(f"Saved {RAW_TIFF} ({os.path.getsize(RAW_TIFF)/1e6:.2f} MB) | Resolution: ~{res_m:.2f} m/px")
    return res_m


def classify_habitats(res_m):
    """Run 5D (RGB + VARI + ExG) GMM clustering and 3x3 modal denoising."""
    with rasterio.open(RAW_TIFF) as src:
        img = src.read([1, 2, 3])
        transform = src.transform

    r = img[0].astype(float)
    g = img[1].astype(float)
    b = img[2].astype(float)

    # Spectral feature engineering
    vari = (g - r) / (g + r - b + 1e-5)
    exg = 2.0 * g - r - b

    data_flat = img.reshape(3, -1).T
    features = np.column_stack([data_flat, vari.flatten(), exg.flatten()])

    # Unsupervised 4-component Gaussian Mixture Model
    print("Fitting 4-component Gaussian Mixture Model...")
    gmm = GaussianMixture(n_components=4, random_state=42)
    labels = gmm.fit_predict(features)
    raw_map = labels.reshape(img.shape[1], img.shape[2])

    # Map clusters to habitat IDs based on cluster spectral centroids:
    # 1: Sun-heated / Rock | 2: Light Veg | 3: Dense Veg | 4: Pond
    cluster_stats = []
    for cid in range(4):
        mask = labels == cid
        mean_vari = vari.flatten()[mask].mean()
        mean_exg = exg.flatten()[mask].mean()
        mean_brightness = data_flat[mask].mean()
        cluster_stats.append((cid, mean_vari, mean_exg, mean_brightness))

    # Pond has lowest ExG / darker water signature; Dense Veg has highest ExG;
    # Rock/bare substrate has highest brightness & lowest VARI among terrestrial classes
    by_exg = sorted(cluster_stats, key=lambda x: x[2])
    pond_cid = by_exg[0][0]
    dense_cid = by_exg[-1][0]
    remaining = [c for c in cluster_stats if c[0] not in (pond_cid, dense_cid)]
    by_vari = sorted(remaining, key=lambda x: x[1])
    rock_cid = by_vari[0][0]
    light_cid = by_vari[1][0]

    mapped = np.zeros_like(raw_map, dtype=np.uint8)
    mapped[raw_map == rock_cid] = 1
    mapped[raw_map == light_cid] = 2
    mapped[raw_map == dense_cid] = 3
    mapped[raw_map == pond_cid] = 4

    # 3x3 modal filter to remove salt-and-pepper noise
    print("Applying 3x3 spatial modal denoising filter...")
    denoised_map = ndimage.generic_filter(
        mapped,
        function=lambda x: np.bincount(x.astype(int)).argmax(),
        size=3,
    ).astype(np.uint8)

    # Visualization matching paper color palette
    custom_palette = [
        (0.52, 0.32, 0.18),  # 1: Sun-heated / Rock
        (0.72, 0.88, 0.28),  # 2: Light Vegetation
        (0.08, 0.45, 0.12),  # 3: Dense Vegetation
        (0.12, 0.42, 0.82),  # 4: Pond
    ]
    cmap_frog = ListedColormap(custom_palette)

    plt.figure(figsize=(10, 10))
    plt.imshow(denoised_map, cmap=cmap_frog, vmin=1, vmax=4)
    plt.title(f"Denoised Quail Island Habitat Map (~{res_m:.2f} m/px)")
    cbar = plt.colorbar(ticks=[1, 2, 3, 4], fraction=0.046, pad=0.04)
    cbar.ax.set_yticklabels(["Rock / Sun-heated", "Light Veg", "Dense Veg", "Pond"])
    plt.tight_layout()
    plt.savefig(OUTPUT_PNG, dpi=300)
    plt.close()

    # Export HDF5 for MATLAB / Python ABM ingestion
    with h5py.File(OUTPUT_H5, "w") as f:
        f.create_dataset("landscape", data=denoised_map, compression="gzip")
        f.attrs["resolution_m"] = round(res_m, 3)
        f.attrs["crs"] = "EPSG:4326"
        f.attrs["legend"] = "1:Rock/Sun-heated, 2:LightVeg, 3:DenseVeg, 4:Pond"
        f.attrs["transform"] = [
            transform.a, transform.b, transform.c,
            transform.d, transform.e, transform.f,
        ]

    print(f"Pipeline complete. Saved {OUTPUT_H5} and {OUTPUT_PNG}.")


if __name__ == "__main__":
    resolution = download_quail_island_imagery()
    classify_habitats(resolution)
