# src/processors/sub_processors/docker_compose_sub_processor.py
"""
Docker Compose Sub-Processor
Processes docker_compose section from unified collector output.
Creates documents for docker-compose files and their services.
"""

from typing import Dict, Any, List
from datetime import datetime
import yaml
import json

from .base_sub_processor import SubProcessor


class DockerComposeSubProcessor(SubProcessor):
    """
    Processes docker_compose section from unified collector output.

    Creates documents for:
    - Docker Compose files (file-level metadata)
    - Docker Compose services (service definitions)
    """

    def __init__(self, system_name: str, config: Dict[str, Any]):
        """
        Initialize docker compose sub-processor

        Args:
            system_name: System name
            config: Processor configuration
        """
        super().__init__(system_name, config)

    def get_section_name(self) -> str:
        return "docker_compose"

    def process(self, section_data: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Process docker_compose section data

        Args:
            section_data: Docker compose section from unified collector
                Expected structure:
                {
                    "compose_files": [
                        {
                            "file_path": "...",
                            "project_name": "...",
                            "services": {...},
                            ...
                        }
                    ],
                    "total_files": N,
                    "total_services": M
                }

        Returns:
            Tuple of (documents, relationships)
        """
        self.log_start()

        if not self.validate_section_data(section_data):
            return [], []

        compose_files = section_data.get('compose_files', [])

        if not compose_files:
            self.logger.info(f"No compose files found in docker_compose section for {self.system_name}")
            return [], []

        self.logger.info(f"Processing {len(compose_files)} docker-compose files from {self.system_name}")

        documents = []
        relationships = []  # TODO: Will be implemented later

        # Process each compose file
        for compose_file in compose_files:
            # Create file-level document
            file_doc = self._create_compose_file_document(compose_file)
            if file_doc:
                documents.append(file_doc)

            # Create service-level documents
            service_docs = self._create_compose_service_documents(compose_file)
            documents.extend(service_docs)

        self.log_end(len(documents))

        return documents, relationships

    def _create_compose_file_document(self, compose_file: Dict[str, Any]) -> Dict[str, Any]:
        """Create document for a docker-compose file"""

        file_path = compose_file.get('path', compose_file.get('file_path', 'unknown'))

        # Extract project name from path if not provided
        if 'project_name' in compose_file:
            project_name = compose_file['project_name']
        else:
            # Try to extract project name from directory path
            # Example: /path/to/ROMM/docker-compose.yml -> ROMM
            directory = compose_file.get('directory', '')
            if directory:
                project_name = directory.split('/')[-1]
            else:
                project_name = 'unknown'

        services = compose_file.get('services', {})
        networks = compose_file.get('networks', {})
        volumes = compose_file.get('volumes', {})

        # Handle services as either list (collector format) or dict (parsed format)
        if isinstance(services, list):
            service_names = services
            service_count = len(services)
        elif isinstance(services, dict):
            service_names = list(services.keys())
            service_count = len(service_names)
        else:
            service_names = []
            service_count = compose_file.get('service_count', 0)

        # Build content
        content_parts = [
            f"Docker Compose project '{project_name}' on {self.system_name}"
        ]

        if service_names:
            content_parts.append(
                f"defines {service_count} services: {', '.join(service_names[:5])}"
            )
            if len(service_names) > 5:
                content_parts.append(f"and {len(service_names) - 5} more")
        elif service_count > 0:
            content_parts.append(f"defines {service_count} services")

        if networks and len(networks) > 0:
            network_count = len(networks) if isinstance(networks, (list, dict)) else 0
            if network_count > 0:
                content_parts.append(f"with {network_count} custom networks")

        if volumes and len(volumes) > 0:
            volume_count = len(volumes) if isinstance(volumes, (list, dict)) else 0
            if volume_count > 0:
                content_parts.append(f"and {volume_count} volumes.")
            else:
                content_parts.append(".")
        else:
            content_parts.append(".")

        content = " ".join(content_parts)

        # Extract metadata
        metadata = {
            'system_name': self.system_name,
            'file_path': file_path,
            'project_name': project_name,
            'services_count': service_count,
            'networks_count': len(networks) if isinstance(networks, (list, dict)) else 0,
            'volumes_count': len(volumes) if isinstance(volumes, (list, dict)) else 0,
            'last_updated': datetime.now().isoformat()
        }

        document = {
            'id': f'compose_file_{self.system_name}_{project_name}',
            'type': 'docker_compose_file',
            'title': f'Docker Compose: {project_name} on {self.system_name}',
            'content': content,
            'metadata': metadata
        }

        return document

    def _create_compose_service_documents(self, compose_file: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Create documents for each service in a compose file"""

        # Extract project name
        if 'project_name' in compose_file:
            project_name = compose_file['project_name']
        else:
            directory = compose_file.get('directory', '')
            if directory:
                project_name = directory.split('/')[-1]
            else:
                project_name = 'unknown'

        services = compose_file.get('services', {})

        documents = []

        # Only create service documents if we have detailed service configs (dict format)
        # If services is a list, we only have service names without configurations
        if isinstance(services, dict):
            for service_name, service_config in services.items():
                document = self._create_service_document(project_name, service_name, service_config)
                if document:
                    documents.append(document)
        else:
            # Services is a list of names only - skip detailed service documents
            self.logger.debug(f"Skipping service detail documents for {project_name} (only service names available)")

        return documents

    def _create_service_document(self, project_name: str, service_name: str, service_config: Dict[str, Any]) -> Dict[str, Any]:
        """Create document for a single compose service"""

        # Extract service details
        image = service_config.get('image', 'no image specified')
        ports = service_config.get('ports', [])
        volumes = service_config.get('volumes', [])
        environment = service_config.get('environment', {})
        networks = service_config.get('networks', [])
        depends_on = service_config.get('depends_on', [])
        restart = service_config.get('restart', 'no')

        # Build content
        content_parts = [
            f"Docker Compose service '{service_name}' in project '{project_name}' on {self.system_name}"
        ]

        content_parts.append(f"uses image {image}")

        if ports:
            port_list = ', '.join([str(p) for p in ports[:3]])
            content_parts.append(f"with exposed ports: {port_list}")

        if volumes:
            content_parts.append(f"and {len(volumes)} volume mounts")

        if depends_on:
            dep_list = ', '.join(depends_on[:3])
            content_parts.append(f". Depends on: {dep_list}")

        content_parts.append(f". Restart policy: {restart}.")

        content = " ".join(content_parts)

        # Extract metadata
        metadata = {
            'system_name': self.system_name,
            'project_name': project_name,
            'service_name': service_name,
            'image': image,
            'ports': [str(p) for p in ports],
            'volumes_count': len(volumes),
            'environment_vars_count': len(environment),
            'networks': networks if isinstance(networks, list) else [networks] if networks else [],
            'depends_on': depends_on if isinstance(depends_on, list) else [],
            'restart_policy': restart,
            'last_updated': datetime.now().isoformat()
        }

        document = {
            'id': f'compose_service_{self.system_name}_{project_name}_{service_name}',
            'type': 'docker_compose_service',
            'title': f'Compose Service: {service_name} ({project_name})',
            'content': content,
            'metadata': metadata
        }

        return document
