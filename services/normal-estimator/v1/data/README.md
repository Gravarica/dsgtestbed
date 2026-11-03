# LiDAR scans

The scans are not in git. `just prepare normal-estimator v1` puts the first 60 scans into `fetched/scans/`. It
copies them from `pc-visualizer/v1` when that service already downloaded them, otherwise it downloads the
drive itself.

They are the KITTI raw recording `2011_09_26_drive_0001_sync` (`velodyne_points` only), the same scans that
`pc-visualizer v1` uses, published by KITTI at
`https://s3.eu-central-1.amazonaws.com/avg-kitti/raw_data/2011_09_26_drive_0001/2011_09_26_drive_0001_sync.zip`.
Each `.bin` file holds float32 values x, y, z, reflectance per point.

A full scan has about 120 000 points, too many to fit a plane around every point in the time one item may take.
Every worker therefore thins each scan once, when it starts: it keeps the points closer than `data_quality` metres
and of those one point per 0.3 m voxel. The normals are estimated on these thinned scans, the ground included.

KITTI data is licensed CC BY-NC-SA 3.0: research use, not commercial, credit the KITTI authors
(Geiger, Lenz, Stiller, Urtasun: Vision meets Robotics: The KITTI Dataset, IJRR 2013).
