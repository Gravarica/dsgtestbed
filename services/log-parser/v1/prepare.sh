set -e
cd "$(dirname "$0")"

for system in Apache HDFS Hadoop Spark Zookeeper OpenStack Linux OpenSSH; do
  mkdir -p fetched/loghub/$system
  for suffix in log log_structured.csv log_templates.csv; do
    target=fetched/loghub/$system/${system}_2k.$suffix
    if [ ! -f "$target" ]; then
      curl -L --fail --silent --show-error -o "$target.part" \
        "https://raw.githubusercontent.com/logpai/loghub/master/$system/${system}_2k.$suffix"
      mv "$target.part" "$target"
    fi
  done
done
echo "$(ls fetched/loghub | wc -l) systems in fetched/loghub"
