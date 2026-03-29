# Grafana Monitoring Stack

## Context

The `/metrics` endpoint already exports Prometheus-format metrics (HTTP requests, job counts/duration, queue depth, GPU VRAM, active sessions). The `/health` endpoint reports component status. Neither is consumed by anything — monitoring is reading log files. This plan adds Grafana + Prometheus to the Docker stack.

## What Already Exists

**Prometheus metrics** (`/metrics`):
- `songmaker_http_requests_total{method, status}` — counter
- `songmaker_http_request_duration_milliseconds_total` — counter
- `songmaker_active_sessions` — gauge
- `songmaker_jobs_total{type, status}` — gauge
- `songmaker_job_duration_seconds{quantile=avg|min|max}` — gauge
- `songmaker_queue_depth` — gauge
- `songmaker_gpu_vram_megabytes` — gauge (when pynvml available)

**Health endpoint** (`/health`):
- `status`: ok/degraded
- `worker`: running/stopped
- `queue_depth`, `db`, `redis`, `acestep`, `acestep_model`, `uptime_seconds`

## Implementation

### 1. Add Prometheus + Grafana to docker-compose.yml

```yaml
  prometheus:
    image: prom/prometheus:latest
    restart: unless-stopped
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - promdata:/prometheus
    depends_on:
      songmaker-web:
        condition: service_healthy
    cap_drop:
      - ALL

  grafana:
    image: grafana/grafana:latest
    restart: unless-stopped
    environment:
      GF_SECURITY_ADMIN_USER: ${GRAFANA_USER:-admin}
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD:-admin}
      GF_AUTH_ANONYMOUS_ENABLED: "false"
    ports:
      - "3000:3000"
    volumes:
      - grafdata:/var/lib/grafana
      - ./monitoring/provisioning:/etc/grafana/provisioning:ro
      - ./monitoring/dashboards:/var/lib/grafana/dashboards:ro
    depends_on:
      - prometheus
    cap_drop:
      - ALL
```

Add volumes: `promdata:`, `grafdata:`

### 2. Create monitoring/prometheus.yml

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: songmaker
    metrics_path: /metrics
    static_configs:
      - targets: ["songmaker-web:8080"]
```

### 3. Create Grafana provisioning

**monitoring/provisioning/datasources/prometheus.yml:**
```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
    isDefault: true
```

**monitoring/provisioning/dashboards/default.yml:**
```yaml
apiVersion: 1
providers:
  - name: Default
    folder: Songmaker
    type: file
    options:
      path: /var/lib/grafana/dashboards
```

### 4. Create monitoring/dashboards/songmaker.json

Dashboard with these panels:

**Row 1: Overview**
- Uptime (stat, from health endpoint scrape or custom metric)
- Active sessions (gauge: `songmaker_active_sessions`)
- Queue depth (gauge: `songmaker_queue_depth`)
- GPU VRAM (gauge: `songmaker_gpu_vram_megabytes`)

**Row 2: HTTP Traffic**
- Request rate (graph: `rate(songmaker_http_requests_total[5m])` by status)
- Error rate (graph: status 4xx/5xx only)
- Avg request duration (graph: `rate(duration_total) / rate(requests_count)`)

**Row 3: Jobs**
- Jobs by status (stacked bar: `songmaker_jobs_total` by type and status)
- Job duration avg/min/max (graph: `songmaker_job_duration_seconds`)
- Failed jobs (stat: `songmaker_jobs_total{status="failed"}`)

**Row 4: Infrastructure**
- GPU VRAM over time (graph: `songmaker_gpu_vram_megabytes`)
- Queue depth over time (graph: `songmaker_queue_depth`)

### 5. Optional: Alerts

Add to Grafana or Prometheus alertmanager:
- Queue depth > 5 for 10 minutes
- Worker stopped for > 2 minutes
- GPU VRAM > 22GB (approaching 24GB limit on RTX 3090)
- Error rate > 10% for 5 minutes

## Files to Create

```
monitoring/
  prometheus.yml
  provisioning/
    datasources/
      prometheus.yml
    dashboards/
      default.yml
  dashboards/
    songmaker.json
```

## Effort

~2-3 hours. The metrics endpoint is already done. This is all configuration — no application code changes.
