# Deployment Guide - Infrastructure Documentation Collection

This guide covers deploying the infrastructure documentation collection system using Jenkins CI/CD with Docker containerization.

## Architecture Overview

```
Jenkins Pipeline → Docker Build → Registry Push → Docker Compose Deploy → Scheduled Execution
```

- **Build Agent**: jenkins-build-agent (label: 'docker')
- **Registry**: registry.maxseiner.casa
- **Deployment**: Docker Compose with volume mounts
- **Schedule**: Daily at 2 AM (configurable via Jenkinsfile cron trigger)

## Prerequisites

### 1. Jenkins Setup

- Jenkins controller with Docker-enabled build agent
- Build agent with label `docker`
- Docker registry credentials configured in Jenkins

### 2. Required Credentials in Jenkins

Create the following credential in Jenkins (Manage Jenkins → Credentials):

**Credential ID**: `docker-registry`
- **Type**: Username with password
- **Username**: Your registry username
- **Password**: Your registry password
- **ID**: `docker-registry`

### 3. Host System Requirements

The deployment host needs:
- Docker and Docker Compose installed
- SSH keys for accessing infrastructure systems
- Network access to target systems (Docker hosts, Proxmox, etc.)
- Directory structure for persistent data

## Initial Setup

### Step 1: Prepare Host Directories

On your deployment host, create the required directory structure:

```bash
# Create deployment directory
sudo mkdir -p /opt/infrastructure-docs-collector

# Create data directories
mkdir -p ~/infrastructure-docs-data/{rag_output,collected,logs}
```

### Step 2: Configure SSH Access

Ensure SSH keys are available for remote system access:

```bash
# SSH keys should be in ~/.ssh/ with proper permissions
chmod 700 ~/.ssh
chmod 600 ~/.ssh/id_rsa  # Or your specific key file
```

### Step 3: Create Environment Configuration

Copy the example environment file and customize:

```bash
cd /opt/infrastructure-docs-collector
cp .env.example .env
nano .env  # Edit with your specific paths and settings
```

Example `.env` configuration:

```bash
# Registry
REGISTRY=registry.maxseiner.casa

# Logging
LOG_LEVEL=INFO

# Collection toggles
COLLECT_DOCKER=true
COLLECT_PROXMOX=true
COLLECT_SYSTEM_DOCS=true
COLLECT_GRAFANA=false

# Volume paths (adjust to your system)
SSH_KEY_PATH=/home/yourusername/.ssh
CONFIG_PATH=/path/to/infrastructure-docs
RAG_OUTPUT_PATH=/home/yourusername/infrastructure-docs-data/rag_output
COLLECTED_DATA_PATH=/home/yourusername/infrastructure-docs-data/collected
LOGS_PATH=/home/yourusername/infrastructure-docs-data/logs
```

### Step 4: Prepare Configuration Files

Your `infrastructure-docs` directory should contain:

- YAML configuration files defining systems to collect from
- Manual documentation JSON files (optional)
- Any custom service definitions

Example structure:
```
infrastructure-docs/
├── docker-systems.yml
├── proxmox-systems.yml
├── manual/
│   ├── hardware_specifications.json
│   ├── local_dns.json
│   └── network_equipment.json
└── service-definitions/
    └── custom-services.yml
```

## Jenkins Pipeline Configuration

### Step 1: Create Jenkins Pipeline Job

1. In Jenkins, create a new Pipeline job
2. Configure SCM (Git) to point to your repository
3. Set Pipeline script from SCM
4. Jenkins will automatically use the `Jenkinsfile` in the repository

### Step 2: Configure Build Triggers

The pipeline includes a cron trigger for daily execution at 2 AM:

```groovy
triggers {
    cron('0 2 * * *')
}
```

To change the schedule, edit the `Jenkinsfile`:
- `0 2 * * *` - Daily at 2 AM
- `0 */6 * * *` - Every 6 hours
- `0 0 * * 0` - Weekly on Sunday at midnight

### Step 3: Adjust Deployment Path (Optional)

If you want to deploy to a different location than `/opt/infrastructure-docs-collector`, update the `Jenkinsfile`:

```groovy
environment {
    DEPLOY_PATH = '/your/custom/path'
}
```

## Pipeline Stages

The Jenkins pipeline executes these stages:

1. **Checkout**: Clone the repository
2. **Build**: Build Docker image with current code
3. **Push**: Push image to private registry (tagged with build number and 'latest')
4. **Deploy**: Deploy using docker-compose (pulls latest image, restarts container)
5. **Verify**: Check deployment status and show recent logs

## Manual Deployment (Without Jenkins)

For manual deployment or testing:

```bash
# Build image
docker build -t registry.maxseiner.casa/infrastructure-docs-collector:latest .

# Push to registry (optional)
docker push registry.maxseiner.casa/infrastructure-docs-collector:latest

# Deploy with docker-compose
cd /opt/infrastructure-docs-collector
docker-compose up -d

# View logs
docker-compose logs -f

# One-time execution (without docker-compose)
docker run --rm \
  -v ~/.ssh:/root/.ssh:ro \
  -v ./infrastructure-docs:/app/infrastructure-docs:ro \
  -v ./rag_output:/app/rag_output \
  -v ./work/collected:/app/work/collected \
  -v ./logs:/app/logs \
  registry.maxseiner.casa/infrastructure-docs-collector:latest
```

## Monitoring and Troubleshooting

### View Logs

```bash
cd /opt/infrastructure-docs-collector
docker-compose logs -f
```

### Check Container Status

```bash
docker-compose ps
```

### Manual Pipeline Execution

```bash
cd /opt/infrastructure-docs-collector
docker-compose run --rm infrastructure-docs-collector
```

### Common Issues

**Issue**: Cannot connect to remote systems via SSH
- **Solution**: Verify SSH keys are mounted correctly and have proper permissions
- Check: `docker-compose exec infrastructure-docs-collector ls -la /root/.ssh`

**Issue**: Configuration files not found
- **Solution**: Verify CONFIG_PATH in .env points to correct directory
- Check: `docker-compose exec infrastructure-docs-collector ls -la /app/infrastructure-docs`

**Issue**: Permission denied writing output files
- **Solution**: Ensure output directories have correct ownership
- Fix: `sudo chown -R $(id -u):$(id -g) ~/infrastructure-docs-data`

**Issue**: Container exits immediately
- **Solution**: Check logs for errors: `docker-compose logs`
- Verify configuration files are valid YAML

## Integration with MCP Server

The output from this pipeline (`rag_output/rag_data.json`) is consumed by the **InfrastructureDocumentationMCP** sister project.

To integrate:

1. Ensure RAG_OUTPUT_PATH is accessible to the MCP server
2. Configure the MCP server to read from this output location
3. The MCP server will provide conversational AI interface to infrastructure data

## Scheduled Execution Details

The Jenkins pipeline runs automatically via cron trigger, which:

1. Pulls latest code from repository
2. Builds fresh Docker image with updated code
3. Deploys and executes the collection pipeline
4. Container runs once and exits (one-shot execution)
5. Output remains in persistent volumes for MCP server consumption

This ensures infrastructure documentation is continuously updated and available for AI-powered queries.

## Security Considerations

- SSH keys are mounted read-only into containers
- Environment variables in `.env` are not committed to Git
- Registry credentials are managed securely in Jenkins
- All sensitive configuration files are gitignored
- Container runs with minimal required permissions

## Customization

### Resource Limits

To add resource limits, uncomment the deploy section in `docker-compose.yml`:

```yaml
deploy:
  resources:
    limits:
      cpus: '2.0'
      memory: 4G
    reservations:
      cpus: '1.0'
      memory: 2G
```

### Additional Volume Mounts

To mount additional configuration files, add to `docker-compose.yml`:

```yaml
volumes:
  - ./custom-config.yml:/app/custom-config.yml:ro
```

### Network Configuration

If your infrastructure requires specific network access, modify the networks section:

```yaml
networks:
  infrastructure-docs-network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
```

## Support and Documentation

- Project documentation: See `README.md` in repository root
- Schema validation: See `schema/` directory for entity schemas
- Configuration examples: See `infrastructure-docs/` directory
- Sister project: **InfrastructureDocumentationMCP** for MCP server setup
