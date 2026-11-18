# Locator map sources

`locator.json` holds the small locator maps on the country and region
briefs and social cards (`scripts/locator_map.py`).

| file | source | licence | notice |
|---|---|---|---|
| locator.json | [Natural Earth](https://www.naturalearthdata.com/) 1:50m Cultural Vectors, Admin 0 – Countries, v5.1.2 ([GeoJSON on GitHub](https://github.com/nvkelso/natural-earth-vector/blob/v5.1.2/geojson/ne_50m_admin_0_countries.geojson), sha256 `3e458fc036ad0a66411f2c1e6cac49c5d7bfb81cb1123bc513b22511a2b7fdeb`) | Public domain ([terms of use](https://www.naturalearthdata.com/about/terms-of-use/)) | Projected, clipped and simplified offline by `scripts/build_locator_maps.py`; Antarctica left out. Credit is not required; we give it anyway. |

Boundaries are Natural Earth's default (de facto) view. A locator map
shows where a market is; it says nothing about borders or recognition.

Rebuild (not run in CI; pure Python, no GIS libraries):

    curl -L -o ne_50m.geojson \
      https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_50m_admin_0_countries.geojson
    python scripts/build_locator_maps.py ne_50m.geojson
