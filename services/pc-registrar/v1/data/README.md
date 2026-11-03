# LiDAR scans

The scans are not in git. `just prepare pc-registrar v1` puts the first 61 scans into `fetched/scans/`. It
copies them from `pc-visualizer/v1` when that service already downloaded them, otherwise it downloads the
drive itself. The scans are consecutive, 0.1 s apart: sample `i` is the pair (scan `i + 1`, scan `i`), so 61
scans give 60 samples and the service keeps nothing between items.

They are the KITTI raw recording `2011_09_26_drive_0001_sync` (`velodyne_points` only), the same scans that
`pc-visualizer v1` uses, published by KITTI at
`https://s3.eu-central-1.amazonaws.com/avg-kitti/raw_data/2011_09_26_drive_0001/2011_09_26_drive_0001_sync.zip`.
Each `.bin` file holds float32 values x, y, z, reflectance per point.

Before any item is processed, every scan is cut to the largest distance (`data_quality`, metres), its ground
points (z below -1.4 m) are dropped, and it is thinned to one point per voxel of a fixed grid
(`VOXEL_SIZE_METERS` in `service.py`). The alignment itself, point-to-point ICP with exactly `iterations`
rounds, runs per item.

KITTI data is licensed CC BY-NC-SA 3.0: research use, not commercial, credit the KITTI authors
(Geiger, Lenz, Stiller, Urtasun: Vision meets Robotics: The KITTI Dataset, IJRR 2013).
