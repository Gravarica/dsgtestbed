#!/bin/sh
set -eu
model_directory=fetched/models
model_file=$model_directory/face_detection_yunet_2023mar.onnx
model_url=https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
model_sha256=8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4
if [ -f "$model_file" ] && echo "$model_sha256  $model_file" | sha256sum -c - >/dev/null 2>&1; then
    exit 0
fi
mkdir -p "$model_directory"
curl -fsSL -o "$model_file" "$model_url"
echo "$model_sha256  $model_file" | sha256sum -c -
