# Sample data

`QR_Video.mp4` is copied unchanged from `services/qr-detector/v1/data/`, which took it from the
elastic-workbench repository. It is a 1920x1080 video with a QR code in view. The service reads the first 61
frames; sample `i` is the pair (frame `i + 1`, frame `i`), the frame and the one before it. `data_quality` is the
height in pixels both frames are resized to before they are compared.
