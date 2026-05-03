# Monitoring 인프라 구축 트러블슈팅 가이드

## 모니터링 아키텍처 요약

```
rag-mongo-vm (34.47.80.98)
├── Node Exporter 1.8.2          :9100  — 시스템 메트릭 (CPU/RAM/디스크/네트워크)
├── MongoDB Exporter 0.40.0      :9216  — MongoDB 메트릭 (Percona, mongodb_ss_*)
├── Prometheus 2.53.3            :9090  — 메트릭 수집 + 저장 (30일 보존)
├── Grafana                      :3000  — 대시보드 시각화
└── MongoDB 7.0.31               :27017 — 정책 메타데이터 저장소

rag-airflow-vm (10.178.0.4)
└── Node Exporter 1.8.2          :9100  — 시스템 메트릭 (Prometheus가 원격 스크랩)
```

### Prometheus 스크랩 대상

| Job | Target | 설명 |
|-----|--------|------|
| `node-mongo-vm` | `localhost:9100` | MongoDB VM 시스템 메트릭 |
| `node-airflow-vm` | `10.178.0.4:9100` | Airflow VM 시스템 메트릭 (VPC 내부) |
| `mongodb` | `localhost:9216` | MongoDB 메트릭 |

### Grafana 대시보드

| 대시보드 | 소스 | 설명 |
|----------|------|------|
| Node Exporter Full | 커뮤니티 ID 1860 | 시스템 메트릭 전체 (CPU, RAM, 디스크, 네트워크) |
| MongoDB (Percona Exporter) | 커스텀 작성 | Percona `mongodb_ss_*` 메트릭 기반 22개 패널 |

---

## 트러블슈팅 이슈

### 1. Percona MongoDB Exporter 플래그 호환성

**문제**

Percona mongodb_exporter v0.40.0에서 다양한 플래그 조합 시 패닉 또는 빈 응답 발생:

```
# 패닉 1: --collect-all
mongodb_exporter --collect-all --compatible-mode
# → panic: runtime error: nil pointer dereference

# 패닉 2: --discovering-mode + --compatible-mode
mongodb_exporter --discovering-mode --compatible-mode
# → panic: duplicate metrics collector registration (MustRegister)

# 빈 응답: 개별 collector 플래그
mongodb_exporter --collector.dbstats --collector.topmetrics --collector.indexstats --collector.collstats
# → /metrics 엔드포인트 빈 응답
```

**원인**

v0.40.0에서 특정 collector들이 standalone MongoDB 7.0에서 nil pointer dereference를 일으킴. `--discovering-mode`와 `--compatible-mode`를 같이 쓰면 Prometheus registry에 중복 등록 시도.

**해결**

`--compatible-mode`만 단독 사용:

```ini
# /etc/systemd/system/mongodb_exporter.service
[Service]
ExecStart=/usr/local/bin/mongodb_exporter \
  --mongodb.uri=mongodb://exporter:YOUR_EXPORTER_PASSWORD@localhost:27017/admin \
  --web.listen-address=:9216 \
  --compatible-mode
```

---

### 2. dcu/mongodb_exporter MongoDB 7.0 비호환

**문제**

dcu/mongodb_exporter v1.0.0 사용 시 MongoDB 7.0에 연결 실패:

```
error: no reachable servers
```

**원인**

dcu/mongodb_exporter는 구버전 `mgo` 드라이버를 사용하며, MongoDB 7.0의 wire protocol 변경 사항과 호환되지 않음.

**해결**

Percona mongodb_exporter v0.40.0으로 전환. Percona 버전은 공식 `mongo-driver`를 사용하여 MongoDB 6.0+ 지원.

```bash
wget -q "https://github.com/percona/mongodb_exporter/releases/download/v0.40.0/mongodb_exporter-0.40.0.linux-amd64.tar.gz"
tar xzf mongodb_exporter-0.40.0.linux-amd64.tar.gz
sudo cp mongodb_exporter-0.40.0.linux-amd64/mongodb_exporter /usr/local/bin/
```

---

### 3. MongoDB 인증 미설정으로 메트릭 수집 실패

**문제**

Exporter 실행 후 `/metrics` 엔드포인트에 `mongodb_up 1`만 반환되고, `mongodb_ss_*` 메트릭이 전혀 수집되지 않음.

```bash
curl -s http://localhost:9216/metrics | grep -c mongodb_
# 1  (mongodb_up만 존재)
```

**원인**

MongoDB에 인증(`--auth`)이 활성화되어 있으나, exporter가 인증 없이 접속하여 `serverStatus` 명령 실행 권한이 없음.

**해결**

1. MongoDB에 exporter 전용 사용자 생성:

```javascript
// /tmp/create_exporter.js
db.getSiblingDB("admin").createUser({
  user: "exporter",
  pwd: "YOUR_EXPORTER_PASSWORD",
  roles: [
    { role: "clusterMonitor", db: "admin" },
    { role: "read", db: "local" }
  ]
});
```

```bash
mongosh -u admin -p <admin_password> --authenticationDatabase admin /tmp/create_exporter.js
```

2. Exporter URI에 인증 정보 추가:

```
mongodb://exporter:YOUR_EXPORTER_PASSWORD@localhost:27017/admin
```

3. 결과 확인:

```bash
curl -s http://localhost:9216/metrics | grep -c mongodb_
# 6940
```

---

### 4. 커뮤니티 Grafana 대시보드 메트릭 이름 불일치

**문제**

Grafana 커뮤니티 대시보드 (ID: 2583, 12079, 14997, 20867) 모두 import 후 전 패널 "No data" 표시.

**원인**

MongoDB exporter 생태계에는 두 가지 메트릭 이름 체계가 존재:

| Exporter | 메트릭 형식 | 예시 |
|----------|------------|------|
| dcu/mongodb_exporter (구버전) | `mongodb_connections` | `mongodb_connections{state="current"}` |
| Percona (v0.40.0, 기본) | `mongodb_ss_*` | `mongodb_ss_connections{conn_type="current"}` |
| Percona (`--compatible-mode`) | `mongodb_mongod_*` (추가) | `mongodb_mongod_wiredtiger_log_bytes_total` |

커뮤니티 대시보드 대부분은 dcu 형식(`mongodb_connections`)을 기대하지만, Percona exporter는 `mongodb_ss_connections`을 출력. `--compatible-mode`가 추가로 내보내는 `mongodb_mongod_*`도 dcu 형식과 달라서 호환되지 않음.

**해결**

Percona `mongodb_ss_*` 메트릭에 맞는 커스텀 대시보드를 직접 작성:

- 파일: `monitoring/grafana/dashboards/mongodb-exporter.json`
- 22개 패널, 5개 섹션 (Health, Operations, Connections, Memory/Network, WiredTiger/Lock)
- 주요 메트릭: `mongodb_ss_connections`, `mongodb_ss_opcounters`, `mongodb_ss_mem_resident`, `mongodb_ss_network_bytesIn`, `mongodb_ss_wt_cache_*`, `mongodb_ss_globalLock_*`

**참고: 메트릭 이름 확인 방법**

```bash
# Percona exporter가 실제로 내보내는 메트릭 이름 확인
curl -s http://localhost:9216/metrics | grep "^mongodb_ss_" | cut -d'{' -f1 | sort -u
```

---

### 5. Grafana 프로비저닝 대시보드 삭제 불가

**문제**

불필요한 대시보드(GCE VM Monitoring, RAG Youth Policy Pipeline, 구 MongoDB)를 Grafana UI 또는 API로 삭제 시도:

```bash
curl -s -u admin:admin -X DELETE 'http://localhost:3000/api/dashboards/uid/<uid>'
# {"message":"provisioned dashboard cannot be deleted"}
```

**원인**

파일 기반 프로비저닝(`/etc/grafana/provisioning/dashboards/`)으로 배포된 대시보드는 Grafana가 파일에서 관리하므로 API/UI 삭제가 차단됨. 프로비저닝 소스 파일을 삭제해도 Grafana 내부 SQLite DB(`grafana.db`)에 캐시가 남아 계속 표시됨.

**해결**

1. `/var/lib/grafana/dashboards/`에서 불필요한 JSON 파일 삭제:

```bash
sudo rm -f /var/lib/grafana/dashboards/gce-vm-monitoring.json
sudo rm -f /var/lib/grafana/dashboards/rag-pipeline.json
```

2. Grafana DB 리셋 (프로비저닝 파일에서 자동 복원됨):

```bash
sudo systemctl stop grafana-server
sudo rm /var/lib/grafana/grafana.db
sudo systemctl start grafana-server
```

> **주의**: DB 리셋 시 admin 비밀번호가 초기화됨 (admin/admin). 프로비저닝 설정(datasources, dashboards)은 파일에서 자동 복원.

---

### 6. VM 내부에서 GCP 방화벽 규칙 생성 실패

**문제**

VM SSH 세션에서 `gcloud compute firewall-rules create` 실행 시:

```
ERROR: (gcloud.compute.firewall-rules.create) Could not fetch resource:
 - Insufficient Permission: Request had insufficient authentication scopes.
```

**원인**

GCE VM의 서비스 계정에 Compute Engine API 쓰기 scope가 부여되지 않음. VM 생성 시 기본 scope에는 `compute-rw`가 포함되지 않을 수 있음.

**해결**

로컬 터미널에서 개인 계정 인증으로 실행:

```bash
# 로컬에서 실행 (VM이 아닌)
gcloud compute firewall-rules create allow-grafana \
  --allow tcp:3000 \
  --source-ranges 0.0.0.0/0 \
  --target-tags rag-mongo \
  --description "Allow Grafana access" \
  --project rag-qna-eval
```

---

### 7. SSH를 통한 멀티라인 명령 전달 실패

**문제**

`gcloud compute ssh` 명령에 긴 명령을 전달할 때, 터미널의 줄바꿈으로 인해 명령이 별도 명령으로 분리되어 실행 실패:

```bash
# 실패 — 줄바꿈으로 명령 깨짐
gcloud compute ssh vm-name --zone=zone -- "sudo cp
  /source/file
  /dest/file"
# → bash: /source/file: Permission denied
```

**원인**

SSH를 통해 전달되는 명령 문자열이 줄바꿈 시 셸에서 별도 명령으로 해석됨.

**해결**

두 가지 방법:

```bash
# 방법 1: 반드시 한 줄로 작성
gcloud compute ssh vm-name --zone=zone -- "sudo cp /source/file /dest/file && sudo systemctl restart service"

# 방법 2: VM에서 스크립트 파일 생성 후 실행
gcloud compute ssh vm-name --zone=zone -- "cat <<'SCRIPT' > /tmp/task.sh
sudo cp /source/file /dest/file
sudo systemctl restart service
echo Done
SCRIPT
bash /tmp/task.sh"
```

---

## Node Exporter Full 대시보드 데이터소스 수정

커뮤니티 대시보드 JSON(ID: 1860)을 다운로드하면 데이터소스가 `${DS_PROMETHEUS}` 변수로 참조되어 프로비저닝 시 인식 불가.

```bash
# 다운로드 후 데이터소스 참조 수정
sed -i 's/${DS_PROMETHEUS}/Prometheus/g' node-exporter-full.json
```

`Prometheus`는 `datasources.yml`에 정의된 데이터소스 이름과 일치해야 함.

---

## 최종 구성

### 실행 중인 서비스 (rag-mongo-vm)

| 서비스 | 포트 | 상태 확인 |
|--------|------|-----------|
| Node Exporter | :9100 | `curl http://localhost:9100/metrics` |
| MongoDB Exporter | :9216 | `curl http://localhost:9216/metrics \| grep -c mongodb_` → 6,940+ |
| Prometheus | :9090 | `curl http://localhost:9090/-/healthy` |
| Grafana | :3000 | `http://34.47.80.98:3000` (admin/admin) |

### Grafana 대시보드

| 대시보드 | 파일 | 패널 수 |
|----------|------|---------|
| Node Exporter Full | `node-exporter-full.json` | 30+ (커뮤니티) |
| MongoDB (Percona Exporter) | `mongodb-exporter.json` | 22 (커스텀) |

### 관련 파일

```
scripts/setup_grafana.sh                              # 전체 설치 스크립트
monitoring/prometheus/prometheus.yml                   # Prometheus 스크랩 설정
monitoring/grafana/provisioning/datasources.yml        # Grafana 데이터소스
monitoring/grafana/provisioning/dashboards.yml         # Grafana 대시보드 프로비저닝
monitoring/grafana/dashboards/node-exporter-full.json  # Node Exporter 대시보드
monitoring/grafana/dashboards/mongodb-exporter.json    # MongoDB 커스텀 대시보드
```
