# System Documentation Collection

Infrastructure documentation collection system for homelab environments.

## Overview

This project contains the collection engine that gathers configuration files, 
system states, and infrastructure data from various homelab systems.

## Components

- **Collectors**: System-specific data collection modules
- **Connectors**: Connection handlers for SSH, APIs, Docker
- **Processors**: Data sanitization and formatting
- **Docker**: Containerized deployment configuration

## Deployment

The collection system runs as a Docker container with scheduled collection tasks.

See `/docker/docker-compose.yml` for deployment configuration.
