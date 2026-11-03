# Sample data

`QR_Video.mp4` is copied unchanged from `services/qr-detector/v1/data/`, which took it from the
elastic-workbench repository. It is a 1920x1080 video with a QR code in view; the service uses the 30 frames
after the first one and keeps them at their original size, so that resizing is work done for every item.
`data_quality` is the height in pixels of the transformed frame.
