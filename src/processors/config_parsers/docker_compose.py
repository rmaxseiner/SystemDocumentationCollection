# src/processors/config_parsers/docker_compose.py
"""
Docker Compose configuration parser.
Parses docker-compose.yml files and creates relationships to containers.
"""

import yaml
import json
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path

from .base import BaseConfigParser


class DockerComposeParser(BaseConfigParser):
    """
    Parser for Docker Compose configuration files.

    Extracts:
    - Service definitions (names, images, dependencies)
    - Networks and volumes
    - Port mappings
    - Environment variables (count only, not values)

    Creates relationships:
    - CONFIGURES/CONFIGURED_BY to each container defined in compose file
    """

    def __init__(self):
        """Initialize docker compose parser."""
        self.logger = logging.getLogger('docker_compose_parser')

    def can_process(self, service_type: str, config_type: str) -> bool:
        """
        Check if this is a docker-compose configuration file.

        Args:
            service_type: Service type (any)
            config_type: Should be 'docker_compose' or match compose filename patterns

        Returns:
            True if this parser handles this config type
        """
        return (
            config_type == "docker_compose" or
            service_type == "docker-compose"
        )

    def parse(self, content: str, file_path: str) -> Optional[Dict[str, Any]]:
        """
        Parse docker-compose.yml file content.

        Args:
            content: Raw docker-compose YAML content
            file_path: Path to file (for error reporting)

        Returns:
            Dictionary with parsed configuration, or None if parsing fails
        """
        try:
            # Parse YAML
            compose_data = yaml.safe_load(content)
            if not compose_data or not isinstance(compose_data, dict):
                self.logger.warning(f"Invalid docker-compose structure in {file_path}")
                return None

            parsed = {}

            # Extract compose version
            parsed["version"] = compose_data.get("version", "unknown")

            # Extract services
            services = compose_data.get("services", {})
            if not services:
                self.logger.warning(f"No services found in docker-compose file {file_path}")
                return None

            parsed["service_count"] = len(services)
            parsed["service_names"] = list(services.keys())

            # Extract service details
            service_details = []
            for service_name, service_config in services.items():
                if not isinstance(service_config, dict):
                    continue

                service_info = {
                    "name": service_name,
                    "image": service_config.get("image"),
                    "build": service_config.get("build") is not None,
                    "container_name": service_config.get("container_name"),
                    "restart": service_config.get("restart"),
                    "depends_on": list(service_config.get("depends_on", {}).keys()) if isinstance(service_config.get("depends_on"), dict) else service_config.get("depends_on", []),
                    "ports": service_config.get("ports", []),
                    "volumes": len(service_config.get("volumes", [])),
                    "networks": list(service_config.get("networks", {}).keys()) if isinstance(service_config.get("networks"), dict) else service_config.get("networks", []),
                    "environment": len(service_config.get("environment", [])) if isinstance(service_config.get("environment"), list) else len(service_config.get("environment", {}))
                }
                service_details.append(service_info)

            parsed["services"] = service_details

            # Extract networks
            networks = compose_data.get("networks", {})
            if networks:
                parsed["networks"] = list(networks.keys()) if isinstance(networks, dict) else []
                parsed["network_count"] = len(networks)
            else:
                parsed["networks"] = []
                parsed["network_count"] = 0

            # Extract volumes
            volumes = compose_data.get("volumes", {})
            if volumes:
                parsed["volumes"] = list(volumes.keys()) if isinstance(volumes, dict) else []
                parsed["volume_count"] = len(volumes)
            else:
                parsed["volumes"] = []
                parsed["volume_count"] = 0

            return parsed

        except yaml.YAMLError as e:
            self.logger.error(f"YAML parsing error in {file_path}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error parsing docker-compose file {file_path}: {e}")
            return None

    def extract_search_terms(self, parsed_config: Dict[str, Any]) -> List[str]:
        """
        Extract searchable terms from parsed docker-compose configuration.

        Args:
            parsed_config: The parsed configuration dictionary

        Returns:
            List of search terms to add to document
        """
        terms = []

        # Add service names
        if parsed_config.get("service_names"):
            terms.extend(parsed_config["service_names"])

        # Add network names
        if parsed_config.get("networks"):
            terms.extend(parsed_config["networks"])

        # Add volume names
        if parsed_config.get("volumes"):
            terms.extend(parsed_config["volumes"])

        # Add image names (without tags)
        for service in parsed_config.get("services", []):
            if service.get("image"):
                # Extract base image name without tag
                image = service["image"]
                if ":" in image:
                    image = image.split(":")[0]
                terms.append(image)

        # Add docker-compose tag
        terms.append("docker-compose")

        return terms

    def create_relationships(
        self,
        config_id: str,
        parsed_config: Dict[str, Any],
        hostname: str,
        collected_data: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Create CONFIGURES/CONFIGURED_BY relationships to containers.

        This method matches compose services to running containers using:
        - hostname (where compose file is located)
        - compose_project (derived from directory name or label)
        - compose_service (service name from compose file)

        Args:
            config_id: Configuration file entity ID
            parsed_config: Parsed docker-compose data
            hostname: Hostname where compose file is located
            collected_data: Unified JSON data for finding compose project info

        Returns:
            List of CONFIGURES/CONFIGURED_BY relationship pairs
        """
        from ..config_relationship_builder import ConfigRelationshipBuilder

        relationships = []

        if not parsed_config or not parsed_config.get("service_names"):
            self.logger.debug(f"No services in parsed config for {config_id}")
            return relationships

        # We need to determine the compose project name
        # This can come from:
        # 1. The directory name where docker-compose.yml is located
        # 2. The compose_project label in collected_data

        compose_project = self._extract_compose_project(config_id, collected_data, hostname)
        if not compose_project:
            self.logger.warning(
                f"Could not determine compose project for {config_id}, "
                f"cannot create container relationships"
            )
            return relationships

        self.logger.info(
            f"Creating relationships for compose project '{compose_project}' "
            f"with {len(parsed_config['service_names'])} services"
        )

        # Create relationship builder
        rel_builder = ConfigRelationshipBuilder()

        # Create CONFIGURES relationship for each service
        for service_name in parsed_config["service_names"]:
            # Construct container ID
            # Format: container_{hostname}_{container_name}
            # We need to find the actual container name, which might differ from service name

            container_id = self._find_container_id(
                hostname, compose_project, service_name, collected_data
            )

            if container_id:
                # Create bidirectional relationships
                rels = rel_builder.create_configuration_relationships(
                    config_id=config_id,
                    target_id=container_id,
                    target_type='container',
                    config_type='docker_compose',
                    required=True
                )
                relationships.extend(rels)
                self.logger.debug(
                    f"Created relationship: {config_id} CONFIGURES {container_id}"
                )
            else:
                self.logger.debug(
                    f"No running container found for service '{service_name}' "
                    f"in project '{compose_project}' on {hostname}"
                )

        return relationships

    def _extract_compose_project(
        self,
        config_id: str,
        collected_data: Optional[Dict[str, Any]],
        hostname: str
    ) -> Optional[str]:
        """
        Extract compose project name from config_id or collected data.

        The config_id contains the directory name which is the project name.
        Format: config_{hostname}_compose-{project}_{hash}

        Args:
            config_id: Configuration file entity ID
            collected_data: Unified JSON data
            hostname: Hostname

        Returns:
            Compose project name or None
        """
        # Extract project from config_id
        # Format: config_{hostname}_compose-{project}_{hash}
        try:
            parts = config_id.split('_')
            # Find the part that starts with "compose-"
            for part in parts:
                if part.startswith('compose-'):
                    project = part.replace('compose-', '').replace('-', '_').lower()
                    self.logger.debug(f"Extracted compose project '{project}' from config_id")
                    return project
        except Exception as e:
            self.logger.debug(f"Could not extract compose project from config_id: {e}")

        self.logger.warning(f"Could not determine compose project for {config_id}")
        return None

    def _find_container_id(
        self,
        hostname: str,
        compose_project: str,
        service_name: str,
        collected_data: Optional[Dict[str, Any]]
    ) -> Optional[str]:
        """
        Find container ID by matching hostname, compose_project, and service_name.

        This searches rag_data.json to find container documents with matching metadata.

        Args:
            hostname: Hostname where container runs
            compose_project: Compose project name
            service_name: Service name from docker-compose.yml
            collected_data: Unified JSON data (not used, searches rag_data.json instead)

        Returns:
            Container ID (e.g., "container_unraid-server_immich_server") or None
        """
        try:
            # Load rag_data.json to search for container documents
            rag_data_path = Path('rag_output/rag_data.json')
            if not rag_data_path.exists():
                self.logger.debug("rag_data.json not found, cannot match containers")
                return None

            with open(rag_data_path, 'r') as f:
                rag_data = json.load(f)

            # Search container documents
            for doc in rag_data.get('documents', []):
                if doc.get('type') != 'container':
                    continue

                metadata = doc.get('metadata', {})
                doc_hostname = metadata.get('hostname', '')
                doc_compose_project = metadata.get('compose_project', '')
                doc_compose_service = metadata.get('compose_service', '')

                # Match: hostname, compose project (case-insensitive), and service name (exact)
                if (doc_hostname == hostname and
                    doc_compose_project and
                    doc_compose_project.lower() == compose_project.lower() and
                    doc_compose_service == service_name):

                    container_id = doc.get('id')
                    self.logger.debug(
                        f"Found container {container_id} for {compose_project}/{service_name}"
                    )
                    return container_id

            self.logger.debug(
                f"No container found for {hostname}/{compose_project}/{service_name}"
            )

        except Exception as e:
            self.logger.error(
                f"Error finding container for {hostname}/{compose_project}/{service_name}: {e}"
            )

        return None
