# LiDAR scans

The scans are not in git. `just prepare pc-visualizer v1` downloads them.

They are the KITTI raw recording `2011_09_26_drive_0001_sync`, the same one elastic-workbench uses (its
`.gitignore` names the folder, its code opens date `2011_09_26` drive `0001`). KITTI publishes the drive as one
zip file; only the `velodyne_points` part is kept:

```
data/2011_09_26/2011_09_26_drive_0001_sync/velodyne_points/data/0000000000.bin ...
```

KITTI data is licensed CC BY-NC-SA 3.0: research use, not commercial, credit the KITTI authors.
