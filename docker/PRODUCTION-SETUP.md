# Production Deployment to server-containers

This guide covers deploying the infrastructure collector to your production server following your standard conventions.

## Your Standard Pattern

```
~/dockerhome/
├── docker-compose.yml          # Main compose file with all services
├── config/
│   └── <service-name>/        # Config files for each service
└── .env                        # Environment variables

/mnt/docker/<service-name>/     # Large data/volumes
```

## Production Setup Steps

### 1. Prepare Directories on server-containers

```bash
# On server-containers
ssh server-containers

# Create config directory
mkdir -p ~/dockerhome/config/infrastructure-collector/ssh-keys

# Create data directories
mkdir -p /mnt/docker/infrastructure-collector/rag_output
mkdir -p /mnt/docker/infrastructure-collector/collected_data

# Set permissions
chmod 700 ~/dockerhome/config/infrastructure-collector/ssh-keys
```

### 2. Setup SSH Keys

```bash
# On server-containers
cd ~/dockerhome/config/infrastructure-collector/ssh-keys

# Option A: Generate new dedicated key
ssh-keygen -t ed25519 -f id_ed25519 -C "infra-collector@server-containers"

# Option B: Copy existing key
# scp ~/.ssh/id_ed25519* server-containers:~/dockerhome/config/infrastructure-collector/ssh-keys/

# Set permissions
chmod 600 id_ed25519
chmod 644 id_ed25519.pub
```

### 3. Create SSH Config

```bash
# On server-containers
cat > ~/dockerhome/config/infrastructure-collector/ssh-keys/config <<'EOF'
Host *
    StrictHostKeyChecking accept-new
    IdentityFile /app/.ssh/id_ed25519
    ServerAliveInterval 60
    ServerAliveCountMax 3

# Unraid Server
Host unraid-server
    HostName 10.30.0.142
    User your-username
    Port 22

# Proxmox
Host proxmox
    HostName 192.168.94.94
    User root
    Port 22

# Add other hosts as needed...
EOF

chmod 600 ~/dockerhome/config/infrastructure-collector/ssh-keys/config
```

### 4. Copy Public Key to Target Hosts

```bash
# From server-containers
ssh-copy-id -i ~/dockerhome/config/infrastructure-collector/ssh-keys/id_ed25519.pub user@10.30.0.142
ssh-copy-id -i ~/dockerhome/config/infrastructure-collector/ssh-keys/id_ed25519.pub root@192.168.94.94

# Test connections
ssh -i ~/dockerhome/config/infrastructure-collector/ssh-keys/id_ed25519 user@10.30.0.142 "echo Success"
```

### 5. Add Service to docker-compose.yml

```bash
# On server-containers
cd ~/dockerhome
nano docker-compose.yml
```

Add the service from `docker-compose.production.yml` to your main compose file.

**Important decisions:**
- **Build from GitHub** (auto-pull latest code) or
- **Use local registry** (more control, faster startup)

For registry approach:
```bash
# On your dev machine, build and push to your registry
cd docker
docker build -t server-containers:5000/infra-collector:latest -f Dockerfile ..
docker push server-containers:5000/infra-collector:latest
```

### 6. Deploy the Service

```bash
# On server-containers
cd ~/dockerhome

# Pull/build the image
docker-compose pull infra-collector
# or
docker-compose build infra-collector

# Test run (once)
docker-compose run --rm infra-collector run-once

# If successful, start scheduled collection
docker-compose up -d infra-collector

# View logs in real-time
docker-compose logs -f infra-collector
```

### 7. Verify in Graylog

- Open Graylog at your Graylog URL
- Search for: `tag:infra-collector`
- You should see collection logs

### 8. Verify Output Data

```bash
# Check RAG output
ls -lh /mnt/docker/infrastructure-collector/rag_output/

# View RAG data structure
docker-compose exec infra-collector jq '.documents | length' /app/rag_output/rag_data.json

# Check collected data
ls -lh /mnt/docker/infrastructure-collector/collected_data/
```

## Monitoring

### Check Status

```bash
# Container status
docker-compose ps infra-collector

# Health check
docker-compose ps --filter "name=infra-collector" --format "{{.Status}}"

# Recent logs
docker-compose logs --tail=100 infra-collector
```

### Manual Trigger

```bash
# Trigger collection manually
docker-compose exec infra-collector python3 /app/infrastructure_pipeline.py
```

### Check Cron Schedule

```bash
# View configured cron job
docker-compose exec infra-collector crontab -l

# Check if cron is running
docker-compose exec infra-collector ps aux | grep cron
```

## Updating

### Update from Git

If using GitHub build:
```bash
docker-compose down infra-collector
docker-compose build --no-cache infra-collector
docker-compose up -d infra-collector
```

### Update from Registry

If using local registry:
```bash
# On dev machine: build and push new version
docker build -t server-containers:5000/infra-collector:latest -f docker/Dockerfile .
docker push server-containers:5000/infra-collector:latest

# On server-containers: pull and restart
docker-compose pull infra-collector
docker-compose up -d infra-collector
```

## Backup

### Backup SSH Keys

```bash
tar czf ~/backups/infra-collector-ssh-$(date +%Y%m%d).tar.gz \
  -C ~/dockerhome/config/infrastructure-collector ssh-keys
```

### Backup RAG Data

```bash
tar czf ~/backups/infra-collector-rag-$(date +%Y%m%d).tar.gz \
  -C /mnt/docker/infrastructure-collector rag_output
```

## Troubleshooting

### SSH Connection Issues

```bash
# Test SSH from inside container
docker-compose exec infra-collector ssh -vvv user@10.30.0.142

# Check SSH key permissions
docker-compose exec infra-collector ls -la /app/.ssh/
```

### Collection Failures

```bash
# View detailed logs in Graylog
# Search: tag:infra-collector AND level:error

# Or check last run in container
docker-compose exec infra-collector tail -100 /app/logs/collection.log 2>/dev/null || echo "No local logs (using Graylog)"
```

### Disk Space

```bash
# Check /mnt/docker/ usage
du -sh /mnt/docker/infrastructure-collector/*

# Cleanup old collected data if needed
docker-compose exec infra-collector find /app/collected_data -type f -mtime +30 -delete
```

## Integration with MCP Server

The RAG output is available at:
- **Host path:** `/mnt/docker/infrastructure-collector/rag_output/rag_data.json`
- **Container path:** `/app/rag_output/rag_data.json`

Your MCP server can mount this as read-only:
```yaml
# In MCP service definition
volumes:
  - /mnt/docker/infrastructure-collector/rag_output:/data/rag_output:ro
```

## Directory Structure (Production)

```
server-containers
├── ~/dockerhome/
│   ├── docker-compose.yml
│   └── config/
│       └── infrastructure-collector/
│           └── ssh-keys/              # SSH keys (manual config)
│               ├── id_ed25519
│               ├── id_ed25519.pub
│               └── config
│
└── /mnt/docker/
    └── infrastructure-collector/
        ├── rag_output/                # RAG data (auto-generated)
        │   └── rag_data.json
        └── collected_data/            # Raw data (auto-generated)
```

## Logs

All logs go to **Graylog** at `10.20.0.83:12201` with tag `infra-collector`.

No local log files are kept in production (saves disk space).
