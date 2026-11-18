"""
03_sentinel2_ndvi_baseline.py
=============================
Exploratory 10 m resolution multi-spectral habitat baseline using Sentinel-2
surface reflectance (ga_s2am_ard_3) from Digital Earth Australia (DEA).

Computes temporal median NDVI and classifies pixels into 4 discrete habitat
classes for agent-based movement simulations:
  0: Pond (NDVI < 0)
  1: Rock / Urban (0 <= NDVI < 0.2)
  2: Light Vegetation (0.2 <= NDVI < 0.5)
  3: Dense Vegetation (NDVI >= 0.5)
"""

import os
import stackstac
import pystac_client
import xarray as xr
import h5py
import rioxarray  # noqa: F401
import matplotlib.pyplot as plt

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
os.environ["AWS_NO_SIGN_REQUEST"] = "YES"
STAC_URL = "https://explorer.sandbox.dea.ga.gov.au/stac"
BBOX = [150.68, -33.72, 150.73, -33.67]
DATE_RANGE = "2023-11-01/2024-03-01"
MAX_CLOUD_COVER = 5


def main():
    catalog = pystac_client.Client.open(STAC_URL)
    search = catalog.search(
        collections=["ga_s2am_ard_3"],
        bbox=BBOX,
        datetime=DATE_RANGE,
    )

    items = [
        i for i in search.items()
        if i.properties.get("eo:cloud_cover", 100) < MAX_CLOUD_COVER
    ]

    if not items:
        print("No cloud-free Sentinel-2 scenes found for this period.")
        return

    print(f"Found {len(items)} clear scenes. Building 10 m Australian Albers (EPSG:3577) stack...")
    stack = stackstac.stack(
        items,
        bounds_latlon=BBOX,
        epsg=3577,
        assets=["nbart_red", "nbart_nir_1"],
    )

    median_stack = stack.median(dim="time").compute()

    # Normalized Difference Vegetation Index (NDVI)
    nir = median_stack.sel(band="nbart_nir_1")
    red = median_stack.sel(band="nbart_red")
    ndvi = (nir - red) / (nir + red)

    # Discrete 4-class habitat binning
    land_cat = xr.where(
        ndvi < 0, 0,
        xr.where(ndvi < 0.2, 1,
        xr.where(ndvi < 0.5, 2, 3))
    )

    # Export GeoTIFF & HDF5
    ndvi.rio.to_raster("landscape_10m_static.tif")

    with h5py.File("landscape_matrix.h5", "w") as f:
        f.create_dataset("ndvi", data=ndvi.values)
        f.create_dataset("category_id", data=land_cat.values)
        f.create_dataset("x", data=ndvi.x.values)
        f.create_dataset("y", data=ndvi.y.values)
        f.attrs["resolution"] = "10m"
        f.attrs["crs"] = "EPSG:3577"
        f.attrs["legend"] = "0:Pond, 1:Rock, 2:LightVeg, 3:DenseVeg"

    plt.figure(figsize=(10, 8), dpi=150)
    ndvi.plot.imshow(cmap="RdYlGn", vmin=-0.1, vmax=0.8)
    plt.title("Static Master Atlas: 10 m Sentinel-2 NDVI Baseline", fontsize=14)
    plt.tight_layout()
    plt.savefig("master_atlas_highres.png")
    plt.close()

    print("Saved landscape_10m_static.tif, landscape_matrix.h5, and master_atlas_highres.png.")


if __name__ == "__main__":
    main()
