# Deployment Guide

## Production Setup

### Docker Image
- **Registry**: GitHub Container Registry (GHCR)
- **Image URL**: `ghcr.io/millad90s/addeustch:master`
- **Build Command**:
  ```bash
  docker build -t ghcr.io/millad90s/addeustch:master .
  ```
- **Push Command**:
  ```bash
  docker push ghcr.io/millad90s/addeustch:master
  ```

### Services

#### Main Application
- **Image**: `ghcr.io/millad90s/addeustch:master`
- **Port**: `8080:8000` (host:container)
- **Config**: `.env.prod`

#### MinIO (Object Storage)
- **Image**: `minio/minio:latest`
- **API Port**: `9000:9000`
- **Console Port**: `9001:9001`
- **Data Volume**: `minio-data`

---

## Quick Start

### 1. Configure Environment

Create `.env.prod`:
```env
# App Config
GOOGLE_CLIENT_ID=your_client_id
GOOGLE_CLIENT_SECRET=your_client_secret
ADMIN_EMAILS=admin@example.com
SESSION_SECRET=generated_secret

# MinIO Config
MINIO_ACCESS_KEY=secure-key-here
MINIO_SECRET_KEY=secure-secret-here
MINIO_BUCKET=flashcard-ads
MINIO_PUBLIC_URL=https://minio.yourdomain.com

# AI Provider
AI_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_key

# Enrichment Service
ENRICHMENT_ENDPOINT=http://enrichment-service:7000
ENRICHMENT_ENABLED=true
```

### 2. Start Services

```bash
# Build and start
docker-compose -f docker-compose.prod.yml up -d

# Check status
docker-compose -f docker-compose.prod.yml ps
```

### 3. Initialize MinIO

```bash
# Create bucket
docker exec minio mc alias set local http://localhost:9000 \
  $MINIO_ACCESS_KEY $MINIO_SECRET_KEY
docker exec minio mc mb local/flashcard-ads

# Make bucket public
docker exec minio mc anonymous set public local/flashcard-ads
```

### 4. Access Services

- **App**: `http://localhost:8080`
- **MinIO Console**: `http://localhost:9001`
- **MinIO API**: `http://localhost:9000`

---

## Volumes

| Volume | Purpose | Mount |
|--------|---------|-------|
| `./data` | Database & app data | `/data` |
| `minio-data` | MinIO object storage | `/data` in minio |

---

## Health Checks

- MinIO includes health checks (30s interval, 3 retries)
- Web app depends on MinIO being healthy

---

## Upgrade Image

```bash
# Pull latest
docker pull ghcr.io/millad90s/addeustch:master

# Restart services
docker-compose -f docker-compose.prod.yml down
docker-compose -f docker-compose.prod.yml up -d
```

---

## Monitoring

```bash
# View logs
docker-compose -f docker-compose.prod.yml logs -f web
docker-compose -f docker-compose.prod.yml logs -f minio

# Check container health
docker ps --format "table {{.Names}}\t{{.Status}}"
```

---

## Backup

```bash
# Backup database
docker exec flashcards cp /data/flashcards.db /data/flashcards.db.backup

# Backup MinIO data
docker exec minio mc mirror local/flashcard-ads ./backups/flashcard-ads
```
