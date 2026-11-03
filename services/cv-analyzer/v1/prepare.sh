set -e
cd "$(dirname "$0")/models"
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
