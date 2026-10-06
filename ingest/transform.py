
import h3
import pandas as pd

TARGET_RESOLUTIONS = (6, 7, 8, 9)

def transform_events_to_cells(valid_df: pd.DataFrame) -> pd.DataFrame:
    """
    Transforms validated raw events into multi-resolution privacy-preserving cell rollups.
    Stage 2:
      bucket = floor(ts to hour, UTC)
      cell9  = h3.latlng_to_cell(lat, lng, 9)
      DROP lat, lng (privacy boundary)
      group by (cell9, bucket, category) -> cnt
    Stage 3:
      For res in (6, 7, 8, 9):
        Map unique cell9 to parent at res
        Re-aggregate to sum(cnt)
        Attach lat_c, lng_c of cell center
    """
    if valid_df.empty:
        return pd.DataFrame(columns=["res", "h3", "bucket", "category", "cnt", "lat_c", "lng_c"])

    # Floor timestamp to hour
    bucket_series = valid_df["ts"].dt.floor("h")

    # Compute H3 resolution 9 for each event
    lats = valid_df["lat"].to_numpy()
    lngs = valid_df["lng"].to_numpy()

    # Vectorized / list comprehension conversion to res 9
    cell9_list = [h3.latlng_to_cell(lat, lng, 9) for lat, lng in zip(lats, lngs)]

    # PRIVACY BOUNDARY: Create interim DataFrame WITHOUT lat, lng
    interim_df = pd.DataFrame({
        "cell9": cell9_list,
        "bucket": bucket_series.values,
        "category": valid_df["category"].values
    })
    # Explicitly ensure no raw coords remain
    del lats, lngs

    # Aggregate base resolution 9 counts
    base_agg = (
        interim_df.groupby(["cell9", "bucket", "category"], as_index=False)
        .size()
        .rename(columns={"size": "cnt"})
    )

    if base_agg.empty:
        return pd.DataFrame(columns=["res", "h3", "bucket", "category", "cnt", "lat_c", "lng_c"])

    unique_cell9 = base_agg["cell9"].unique()

    # Stage 3: Multi-resolution expansion via unique parent mappings
    expanded_frames: list[pd.DataFrame] = []

    # Cache cell centers
    center_cache = {}

    def get_center(cell: str):
        if cell not in center_cache:
            lat, lng = h3.cell_to_latlng(cell)
            center_cache[cell] = (round(lat, 6), round(lng, 6))
        return center_cache[cell]

    for res in TARGET_RESOLUTIONS:
        if res == 9:
            parent_map = {c: c for c in unique_cell9}
        else:
            parent_map = {c: h3.cell_to_parent(c, res) for c in unique_cell9}

        res_df = base_agg.copy()
        res_df["h3"] = res_df["cell9"].map(parent_map)

        # Re-aggregate counts at resolution 'res'
        agg_res = (
            res_df.groupby(["h3", "bucket", "category"], as_index=False)["cnt"]
            .sum()
        )
        agg_res["res"] = res

        # Attach cell center
        centers = [get_center(c) for c in agg_res["h3"]]
        agg_res["lat_c"] = [c[0] for c in centers]
        agg_res["lng_c"] = [c[1] for c in centers]

        expanded_frames.append(agg_res[["res", "h3", "bucket", "category", "cnt", "lat_c", "lng_c"]])

    final_df = pd.concat(expanded_frames, ignore_index=True)
    return final_df
