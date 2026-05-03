#!/usr/bin/env bash
# MongoDB VM에 Node Exporter + MongoDB Exporter + Prometheus + Grafana 설치 및 구성.
#
# 사용법: bash scripts/setup_grafana.sh
#
# 구성:
#   - Node Exporter (:9100) — 시스템 메트릭 (CPU/RAM/디스크/네트워크)
#   - MongoDB Exporter (:9216) — MongoDB 메트릭 (dcu/mongodb_exporter)
#   - Prometheus (:9090) — 메트릭 수집 + 저장
#   - Grafana (:3000) — 대시보드 시각화
#
# 대시보드 (Grafana 커뮤니티):
#   - Node Exporter Full (ID: 1860)
#   - MongoDB Exporter Dashboard (ID: 2583)
#
# 참고: Airflow VM에도 Node Exporter를 설치하면 원격 모니터링 가능
#       (Prometheus가 10.178.0.4:9100 을 스크랩)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

NODE_EXPORTER_VERSION="1.8.2"
MONGODB_EXPORTER_VERSION="0.40.0"
PROMETHEUS_VERSION="2.53.3"

# ── 1. Node Exporter ─────────────────────────────────────────
echo "=== 1/6: Node Exporter 설치 ==="
if systemctl is-active --quiet node_exporter 2>/dev/null; then
  echo "  이미 실행 중 (건너뜀)"
else
  cd /tmp
  wget -q "https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz"
  tar xzf "node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz"
  sudo cp "node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64/node_exporter" /usr/local/bin/
  rm -rf "node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64"*

  sudo useradd --no-create-home --shell /bin/false node_exporter 2>/dev/null || true

  sudo tee /etc/systemd/system/node_exporter.service > /dev/null <<'UNIT'
[Unit]
Description=Node Exporter
After=network.target

[Service]
User=node_exporter
ExecStart=/usr/local/bin/node_exporter
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

  sudo systemctl daemon-reload
  sudo systemctl enable --now node_exporter
  echo "  Node Exporter 설치 완료 (:9100)"
fi

# ── 2. MongoDB Exporter (dcu/mongodb_exporter) ───────────────
echo ""
echo "=== 2/6: MongoDB Exporter 설치 ==="
if systemctl is-active --quiet mongodb_exporter 2>/dev/null; then
  echo "  이미 실행 중 (건너뜀)"
else
  cd /tmp
  wget -q "https://github.com/percona/mongodb_exporter/releases/download/v${MONGODB_EXPORTER_VERSION}/mongodb_exporter-${MONGODB_EXPORTER_VERSION}.linux-amd64.tar.gz"
  tar xzf "mongodb_exporter-${MONGODB_EXPORTER_VERSION}.linux-amd64.tar.gz"
  sudo cp "mongodb_exporter-${MONGODB_EXPORTER_VERSION}.linux-amd64/mongodb_exporter" /usr/local/bin/
  rm -rf "mongodb_exporter-${MONGODB_EXPORTER_VERSION}.linux-amd64"*

  sudo useradd --no-create-home --shell /bin/false mongodb_exporter 2>/dev/null || true

  sudo tee /etc/systemd/system/mongodb_exporter.service > /dev/null <<'UNIT'
[Unit]
Description=MongoDB Exporter
After=network.target mongod.service

[Service]
User=mongodb_exporter
Environment="MONGODB_URI=mongodb://exporter:YOUR_EXPORTER_PASSWORD@localhost:27017/admin"
ExecStart=/usr/local/bin/mongodb_exporter \
  --mongodb.uri=mongodb://exporter:YOUR_EXPORTER_PASSWORD@localhost:27017/admin \
  --web.listen-address=:9216 \
  --compatible-mode
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

  sudo systemctl daemon-reload
  sudo systemctl enable --now mongodb_exporter
  echo "  MongoDB Exporter 설치 완료 (:9216)"
fi

# ── 3. Prometheus ─────────────────────────────────────────────
echo ""
echo "=== 3/6: Prometheus 설치 ==="
if systemctl is-active --quiet prometheus 2>/dev/null; then
  echo "  이미 실행 중 — 설정만 업데이트"
else
  cd /tmp
  wget -q "https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz"
  tar xzf "prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz"
  sudo cp "prometheus-${PROMETHEUS_VERSION}.linux-amd64/prometheus" /usr/local/bin/
  sudo cp "prometheus-${PROMETHEUS_VERSION}.linux-amd64/promtool" /usr/local/bin/
  rm -rf "prometheus-${PROMETHEUS_VERSION}.linux-amd64"*

  sudo useradd --no-create-home --shell /bin/false prometheus 2>/dev/null || true
  sudo mkdir -p /etc/prometheus /var/lib/prometheus
  sudo chown prometheus:prometheus /var/lib/prometheus

  sudo tee /etc/systemd/system/prometheus.service > /dev/null <<'UNIT'
[Unit]
Description=Prometheus
After=network.target

[Service]
User=prometheus
ExecStart=/usr/local/bin/prometheus \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/var/lib/prometheus \
  --storage.tsdb.retention.time=30d \
  --web.listen-address=:9090
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

  sudo systemctl daemon-reload
  echo "  Prometheus 바이너리 설치 완료"
fi

sudo cp "$REPO_ROOT/monitoring/prometheus/prometheus.yml" /etc/prometheus/prometheus.yml
sudo chown prometheus:prometheus /etc/prometheus/prometheus.yml
sudo systemctl enable --now prometheus
sudo systemctl reload prometheus 2>/dev/null || sudo systemctl restart prometheus
echo "  Prometheus 설정 적용 완료 (:9090)"

# ── 4. Grafana ────────────────────────────────────────────────
echo ""
echo "=== 4/6: Grafana 설치 ==="
if systemctl is-active --quiet grafana-server 2>/dev/null; then
  echo "  이미 실행 중 (건너뜀)"
else
  sudo apt-get install -y apt-transport-https software-properties-common wget >/dev/null 2>&1
  sudo mkdir -p /etc/apt/keyrings/
  wget -q -O - https://apt.grafana.com/gpg.key | gpg --dearmor | sudo tee /etc/apt/keyrings/grafana.gpg > /dev/null
  echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" | sudo tee /etc/apt/sources.list.d/grafana.list > /dev/null
  sudo apt-get update -qq
  sudo apt-get install -y grafana >/dev/null 2>&1
  sudo systemctl enable grafana-server
  echo "  Grafana 설치 완료"
fi

# ── 5. Grafana 프로비저닝 ─────────────────────────────────────
echo ""
echo "=== 5/6: Grafana 프로비저닝 ==="
GRAFANA_HOME="/etc/grafana"
GRAFANA_DASHBOARDS="/var/lib/grafana/dashboards"

sudo cp "$REPO_ROOT/monitoring/grafana/provisioning/datasources.yml" \
  "$GRAFANA_HOME/provisioning/datasources/rag-datasources.yml"
sudo cp "$REPO_ROOT/monitoring/grafana/provisioning/dashboards.yml" \
  "$GRAFANA_HOME/provisioning/dashboards/rag-dashboards.yml"

sudo mkdir -p "$GRAFANA_DASHBOARDS"
sudo cp "$REPO_ROOT/monitoring/grafana/dashboards/node-exporter-full.json" \
  "$GRAFANA_DASHBOARDS/node-exporter-full.json"
sudo cp "$REPO_ROOT/monitoring/grafana/dashboards/mongodb-exporter.json" \
  "$GRAFANA_DASHBOARDS/mongodb-exporter.json"
echo "  프로비저닝 파일 복사 완료 (Node Exporter Full + MongoDB Exporter)"

# ── 6. Grafana 재시작 ─────────────────────────────────────────
echo ""
echo "=== 6/6: Grafana 시작 ==="
sudo systemctl restart grafana-server
sleep 2
if systemctl is-active --quiet grafana-server; then
  echo "  Grafana 재시작 성공"
else
  echo "  WARNING: Grafana 시작 실패. 로그: sudo journalctl -u grafana-server -n 20"
fi

# ── 상태 요약 ─────────────────────────────────────────────────
echo ""
echo "=== 설치 완료 ==="
echo ""
echo "  Node Exporter    : http://localhost:9100/metrics"
echo "  MongoDB Exporter : http://localhost:9216/metrics"
echo "  Prometheus       : http://localhost:9090"
echo "  Grafana          : http://$(hostname -I | awk '{print $1}'):3000"
echo ""
echo "  대시보드:"
echo "    - Node Exporter Full (커뮤니티 ID: 1860)"
echo "    - MongoDB Exporter (커뮤니티 ID: 2583)"
echo ""
echo "  Grafana 기본 로그인: admin / admin"
echo ""
echo "  Airflow VM에도 Node Exporter를 설치하려면:"
echo "    gcloud compute ssh rag-airflow-vm --zone=asia-northeast3-a -- \\"
echo "      'wget -q https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz && \\"
echo "       tar xzf node_exporter-*.tar.gz && sudo cp node_exporter-*/node_exporter /usr/local/bin/ && \\"
echo "       sudo useradd --no-create-home --shell /bin/false node_exporter; \\"
echo "       echo \"[Unit]\nDescription=Node Exporter\nAfter=network.target\n[Service]\nUser=node_exporter\nExecStart=/usr/local/bin/node_exporter\nRestart=on-failure\n[Install]\nWantedBy=multi-user.target\" | sudo tee /etc/systemd/system/node_exporter.service && \\"
echo "       sudo systemctl daemon-reload && sudo systemctl enable --now node_exporter'"
