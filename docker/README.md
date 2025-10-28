# Docker Deployment Guide

This guide covers deploying the Infrastructure Documentation Collection system as a Docker container.

## Overview

The containerized collector:
- ✅ Connects to systems via SSH to collect infrastructure data
- ✅ Runs on a configurable schedule (default: every 6 hours)
- ✅ Outputs RAG-ready data to a shared volume for MCP server consumption
- ✅ Lightweight and resource-efficient
- ✅ Simple deployment and management

## Architecture

```
┌─────────────────────────────────────┐
│  Docker Host (Proxmox VM or Host)  │
│                                     │
│  ┌──────────────────────────────┐  │
│  │  infra-collector Container  │  │
│  │                              │  │
│  │  • SSH to Docker hosts       │  │
│  │  • Collect data              │  │
│  │  • Process to RAG format     │  │
│  │  • Write to shared volume    │  │
│  └──────────┬───────────────────┘  │
│             │                       │
│  ┌──────────▼───────────────────┐  │
│  │  Shared Volume: rag_output   │◄─┼─── MCP Server reads from here
│  └──────────────────────────────┘  │
└─────────────────────────────────────┘
```

## Prerequisites

1. **Docker & Docker Compose** installed on host system
2. **SSH keys** for accessing target systems (Docker hosts, Proxmox, etc.)
3. **Network access** from container to target systems
4. **Disk space** for collected data (~500MB-2GB depending on infrastructure size)

## Setup Instructions

### 1. Prepare SSH Keys

Create SSH key directory and copy your keys:

```bash
cd docker
mkdir -p ssh-keys

# Option A: Copy existing SSH key
cp ~/.ssh/id_ed25519 ssh-keys/
cp ~/.ssh/id_ed25519.pub ssh-keys/

# Option B: Generate new dedicated key
ssh-keygen -t ed25519 -f ssh-keys/id_ed25519 -C "infra-collector@docker"

# Set proper permissions
chmod 600 ssh-keys/id_ed25519
chmod 644 ssh-keys/id_ed25519.pub
```

### 2. Create SSH Config (Optional but Recommended)

Create `docker/ssh-keys/config` for easier host management:

```bash
cat > ssh-keys/config <<'EOF'
Host *
    StrictHostKeyChecking accept-new
    IdentityFile /app/.ssh/id_ed25519
    ServerAliveInterval 60
    ServerAliveCountMax 3

# Docker Host - Unraid Server
Host unraid-server
    HostName 10.30.0.142
    User your-username
    Port 22

# Docker Host - Server Containers
Host server-containers
    HostName 10.20.0.100
    User your-username
    Port 22

# Proxmox Host
Host proxmox
    HostName 192.168.94.94
    User root
    Port 22
EOF

chmod 600 ssh-keys/config
```

### 3. Copy SSH Keys to Target Hosts

Copy your public key to each target system:

```bash
# For Docker hosts
ssh-copy-id -i ssh-keys/id_ed25519.pub user@10.30.0.142
ssh-copy-id -i ssh-keys/id_ed25519.pub user@10.20.0.100

# For Proxmox
ssh-copy-id -i ssh-keys/id_ed25519.pub root@192.168.94.94

# Test connections
ssh -i ssh-keys/id_ed25519 user@10.30.0.142 "echo 'Connection successful!'"
```

### 4. Configure Schedule (Optional)

Edit `docker-compose.yml` to change collection schedule:

```yaml
environment:
  # Change this to your preferred schedule (cron format)
  - CRON_SCHEDULE=0 */6 * * *  # Every 6 hours (default)
  # - CRON_SCHEDULE=0 0,12 * * *  # Twice daily at midnight and noon
  # - CRON_SCHEDULE=*/30 * * * *  # Every 30 minutes (testing)
```

### 5. Build the Container

```bash
cd docker
docker-compose build
```

## Usage

### Run Once (Testing)

Test the collection without starting the scheduler:

```bash
docker-compose run --rm infra-collector run-once
```

This will:
- Run the collection immediately
- Show all output in your terminal
- Exit when complete
- Clean up the container

### Start Scheduled Collection

Start the container in scheduled mode:

```bash
docker-compose up -d
```

This will:
- Run initial collection immediately
- Start cron daemon
- Continue running and collecting on schedule
- Restart automatically if it fails

### View Logs

```bash
# Follow live logs
docker-compose logs -f infra-collector

# View collection log specifically
docker-compose exec infra-collector tail -f /app/logs/collection.log

# View last 100 lines
docker-compose logs --tail=100 infra-collector
```

### Manual Trigger

Trigger collection manually without waiting for schedule:

```bash
docker-compose exec infra-collector python3 /app/infrastructure_pipeline.py
```

### Interactive Shell

Get a shell inside the container for debugging:

```bash
# Using run (new container)
docker-compose run --rm infra-collector interactive

# Or exec into running container
docker-compose exec infra-collector /bin/bash
```

### Stop Collection

```bash
# Stop container
docker-compose stop

# Stop and remove container
docker-compose down

# Stop and remove everything including volumes
docker-compose down -v
```

## Run Modes

The container supports multiple run modes via the entrypoint:

| Mode | Command | Description |
|------|---------|-------------|
| **schedule** | `docker-compose up -d` | Default. Runs on cron schedule |
| **run-once** | `docker-compose run --rm infra-collector run-once` | Single collection then exit |
| **interactive** | `docker-compose run --rm infra-collector interactive` | Bash shell for debugging |

## Output & Data

### Volumes

The container uses several volumes:

```yaml
volumes:
  - ./ssh-keys:/app/.ssh:ro           # SSH keys (read-only)
  - ../infrastructure-docs:/app/infrastructure-docs:ro  # Config (read-only)
  - rag-data:/app/rag_output          # RAG output (shared with MCP)
  - collected-data:/app/collected_data # Raw collected data
  - ./logs:/app/logs                  # Logs (persisted)
```

### Access Output Data

```bash
# View RAG output files
docker-compose exec infra-collector ls -lh /app/rag_output/

# Copy RAG data out of container
docker cp infra-collector:/app/rag_output/rag_data.json ./

# Inspect RAG data
docker-compose exec infra-collector jq '.documents | length' /app/rag_output/rag_data.json
```

### Sharing with MCP Server

To share the `rag_output` volume with your MCP server, you have two options:

**Option A: Docker Volume (Both containers on same host)**

The MCP server can mount the same Docker volume:

```yaml
# In your MCP docker-compose.yml
volumes:
  - infra-collector_rag-data:/data/rag_output:ro
```

**Option B: Bind Mount (Different hosts or VMs)**

Edit `docker-compose.yml` to use a bind mount:

```yaml
volumes:
  rag-data:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: /mnt/shared/infrastructure/rag_output  # Path accessible by MCP
```

Then mount this path in your MCP server as read-only.

## Troubleshooting

### SSH Connection Issues

```bash
# Test SSH from inside container
docker-compose exec infra-collector ssh -i /app/.ssh/id_ed25519 user@10.30.0.142

# Check SSH key permissions
docker-compose exec infra-collector ls -la /app/.ssh/

# View SSH debug output
docker-compose exec infra-collector ssh -vvv -i /app/.ssh/id_ed25519 user@10.30.0.142
```

### Collection Failures

```bash
# Check container logs
docker-compose logs --tail=100 infra-collector

# Check Python errors
docker-compose exec infra-collector tail -100 /app/logs/collection.log

# Run with debug mode
docker-compose run --rm infra-collector python3 /app/infrastructure_pipeline.py --debug
```

### Cron Not Running

```bash
# Check cron status
docker-compose exec infra-collector ps aux | grep cron

# View crontab
docker-compose exec infra-collector crontab -l

# Check cron logs (Debian/Ubuntu)
docker-compose exec infra-collector tail /var/log/cron.log
```

### Resource Issues

```bash
# Check container resource usage
docker stats infra-collector

# View disk usage
docker-compose exec infra-collector df -h

# Check memory usage
docker-compose exec infra-collector free -h
```

## Advanced Configuration

### Custom Schedule Examples

```bash
# Every hour
CRON_SCHEDULE="0 * * * *"

# Every 4 hours at :30 past the hour
CRON_SCHEDULE="30 */4 * * *"

# Daily at 2 AM
CRON_SCHEDULE="0 2 * * *"

# Business hours only (9 AM - 5 PM, every hour)
CRON_SCHEDULE="0 9-17 * * *"

# Weekdays only at 6 AM
CRON_SCHEDULE="0 6 * * 1-5"
```

### Auto-scan SSH Hosts

Add hosts to automatically scan and add to known_hosts:

```yaml
environment:
  - SSH_HOST_SCAN=10.30.0.142 10.20.0.100 192.168.94.94
```

### Resource Limits

Adjust resource limits in `docker-compose.yml`:

```yaml
deploy:
  resources:
    limits:
      memory: 4G      # Increase for larger infrastructures
      cpus: '2.0'     # More CPUs for faster processing
    reservations:
      memory: 1G
      cpus: '0.5'
```

## Deployment to Proxmox

### Option 1: Deploy to Proxmox Host Directly

If your Proxmox host has Docker installed:

```bash
# SSH to Proxmox
ssh root@192.168.94.94

# Clone repository
git clone <repo-url> /opt/infra-collector
cd /opt/infra-collector/docker

# Setup and start
./setup.sh  # If you create a setup script
docker-compose up -d
```

### Option 2: Deploy to Docker VM on Proxmox

Create a dedicated lightweight VM on Proxmox:

1. **Create VM:**
   - OS: Ubuntu Server 22.04 or Debian 12
   - CPU: 2 cores
   - RAM: 2GB
   - Disk: 20GB

2. **Install Docker:**
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER
   ```

3. **Deploy container:**
   ```bash
   git clone <repo-url> /opt/infra-collector
   cd /opt/infra-collector/docker
   # Setup SSH keys and run docker-compose
   ```

### Option 3: LXC Container on Proxmox (Lightweight)

For minimal resource usage:

```bash
# Create privileged LXC container
pct create 200 local:vztmpl/ubuntu-22.04-standard_22.04-1_amd64.tar.zst \
  --hostname infra-collector \
  --memory 2048 \
  --cores 2 \
  --rootfs local-lvm:20

# Start and enter container
pct start 200
pct enter 200

# Install Docker and deploy
curl -fsSL https://get.docker.com | sh
# Continue with normal setup...
```

## Maintenance

### Update Container

```bash
cd docker

# Pull latest code
git pull

# Rebuild and restart
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### Backup

```bash
# Backup volumes
docker run --rm \
  -v infra-collector_rag-data:/data \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/rag-data-$(date +%Y%m%d).tar.gz -C /data .

# Backup configuration
tar czf config-backup-$(date +%Y%m%d).tar.gz ../infrastructure-docs/
```

### Monitor

```bash
# Setup log rotation for collection.log
cat > docker/logs/logrotate.conf <<'EOF'
/app/logs/collection.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
}
EOF
```

## Security Best Practices

1. **SSH Keys:**
   - ✅ Use dedicated SSH key for collector (not your personal key)
   - ✅ Mount SSH keys as read-only (`:ro`)
   - ✅ Never commit keys to git
   - ✅ Use SSH config with proper permissions (600)

2. **Container Security:**
   - ✅ Use latest Python base image
   - ✅ Don't run as root (removed from Dockerfile to keep it simple)
   - ✅ Limit container resources
   - ✅ Keep container updated

3. **Network:**
   - ✅ Use private networks when possible
   - ✅ Firewall rules to limit access
   - ✅ Consider using SSH bastion/jump host

4. **Secrets:**
   - ✅ Use Docker secrets for sensitive data
   - ✅ Never log sensitive information
   - ✅ Rotate SSH keys periodically

## Integration with MCP Server

Example MCP server integration (add to MCP's docker-compose.yml):

```yaml
services:
  infra-mcp:
    image: your-mcp-server:latest
    volumes:
      # Read from same volume as collector
      - infra-collector_rag-data:/data/rag_output:ro
    depends_on:
      - infra-collector
    networks:
      - infra-net

networks:
  infra-net:
    external: true
    name: docker_infra-net
```

## Support

For issues or questions:
- Check logs: `docker-compose logs -f`
- Review CLAUDE.md in project root
- Check GitHub issues (if applicable)
