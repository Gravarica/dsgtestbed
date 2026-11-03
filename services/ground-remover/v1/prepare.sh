set -e
cd "$(dirname "$0")"
DRIVE=2011_09_26_drive_0001_sync
SCANS=fetched/scans
SCAN_COUNT=60
PC_VISUALIZER_SCANS=../../pc-visualizer/v1/data/2011_09_26/$DRIVE/velodyne_points/data
if [ "$(ls $SCANS/*.bin 2>/dev/null | wc -l)" -ge $SCAN_COUNT ]; then
  echo "scans already present in $SCANS"
  exit 0
fi
mkdir -p $SCANS
if [ "$(ls $PC_VISUALIZER_SCANS/*.bin 2>/dev/null | wc -l)" -ge $SCAN_COUNT ]; then
  ls $PC_VISUALIZER_SCANS/*.bin | sort | head -n $SCAN_COUNT | xargs -I{} cp {} $SCANS/
else
  curl -L --fail --silent --show-error -o fetched/$DRIVE.zip "https://s3.eu-central-1.amazonaws.com/avg-kitti/raw_data/2011_09_26_drive_0001/$DRIVE.zip"
  unzip -q -o fetched/$DRIVE.zip "2011_09_26/$DRIVE/velodyne_points/data/*" -d fetched/unpacked
  ls fetched/unpacked/2011_09_26/$DRIVE/velodyne_points/data/*.bin | sort | head -n $SCAN_COUNT | xargs -I{} cp {} $SCANS/
  rm -rf fetched/unpacked fetched/$DRIVE.zip
fi
echo "$(ls $SCANS/*.bin | wc -l) scans in $SCANS"
