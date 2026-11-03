# Data of cv-analyzer v2

- `CV_Video.mp4`: the sample video of cv-analyzer v1 (from elastic-workbench, `CvAnalyzer_Yolo`). The first frame is
  skipped and the next 60 frames are the samples.
- `models/yolov10{n,s,m,l}.onnx` (not in git): YOLOv10 nano, small, medium and large, `model_size` 1 to 4. `prepare.sh`
  copies them from `cv-analyzer/v1/models` when they are there, and otherwise exports them with the ultralytics Docker
  image (`dynamic=True end2end=True`), so one file per model runs at every frame size. YOLOv10 and the ultralytics
  exporter are licensed AGPL-3.0.

## What `data_quality` means

`data_quality` is the frame height in pixels, 160 to 640. YOLO needs a height and a width that are divisible by 32, so
the service rounds the asked height to the nearest multiple of 32 (300 becomes 288, 310 becomes 320) and sets the width
to the multiple of 32 that keeps the shape of the frame best. The frames are resized once per worker, before any item;
an item is one detection on a resized frame. Boxes are returned in the pixels of the resized frame.
