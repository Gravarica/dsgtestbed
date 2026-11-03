# Sample data

`QR_Video.mp4` is copied unchanged from `services/qr-detector/v1/data/`, which took it from the
elastic-workbench repository. It is a 1920x1080 video; the service uses the 60 frames after the first one,
resized to a height of 640 pixels, the largest frame height the detectors of the B3 trees use.
