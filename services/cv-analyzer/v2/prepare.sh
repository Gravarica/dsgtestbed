set -e
cd "$(dirname "$0")"
mkdir -p models
for size in n s m l; do
  if [ ! -f models/yolov10$size.onnx ] && [ -f ../v1/models/yolov10$size.onnx ]; then
    cp ../v1/models/yolov10$size.onnx models/yolov10$size.onnx
  fi
done
if ls models/yolov10n.onnx models/yolov10s.onnx models/yolov10m.onnx models/yolov10l.onnx > /dev/null 2>&1; then
  echo "all four models are in models/"
  exit 0
fi
cd models
docker run --rm -v "$PWD":/models -w /models ultralytics/ultralytics@sha256:21a913ab8417fa73405ba5874ecbf05e42d41d564587f76786d5909460e98af6 sh -c "
  for size in n s m l; do
    if [ ! -f yolov10\$size.onnx ]; then
      yolo export model=yolov10\$size.pt format=onnx dynamic=True end2end=True
      rm -f yolov10\$size.pt
    fi
  done
  chown -R $(id -u):$(id -g) /models
"
ls -la
