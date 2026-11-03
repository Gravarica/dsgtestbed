# LiDAR scans

The scans are not in git. `just prepare pc-encoder v1` puts the first 60 scans into `fetched/scans/`. It
copies them from `pc-visualizer/v1` when that service already downloaded them, otherwise it downloads the
drive itself.

They are the KITTI raw recording `2011_09_26_drive_0001_sync` (`velodyne_points` only), the same scans that
`pc-visualizer v1` uses, published by KITTI at
`https://s3.eu-central-1.amazonaws.com/avg-kitti/raw_data/2011_09_26_drive_0001/2011_09_26_drive_0001_sync.zip`.
Each `.bin` file holds float32 values x, y, z, reflectance per point.

KITTI data is licensed CC BY-NC-SA 3.0: research use, not commercial, credit the KITTI authors
(Geiger, Lenz, Stiller, Urtasun: Vision meets Robotics: The KITTI Dataset, IJRR 2013).
