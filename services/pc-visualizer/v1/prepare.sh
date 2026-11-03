set -e
cd "$(dirname "$0")/data"
DRIVE=2011_09_26_drive_0001_sync
SCANS=2011_09_26/$DRIVE/velodyne_points/data
if [ "$(ls $SCANS/*.bin 2>/dev/null | wc -l)" -ge 60 ]; then
  echo "scans already present in $SCANS"
  exit 0
fi
curl -L --fail --silent --show-error -o $DRIVE.zip "https://s3.eu-central-1.amazonaws.com/avg-kitti/raw_data/2011_09_26_drive_0001/$DRIVE.zip"
unzip -q -o $DRIVE.zip "2011_09_26/$DRIVE/velodyne_points/*"
rm $DRIVE.zip
echo "$(ls $SCANS/*.bin | wc -l) scans in $SCANS"
