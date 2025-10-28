# Docker Quick Start Guide

## Initial Setup

```bash
cd docker

# Run setup script
./setup.sh

# Or manually:
mkdir -p ssh-keys logs
cp ~/.ssh/id_ed25519* ssh-keys/
chmod 600 ssh-keys/id_ed25519

# Copy SSH key to target hosts
ssh-copy-id -i ssh-keys/id_ed25519.pub user@your-host
```

## Common Commands

### First Time / Testing

```bash
# Build the container
docker-compose build

# Test run (once)
docker-compose run --rm infra-collector run-once

# Start scheduled collection
docker-compose up -d
```

### Daily Operations

```bash
# View logs (live)
docker-compose logs -f

# Manual trigger
docker-compose exec infra-collector python3 /app/infrastructure_pipeline.py

# Check status
docker-compose ps

# Restart
docker-compose restart

# Stop
docker-compose down
```

### Debugging

```bash
# Shell access
docker-compose exec infra-collector /bin/bash

# Test SSH connection
docker-compose exec infra-collector ssh user@target-host

# Check cron
docker-compose exec infra-collector crontab -l

# View collection log
docker-compose exec infra-collector tail -f /app/logs/collection.log
```

### Data Access

```bash
# List output files
docker-compose exec infra-collector ls -lh /app/rag_output/

# View RAG data summary
docker-compose exec infra-collector jq '.documents | length' /app/rag_output/rag_data.json

# Copy data out
docker cp infra-collector:/app/rag_output/rag_data.json ./
```

## Configuration

### Change Schedule

Edit `docker-compose.yml`:

```yaml
environment:
  # Every 6 hours (default)
  - CRON_SCHEDULE=0 */6 * * *

  # Or: Daily at 2 AM
  # - CRON_SCHEDULE=0 2 * * *

  # Or: Every hour
  # - CRON_SCHEDULE=0 * * * *
```

Then restart:
```bash
docker-compose down && docker-compose up -d
```

### Add SSH Hosts

Edit `ssh-keys/config`:

```
Host my-docker-host
    HostName 10.30.0.142
    User myuser
    Port 22
```

No restart needed - changes take effect on next run.

## Troubleshooting

### SSH Issues
```bash
# Test from inside container
docker-compose exec infra-collector ssh -vvv user@host

# Check key permissions
docker-compose exec infra-collector ls -la /app/.ssh/
```

### Collection Errors
```bash
# Check logs
docker-compose logs --tail=100 infra-collector

# Check collection log
docker-compose exec infra-collector tail -100 /app/logs/collection.log
```

### Container Won't Start
```bash
# Check container status
docker-compose ps

# View startup logs
docker-compose logs infra-collector

# Rebuild
docker-compose build --no-cache
```

## File Locations

| Path | Description |
|------|-------------|
| `ssh-keys/` | SSH keys and config |
| `logs/` | Collection logs |
| `/app/rag_output/` | RAG data (in container) |
| `/app/collected_data/` | Raw data (in container) |

## Integration with MCP Server

The `rag_output` volume is shared and can be mounted read-only in your MCP server:

```yaml
# MCP docker-compose.yml
volumes:
  - infra-collector_rag-data:/data/rag_output:ro
```

## Quick Reference

| Command | Purpose |
|---------|---------|
| `docker-compose up -d` | Start scheduled collection |
| `docker-compose down` | Stop collector |
| `docker-compose logs -f` | View live logs |
| `docker-compose restart` | Restart collector |
| `docker-compose run --rm infra-collector run-once` | Run once for testing |
| `docker-compose exec infra-collector bash` | Get shell in container |

## Support

See `README.md` for full documentation.
