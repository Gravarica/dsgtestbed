# Sample data

`QR_Video.mp4` is copied unchanged from `services/qr-detector/v1/data/`, which took it from the
elastic-workbench repository. It is a 1920x1080 video with a QR code in view; the service uses the 60 frames
after the first one. `data_quality` is the height in pixels the frames are resized to.

The video itself is clean, so every worker adds Gaussian noise (standard deviation 15 grey levels, fixed seed)
to the resized frames when it starts. The noisy frames are the samples the service cleans; the resized frames
without noise are the reference the tests compare against.
