# System Documentation Collection

Infrastructure documentation collection system for homelab environments.

## Overview

This project contains the collection engine that gathers configuration files,
system states, and infrastructure data from various homelab systems. It processes
this data into RAG-ready format for consumption by the InfrastructureDocumentationMCP
server.

## Components

- **Collectors**: System-specific data collection modules
- **Connectors**: Connection handlers for SSH, APIs, Docker
- **Processors**: Data sanitization and formatting
- **Validators**: Schema and relationship validation
- **Docker**: Containerized deployment configuration

## Usage

### Basic Commands

```bash
# Full pipeline (collection + processing)
python3 infrastructure_pipeline.py full-pipeline

# Full pipeline with validation
python3 infrastructure_pipeline.py full-pipeline --validate

# Process only with validation
python3 infrastructure_pipeline.py process --validate

# Collect only
python3 infrastructure_pipeline.py collect
```

### Schema Validation

Validate generated data against entity schemas:

```bash
# Validate as part of pipeline
python3 infrastructure_pipeline.py process --validate

# Validate specific entity type
python3 tests/test_entity_schema.py schema/physical_server_entity.yml

# Validate relationships
python3 tests/test_relationships.py
```

## Output

The pipeline generates:
- `rag_output/rag_data.json` - Structured entity data
- `rag_output/intermediate/` - Processing artifacts
- `work/collected/` - Raw collection data

## Deployment

The collection system runs as a Docker container with scheduled collection tasks.

See `/docker/docker-compose.yml` for deployment configuration.
