set -e
cd "$(dirname "$0")"

if [ ! -f fetched/readings/windows.json ]; then
  python3 generate_readings.py fetched/readings
fi
echo "readings in fetched/readings: $(du -h fetched/readings/readings.f32 | cut -f1)"
