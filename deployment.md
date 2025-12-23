# 🚀 DocGuard Deployment Guide

Complete deployment guide for DocGuard across various environments and platforms.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Deployment Options](#deployment-options)
  - [Docker Compose (Recommended)](#docker-compose-recommended)
  - [Docker Standalone](#docker-standalone)
  - [Kubernetes](#kubernetes)
  - [Cloud Platforms](#cloud-platforms)
  - [Manual/Local Deployment](#manuallocal-deployment)
- [Configuration](#configuration)
- [Security Hardening](#security-hardening)
- [Monitoring & Logging](#monitoring--logging)
- [Backup & Disaster Recovery](#backup--disaster-recovery)
- [Scaling Strategies](#scaling-strategies)
- [Troubleshooting](#troubleshooting)

---

## Overview

DocGuard is designed for flexible deployment across various environments:

- **Development**: Local Python environment or Docker
- **Staging**: Docker Compose with resource limits
- **Production**: Docker Compose, Kubernetes, or cloud-managed services

### Deployment Architecture

```
┌─────────────────────────────────────────────┐
│           Load Balancer / Ingress           │
│              (Optional)                      │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│         DocGuard Container(s)               │
│                                             │
│  ┌─────────────────────────────────────┐   │
│  │   Streamlit Frontend (Port 8501)    │   │
│  └─────────────────────────────────────┘   │
│  ┌─────────────────────────────────────┐   │
│  │   Document Processing Engine        │   │
│  │   (PyMuPDF, spaCy, PaddleOCR)      │   │
│  └─────────────────────────────────────┘   │
│  ┌─────────────────────────────────────┐   │
│  │   In-Memory Processing              │   │
│  │   (No Persistent Storage)           │   │
│  └─────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

---

## Prerequisites

### All Deployments

- Git (for cloning the repository)
- Basic understanding of container orchestration (for Docker/K8s deployments)

### Docker-Based Deployments

- Docker Engine 20.10+ ([Install Docker](https://docs.docker.com/get-docker/))
- Docker Compose 2.0+ ([Install Docker Compose](https://docs.docker.com/compose/install/))

### Kubernetes Deployments

- kubectl configured with cluster access
- Helm 3+ (optional, for easier deployment)
- Kubernetes cluster 1.21+

### Manual Deployments

- Python 3.12+
- pip package manager
- System dependencies: `libgl1`, `libglib2.0-0`, `ghostscript`

### Recommended System Requirements

| Environment | CPU | RAM | Storage |
|-------------|-----|-----|---------|
| **Development** | 2 cores | 4GB | 5GB |
| **Staging** | 4 cores | 8GB | 10GB |
| **Production** | 8+ cores | 16GB+ | 20GB+ |

---

## Deployment Options

### Docker Compose (Recommended)

Best for: Development, staging, small to medium production deployments

#### Quick Start

```bash
# Clone repository
git clone https://github.com/nowusman/DocGuard.git
cd DocGuard

# Create environment file
cat > .env << EOF
THROUGHPUT_MODE=false
MAX_WORKERS=4
OCR_MAX_IMAGES_PER_DOC=10
OCR_RENDER_SCALE=1.25
VERBOSE_LOGGING=false
MAX_CACHE_ITEMS=64
EOF

# Start services
docker-compose up -d

# Verify deployment
docker-compose ps
curl http://localhost:8501
```

#### Production Configuration

Update `docker-compose.yml` with resource limits:

```yaml
version: "3.9"

services:
  frontend:
    build:
      context: ./app
    container_name: docguard-frontend
    ports:
      - "8501:8501"
    restart: unless-stopped
    env_file:
      - .env
    deploy:
      resources:
        limits:
          cpus: "8.0"
          memory: 16G
        reservations:
          cpus: "4.0"
          memory: 8G
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8501"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

networks:
  default:
    name: docguard-net
    driver: bridge
```

#### Managing the Service

```bash
# Start services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down

# Restart services
docker-compose restart

# Update and rebuild
git pull
docker-compose down
docker-compose up -d --build

# Scale (if using replicas)
docker-compose up -d --scale frontend=3
```

---

### Docker Standalone

Best for: Minimal deployments, testing, CI/CD pipelines

#### Build and Run

```bash
# Build image
cd app
docker build -t docguard:latest .

# Run container
docker run -d \
  --name docguard \
  -p 8501:8501 \
  -e MAX_WORKERS=4 \
  -e THROUGHPUT_MODE=false \
  --restart unless-stopped \
  --memory="8g" \
  --cpus="4.0" \
  docguard:latest

# Verify
docker ps
docker logs docguard
```

#### Cleanup

```bash
# Stop container
docker stop docguard

# Remove container
docker rm docguard

# Remove image
docker rmi docguard:latest
```

---

### Kubernetes

Best for: Large-scale production, high availability, auto-scaling

#### Kubernetes Manifests

**deployment.yaml**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: docguard
  namespace: docguard
  labels:
    app: docguard
spec:
  replicas: 3
  selector:
    matchLabels:
      app: docguard
  template:
    metadata:
      labels:
        app: docguard
    spec:
      containers:
      - name: docguard
        image: docguard:latest
        imagePullPolicy: Always
        ports:
        - containerPort: 8501
          name: http
        env:
        - name: MAX_WORKERS
          value: "4"
        - name: THROUGHPUT_MODE
          value: "false"
        - name: OCR_MAX_IMAGES_PER_DOC
          value: "10"
        - name: VERBOSE_LOGGING
          value: "false"
        resources:
          requests:
            memory: "8Gi"
            cpu: "4"
          limits:
            memory: "16Gi"
            cpu: "8"
        livenessProbe:
          httpGet:
            path: /
            port: 8501
          initialDelaySeconds: 60
          periodSeconds: 30
          timeoutSeconds: 10
        readinessProbe:
          httpGet:
            path: /
            port: 8501
          initialDelaySeconds: 30
          periodSeconds: 10
          timeoutSeconds: 5
        securityContext:
          runAsNonRoot: true
          runAsUser: 1000
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: false
```

**service.yaml**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: docguard-service
  namespace: docguard
spec:
  selector:
    app: docguard
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8501
  type: LoadBalancer
```

**ingress.yaml**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: docguard-ingress
  namespace: docguard
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - docguard.yourdomain.com
    secretName: docguard-tls
  rules:
  - host: docguard.yourdomain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: docguard-service
            port:
              number: 80
```

**namespace.yaml**

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: docguard
```

#### Deploy to Kubernetes

```bash
# Create namespace
kubectl apply -f namespace.yaml

# Deploy application
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml
kubectl apply -f ingress.yaml

# Verify deployment
kubectl get pods -n docguard
kubectl get svc -n docguard
kubectl get ingress -n docguard

# View logs
kubectl logs -f deployment/docguard -n docguard

# Scale deployment
kubectl scale deployment/docguard --replicas=5 -n docguard
```

#### Helm Chart (Optional)

Create `helm/docguard/values.yaml`:

```yaml
replicaCount: 3

image:
  repository: docguard
  tag: latest
  pullPolicy: Always

service:
  type: LoadBalancer
  port: 80

ingress:
  enabled: true
  className: nginx
  hosts:
    - host: docguard.yourdomain.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: docguard-tls
      hosts:
        - docguard.yourdomain.com

resources:
  requests:
    memory: "8Gi"
    cpu: "4"
  limits:
    memory: "16Gi"
    cpu: "8"

env:
  MAX_WORKERS: "4"
  THROUGHPUT_MODE: "false"
  OCR_MAX_IMAGES_PER_DOC: "10"
```

Deploy with Helm:

```bash
helm install docguard ./helm/docguard -n docguard --create-namespace
helm upgrade docguard ./helm/docguard -n docguard
```

---

### Cloud Platforms

#### AWS (ECS/Fargate)

**Task Definition**:

```json
{
  "family": "docguard",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "4096",
  "memory": "16384",
  "containerDefinitions": [
    {
      "name": "docguard",
      "image": "<account-id>.dkr.ecr.<region>.amazonaws.com/docguard:latest",
      "portMappings": [
        {
          "containerPort": 8501,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {"name": "MAX_WORKERS", "value": "4"},
        {"name": "THROUGHPUT_MODE", "value": "false"}
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/docguard",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
```

Deploy:

```bash
# Build and push to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com
docker build -t docguard app/
docker tag docguard:latest <account-id>.dkr.ecr.us-east-1.amazonaws.com/docguard:latest
docker push <account-id>.dkr.ecr.us-east-1.amazonaws.com/docguard:latest

# Create ECS service
aws ecs create-service \
  --cluster docguard-cluster \
  --service-name docguard-service \
  --task-definition docguard \
  --desired-count 3 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-xxx],assignPublicIp=ENABLED}"
```

#### Google Cloud (Cloud Run)

```bash
# Build and push to GCR
gcloud builds submit --tag gcr.io/<project-id>/docguard app/

# Deploy to Cloud Run
gcloud run deploy docguard \
  --image gcr.io/<project-id>/docguard \
  --platform managed \
  --region us-central1 \
  --memory 16Gi \
  --cpu 8 \
  --max-instances 10 \
  --set-env-vars MAX_WORKERS=4,THROUGHPUT_MODE=false \
  --allow-unauthenticated
```

#### Azure (Container Instances)

```bash
# Build and push to ACR
az acr build --registry <registry-name> --image docguard:latest app/

# Deploy to ACI
az container create \
  --resource-group docguard-rg \
  --name docguard \
  --image <registry-name>.azurecr.io/docguard:latest \
  --cpu 8 \
  --memory 16 \
  --ports 8501 \
  --dns-name-label docguard \
  --environment-variables MAX_WORKERS=4 THROUGHPUT_MODE=false
```

---

### Manual/Local Deployment

Best for: Development, testing, resource-constrained environments

#### Setup

```bash
# Clone repository
git clone https://github.com/nowusman/DocGuard.git
cd DocGuard

# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r app/requirements.txt
python -m spacy download en_core_web_sm

# Install system dependencies (Ubuntu/Debian)
sudo apt-get update
sudo apt-get install -y libgl1 libglib2.0-0 ghostscript

# macOS
brew install ghostscript

# Create environment file
cat > .env << EOF
THROUGHPUT_MODE=false
MAX_WORKERS=4
OCR_MAX_IMAGES_PER_DOC=10
VERBOSE_LOGGING=false
EOF

# Run application
cd app
streamlit run app.py --server.port=8501 --server.address=0.0.0.0
```

#### Process Management (systemd)

Create `/etc/systemd/system/docguard.service`:

```ini
[Unit]
Description=DocGuard Document Processing Service
After=network.target

[Service]
Type=simple
User=docguard
WorkingDirectory=/opt/docguard/app
Environment="PATH=/opt/docguard/venv/bin"
ExecStart=/opt/docguard/venv/bin/streamlit run app.py --server.port=8501 --server.address=0.0.0.0
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable docguard
sudo systemctl start docguard
sudo systemctl status docguard
```

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `THROUGHPUT_MODE` | `false` | Skip OCR/tables for faster processing |
| `MAX_WORKERS` | CPU count | Number of parallel worker processes |
| `OCR_MAX_IMAGES_PER_DOC` | `10` | Maximum images to OCR per document |
| `OCR_RENDER_SCALE` | `1.25` | PDF rendering resolution multiplier |
| `VERBOSE_LOGGING` | `false` | Enable detailed logging |
| `MAX_CACHE_ITEMS` | `64` | LRU cache size for processed documents |

### Streamlit Configuration

Create `app/.streamlit/config.toml`:

```toml
[server]
port = 8501
address = "0.0.0.0"
maxUploadSize = 100
enableCORS = false
enableXsrfProtection = true

[browser]
gatherUsageStats = false

[theme]
primaryColor = "#1f77b4"
backgroundColor = "#ffffff"
secondaryBackgroundColor = "#f0f2f6"
textColor = "#262730"
```

---

## Security Hardening

### TLS/SSL Configuration

#### Nginx Reverse Proxy

```nginx
server {
    listen 80;
    server_name docguard.yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name docguard.yourdomain.com;

    ssl_certificate /etc/ssl/certs/docguard.crt;
    ssl_certificate_key /etc/ssl/private/docguard.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    client_max_body_size 100M;

    location / {
        proxy_pass http://localhost:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Authentication

#### Basic Auth (Nginx)

```bash
# Create password file
sudo htpasswd -c /etc/nginx/.htpasswd docguard_user

# Update nginx config
location / {
    auth_basic "DocGuard Access";
    auth_basic_user_file /etc/nginx/.htpasswd;
    proxy_pass http://localhost:8501;
}
```

#### OAuth2 Proxy (Recommended for Enterprise)

```bash
# Deploy oauth2-proxy
docker run -d \
  --name oauth2-proxy \
  -p 4180:4180 \
  quay.io/oauth2-proxy/oauth2-proxy:latest \
  --provider=google \
  --client-id=<CLIENT_ID> \
  --client-secret=<CLIENT_SECRET> \
  --cookie-secret=<COOKIE_SECRET> \
  --email-domain=yourdomain.com \
  --upstream=http://localhost:8501 \
  --http-address=0.0.0.0:4180
```

### Network Security

```bash
# Firewall rules (ufw)
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 443/tcp   # HTTPS
sudo ufw deny 8501/tcp   # Block direct access to Streamlit
sudo ufw enable

# Docker network isolation
docker network create --driver bridge --subnet 172.20.0.0/16 docguard-net
```

### Container Security

```dockerfile
# Non-root user
RUN useradd -m -u 1000 docguard
USER docguard

# Read-only filesystem (where possible)
docker run --read-only --tmpfs /tmp docguard:latest

# Security scanning
docker scan docguard:latest
trivy image docguard:latest
```

---

## Monitoring & Logging

### Application Logs

```bash
# Docker Compose
docker-compose logs -f --tail=100

# Kubernetes
kubectl logs -f deployment/docguard -n docguard

# Local/systemd
journalctl -u docguard -f
```

### Health Checks

```bash
# HTTP health check
curl -f http://localhost:8501 || exit 1

# Docker health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -f http://localhost:8501 || exit 1
```

### Prometheus Metrics (Advanced)

Add metrics exporter sidecar:

```yaml
# Kubernetes sidecar
- name: metrics-exporter
  image: prom/statsd-exporter:latest
  ports:
  - containerPort: 9102
```

### Logging Stack (ELK)

```bash
# Filebeat configuration
filebeat.inputs:
- type: docker
  containers.ids:
    - '*'
  processors:
  - add_docker_metadata: ~

output.elasticsearch:
  hosts: ["elasticsearch:9200"]
```

---

## Backup & Disaster Recovery

### Container Images

```bash
# Save image
docker save docguard:latest | gzip > docguard-backup.tar.gz

# Load image
docker load < docguard-backup.tar.gz
```

### Configuration Backup

```bash
# Backup configuration
tar -czf docguard-config-$(date +%Y%m%d).tar.gz \
  docker-compose.yml \
  .env \
  app/.streamlit/config.toml

# Restore
tar -xzf docguard-config-20240115.tar.gz
```

### Disaster Recovery Plan

1. **Image Registry**: Store images in multiple registries (Docker Hub, ECR, GCR)
2. **Configuration Management**: Version control all configs in Git
3. **Infrastructure as Code**: Use Terraform/CloudFormation for cloud deployments
4. **Automated Backups**: Daily snapshots of configurations and images
5. **Recovery Time Objective (RTO)**: < 30 minutes
6. **Recovery Point Objective (RPO)**: < 1 hour

---

## Scaling Strategies

### Horizontal Scaling

#### Docker Compose (Limited)

```bash
docker-compose up -d --scale frontend=3
```

#### Kubernetes (HPA)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: docguard-hpa
  namespace: docguard
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: docguard
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

### Vertical Scaling

```bash
# Increase container resources
docker run --memory="32g" --cpus="16" docguard:latest

# Kubernetes
kubectl set resources deployment docguard \
  --limits=cpu=16,memory=32Gi \
  --requests=cpu=8,memory=16Gi \
  -n docguard
```

### Load Balancing

```nginx
upstream docguard_backend {
    least_conn;
    server docguard-1:8501;
    server docguard-2:8501;
    server docguard-3:8501;
}

server {
    listen 80;
    location / {
        proxy_pass http://docguard_backend;
    }
}
```

---

## Troubleshooting

### Common Issues

**Issue**: Container fails to start

```bash
# Check logs
docker logs docguard

# Common causes:
# - Missing environment variables
# - Port already in use
# - Insufficient resources

# Solutions:
docker-compose down
docker-compose up --build
```

**Issue**: Out of memory

```bash
# Increase memory limit
docker run --memory="16g" docguard:latest

# Reduce workers
MAX_WORKERS=2

# Enable throughput mode
THROUGHPUT_MODE=true
```

**Issue**: Slow processing

```bash
# Check CPU usage
docker stats

# Solutions:
# - Increase MAX_WORKERS
# - Enable THROUGHPUT_MODE
# - Reduce OCR_MAX_IMAGES_PER_DOC
# - Lower OCR_RENDER_SCALE
```

**Issue**: Application not accessible

```bash
# Check port binding
docker ps
netstat -tuln | grep 8501

# Check firewall
sudo ufw status
sudo iptables -L

# Test connectivity
curl http://localhost:8501
telnet localhost 8501
```

### Debug Mode

```bash
# Enable verbose logging
VERBOSE_LOGGING=true docker-compose up

# Access container shell
docker exec -it docguard bash

# Check spaCy model
python -c "import spacy; nlp = spacy.load('en_core_web_sm'); print('OK')"

# Check PaddleOCR
python -c "from paddleocr import PaddleOCR; ocr = PaddleOCR(lang='en'); print('OK')"
```

---

## Performance Benchmarks

### Reference Metrics

| Environment | Files/Min | CPU Usage | Memory Usage |
|-------------|-----------|-----------|--------------|
| **Local (4 core, 8GB)** | 15-20 | 80% | 4-6GB |
| **Docker (4 core, 8GB)** | 12-18 | 75% | 5-7GB |
| **Kubernetes (8 core, 16GB)** | 40-60 | 60% | 10-14GB |

### Optimization Tips

1. **Enable Throughput Mode**: 3-5x faster for non-OCR workloads
2. **Tune Workers**: Match CPU cores for optimal parallelism
3. **Reduce OCR Load**: Lower `OCR_MAX_IMAGES_PER_DOC` and `OCR_RENDER_SCALE`
4. **Cache Size**: Increase `MAX_CACHE_ITEMS` for repeated documents
5. **Network**: Use local storage, avoid network-mounted volumes

---

## Support & Maintenance

### Update Strategy

```bash
# Pull latest code
git pull origin main

# Rebuild containers
docker-compose down
docker-compose build --no-cache
docker-compose up -d

# Verify
docker-compose ps
curl http://localhost:8501
```

### Rollback

```bash
# Docker Compose
docker-compose down
git checkout <previous-commit>
docker-compose up -d --build

# Kubernetes
kubectl rollout undo deployment/docguard -n docguard
kubectl rollout status deployment/docguard -n docguard
```

---

## Contact & Support

For deployment assistance:
- **GitHub Issues**: [Report deployment issues](https://github.com/nowusman/DocGuard/issues)
- **Documentation**: [README.md](README.md)

---

<p align="center">
  <strong>DocGuard Deployment Guide</strong><br>
  Last Updated: 2024-12-23
</p>

