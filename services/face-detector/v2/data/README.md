# Sample data

`pedestrian.jpg` and `CV_Video.mp4` are copied from `face-detector/v1`, which took them from elastic-workbench
(iot_services/CvAnalyzer/data). The picture shows twelve people facing the camera; their face boxes are the known
answer of the proof. The video shows a street scene. Sample 0 is the picture, samples 1 to 29 are video frames.

The model is not in git. `prepare.sh` fetches it into `fetched/models/` and checks its SHA-256:

- `face_detection_yunet_2023mar.onnx`, YuNet, from the OpenCV Zoo
  (https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet), MIT licence.

`model_size` 1 runs YuNet once on the frame at the height `data_quality`. `model_size` 2 runs it on that frame and
on the same frame enlarged to twice its height, and merges the two sets of faces; it finds smaller faces and costs
about five times as much.
