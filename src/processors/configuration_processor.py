# src/processors/configuration_processor.py
"""
Configuration Processor
Processes configuration files from infrastructure-docs/services directory and integrates them into RAG data.
Handles both single-service and multi-service configuration files with structured metadata.
"""

import json
import yaml
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import shutil
import mimetypes

from .base_processor import BaseProcessor, ProcessingResult
from .config_parsers.registry import registry
from .config_relationship_builder import ConfigRelationshipBuilder

# Maximum file size for parsing (1MB)
MAX_PARSE_SIZE = 1024 * 1024


class ConfigurationProcessor(BaseProcessor):
    """
    Processes configuration files and creates structured metadata documents.
    Supports single-service configs and multi-service breakdown (Docker Compose, Prometheus).
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)

        # Configuration
        self.services_dir = Path(config.get('services_dir', 'infrastructure-docs/services'))
        self.output_dir = Path(config.get('output_dir', 'rag_output'))
        self.config_files_dir = self.output_dir / 'configuration_files'

        # Relationship builder
        self.rel_builder = ConfigRelationshipBuilder()

        # Multi-service configuration handlers (special files requiring additional processing)
        self.special_file_handlers = {
            'prometheus.yml': self._process_prometheus_config_special,
            'docker-compose.yml': self._process_docker_compose_special,
            'docker-compose.yaml': self._process_docker_compose_special,
        }

        # Authentik config files (placeholder for future)
        self.authentik_patterns = ['authentik']

        # Configuration type mappings
        self.config_type_mappings = {
            'prometheus': 'monitoring',
            'grafana': 'monitoring',
            'alertmanager': 'alerting',
            'blackbox-exporter': 'monitoring',
            'nginx-proxy-manager': 'proxy',
            'home-assistant': 'automation',
            'gitea': 'version_control',
            'homepage': 'dashboard'
        }

    def validate_config(self) -> bool:
        """Validate processor configuration"""
        if not self.services_dir or not self.services_dir.exists():
            self.logger.error(f"Services directory does not exist: {self.services_dir}")
            return False

        self.logger.info("Configuration processor configuration validated")
        return True

    def process(self, collected_data: Dict[str, Any] = None) -> ProcessingResult:
        """
        Process configuration files from services directory

        Args:
            collected_data: Unified collected data (used by parsers for relationship creation)

        Returns:
            ProcessingResult: Contains processed configuration results
        """
        try:
            # Store collected_data for use by parsers
            self.collected_data = collected_data or {}

            self.logger.info("Starting configuration file processing")

            # Create output directories
            output_path = self._create_output_directory(str(self.output_dir))
            self.config_files_dir.mkdir(parents=True, exist_ok=True)

            # Discover service directories
            service_dirs = self._discover_service_directories()

            if not service_dirs:
                self.logger.warning("No service directories found")
                return ProcessingResult(
                    success=True,
                    data={'services_processed': 0, 'message': 'No services found'},
                    metadata={'processor_type': 'configuration'}
                )

            self.logger.info(f"Found {len(service_dirs)} service directories")

            # Process each service directory
            all_documents = []
            all_relationships = []
            processed_services = 0

            for service_dir in service_dirs:
                try:
                    service_docs, service_rels = self._process_service_directory(service_dir)
                    if service_docs:
                        all_documents.extend(service_docs)
                        all_relationships.extend(service_rels)
                        processed_services += 1
                except Exception as e:
                    self.logger.error(f"Failed to process service directory {service_dir}: {e}")
                    continue

            # Process docker-compose files from collected data
            compose_docs, compose_rels = self._process_docker_compose_from_collected_data(self.collected_data)
            all_documents.extend(compose_docs)
            all_relationships.extend(compose_rels)

            # Update rag_data.json with configuration documents and relationships
            rag_data_file = self._update_rag_data_json(all_documents, all_relationships, output_path)

            self.logger.info(f"Configuration processing completed: {len(all_documents)} documents from {processed_services} services")

            return ProcessingResult(
                success=True,
                data={
                    'rag_data_file': str(rag_data_file),
                    'services_processed': processed_services,
                    'documents_generated': len(all_documents),
                    'config_files_directory': str(self.config_files_dir),
                    'output_directory': str(output_path)
                },
                metadata={
                    'processor_type': 'configuration',
                    'services_processed': processed_services,
                    'documents_generated': len(all_documents),
                    'config_files_directory': str(self.config_files_dir)
                }
            )

        except Exception as e:
            self.logger.exception("Configuration processing failed")
            return ProcessingResult(
                success=False,
                error=str(e),
                metadata={'processor_type': 'configuration'}
            )

    def _discover_service_directories(self) -> List[Path]:
        """Discover service directories in services directory"""
        service_dirs = []

        if not self.services_dir.exists():
            return service_dirs

        # Each service should have its own directory
        for item in self.services_dir.iterdir():
            if item.is_dir():
                service_dirs.append(item)

        self.logger.debug(f"Discovered {len(service_dirs)} service directories")
        return service_dirs

    def _process_service_directory(self, service_dir: Path) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Process a single service directory containing configuration files

        Returns:
            Tuple of (documents, relationships)
        """
        self.logger.debug(f"Processing service directory: {service_dir}")

        documents = []
        relationships = []
        service_name = service_dir.name

        # Process each subdirectory (container/service instance)
        for container_dir in service_dir.iterdir():
            if not container_dir.is_dir() or container_dir.name == '__pycache__':
                continue

            # Load collection metadata from container directory
            metadata_file = container_dir / 'collection_metadata.yml'
            collection_metadata = {}
            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r') as f:
                        collection_metadata = yaml.safe_load(f) or {}
                except Exception as e:
                    self.logger.warning(f"Failed to load metadata for {container_dir.name}: {e}")

            # Extract host and service info from metadata with fallback logic
            host = collection_metadata.get('collection_host')
            if not host or host == 'unknown':
                # Log warning about missing host metadata
                self.logger.warning(
                    f"No collection_host found in metadata for {container_dir.name}, "
                    f"using service_name as fallback"
                )
                host = service_name

            container_name = collection_metadata.get('container_name', container_dir.name)
            service_type = collection_metadata.get('service_type', service_name)

            self.logger.debug(
                f"Processing container {container_name} on host {host} (service_type: {service_type})"
            )

            # Process configuration files in this container directory
            config_files = self._get_config_files(container_dir)

            for config_file in config_files:
                # Skip metadata files
                if config_file.name == 'collection_metadata.yml':
                    continue

                doc, rels = self._process_config_file(
                    config_file,
                    service_name,
                    container_name,
                    host,
                    service_type,
                    collection_metadata
                )
                if doc:
                    documents.append(doc)
                if rels:
                    relationships.extend(rels)

        return documents, relationships

    def _process_docker_compose_from_collected_data(
        self, collected_data: Dict[str, Any]
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Process docker-compose files from collected unified JSON files.

        This reads unified JSON files from work/collected/ and processes
        docker-compose.yml files from the docker_compose section.

        Args:
            collected_data: Not used - reads from files directly

        Returns:
            Tuple of (documents, relationships)
        """
        documents = []
        relationships = []

        # Determine collected data directory
        collected_dir = Path('work/collected')
        if not collected_dir.exists():
            self.logger.warning(f"Collected data directory not found: {collected_dir}")
            return documents, relationships

        self.logger.info("Processing docker-compose files from collected data")

        # Get the parser for docker-compose
        parser = registry.get_parser('docker-compose', 'docker_compose')
        if not parser:
            self.logger.warning("No docker-compose parser available")
            return documents, relationships

        # Find all unified JSON files
        unified_files = list(collected_dir.glob('*_unified.json'))
        if not unified_files:
            self.logger.info("No unified JSON files found")
            return documents, relationships

        self.logger.info(f"Found {len(unified_files)} unified JSON files to check for docker-compose")

        # Process each unified JSON file
        for unified_file in unified_files:
            try:
                with open(unified_file, 'r') as f:
                    unified_data = json.load(f)

                # Extract system name from filename (remove _unified.json)
                system_name = unified_file.stem.replace('_unified', '')

                # Get the data section
                if not unified_data.get('success'):
                    self.logger.debug(f"Skipping unsuccessful collection: {system_name}")
                    continue

                system_data = unified_data.get('data', {})
                if not system_data:
                    continue

                # Check if this system has docker_compose data
                sections = system_data.get('sections', {})
                docker_compose_section = sections.get('docker_compose', {})
                compose_files = docker_compose_section.get('compose_files', [])

                if not compose_files:
                    self.logger.debug(f"No docker-compose files for system {system_name}")
                    continue

                self.logger.info(f"Processing {len(compose_files)} docker-compose files from {system_name}")

                for compose_file_data in compose_files:
                    try:
                        doc, rels = self._process_docker_compose_file(
                            compose_file_data, system_name, system_data, parser
                        )
                        if doc:
                            documents.append(doc)
                        if rels:
                            relationships.extend(rels)

                    except Exception as e:
                        self.logger.error(
                            f"Failed to process docker-compose file from {system_name}: {e}"
                        )
                        continue

            except Exception as e:
                self.logger.error(f"Failed to read unified file {unified_file}: {e}")
                continue

        self.logger.info(
            f"Completed docker-compose processing: {len(documents)} documents, "
            f"{len(relationships)} relationships"
        )

        return documents, relationships

    def _process_docker_compose_file(
        self,
        compose_file_data: Dict[str, Any],
        hostname: str,
        system_data: Dict[str, Any],
        parser
    ) -> tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Process a single docker-compose file from collected data.

        Args:
            compose_file_data: Compose file data from unified JSON
            hostname: Hostname where compose file is located
            system_data: Full system data for relationship matching
            parser: DockerComposeParser instance

        Returns:
            Tuple of (document, relationships)
        """
        # Extract compose file info
        file_path = compose_file_data.get('path', '')
        content = compose_file_data.get('content', '')
        filename = compose_file_data.get('filename', 'docker-compose.yml')
        file_size = compose_file_data.get('file_size', 0)
        directory = compose_file_data.get('directory', '')
        last_modified_timestamp = compose_file_data.get('last_modified_timestamp')

        if not content or content == "REDACTED":
            self.logger.warning(f"No content for docker-compose file at {file_path}")
            return None, []

        # Parse the compose file
        parsed_config = parser.parse(content, file_path)
        if not parsed_config:
            self.logger.warning(f"Failed to parse docker-compose file {file_path}")
            return None, []

        # Save the docker-compose file to output directory
        saved_file_path = self._save_docker_compose_file(
            content=content,
            filename=filename,
            hostname=hostname,
            directory=directory
        )

        # Generate document ID
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        sanitized_name = Path(directory).name.replace('.', '-').replace('/', '-')
        doc_id = f"config_{hostname}_compose-{sanitized_name}_{content_hash[:8]}"

        # Calculate relative path for consistent metadata (like other config files)
        relative_storage_path = str(saved_file_path.relative_to(self.config_files_dir))

        # Build content description
        service_count = parsed_config.get('service_count', 0)
        service_names = parsed_config.get('service_names', [])
        content_description = (
            f"Docker Compose configuration file at {directory}. "
            f"Defines {service_count} services: {', '.join(service_names[:5])}. "
            f"Originally located at {file_path} on {hostname}."
        )

        # Add search terms
        search_terms = parser.extract_search_terms(parsed_config)
        if search_terms:
            content_description += " " + " ".join(search_terms)

        # Build document with 3-tier structure
        document = {
            # Root
            "id": doc_id,
            "type": "configuration_file",

            # Tier 1: Vector Search Content
            "title": f"Docker Compose Configuration - {Path(directory).name}",
            "content": content_description,

            # Tier 2: Summary Metadata
            "metadata": {
                # Identity
                "hostname": hostname,
                "config_name": filename,
                "config_type": "docker_compose",

                # File Information (consistent with other config files - relative paths)
                "file_path": relative_storage_path,  # Relative path in configuration_files directory
                "file_size": file_size,
                "file_format": "yaml",

                # Usage
                "service_name": "docker-compose",
                "container_name": Path(directory).name,
                "configures_type": "container",

                # File Retrieval (consistent with other config files)
                "file_storage_path": relative_storage_path,  # Where file is stored in configuration_files
                "original_host_path": file_path,  # Original location on host server
                "checksum_sha256": content_hash,

                # Parsed configuration
                "parsed_config": parsed_config,

                # Timestamps
                "file_last_modified": (
                    datetime.fromtimestamp(last_modified_timestamp).isoformat()
                    if last_modified_timestamp else None
                ),
                "collected_at": system_data.get('collection_timestamp', datetime.now().isoformat()),
                "last_updated": datetime.now().isoformat()
            },

            # Tier 3: Detailed Information
            "details": {
                "file_info": {
                    "full_path": relative_storage_path,  # Consistent with file_path
                    "original_host_path": file_path,  # Original location on host
                    "size_bytes": file_size,
                    "format": "yaml",
                    "saved_to": str(saved_file_path)
                },
                "storage": {
                    "stored_on_host": hostname,
                    "stored_on_type": "virtual_server",
                    "local_storage_path": str(saved_file_path)
                }
            }
        }

        # Create relationships
        all_relationships = []

        # Storage relationships (STORED_ON / STORES)
        storage_rels = self.rel_builder.create_storage_relationships(
            config_id=doc_id,
            host=hostname,
            file_path=file_path
        )
        all_relationships.extend(storage_rels)

        # Configuration relationships (CONFIGURES / CONFIGURED_BY)
        # Let parser create relationships to containers
        try:
            parser_rels = parser.create_relationships(
                config_id=doc_id,
                parsed_config=parsed_config,
                hostname=hostname,
                collected_data=system_data
            )
            all_relationships.extend(parser_rels)
            self.logger.info(
                f"Created {len(parser_rels)} relationships for docker-compose at {file_path}"
            )
        except Exception as e:
            self.logger.error(
                f"Failed to create relationships for docker-compose {file_path}: {e}"
            )

        return document, all_relationships

    def _get_config_files(self, container_dir: Path) -> List[Path]:
        """Get all configuration files from container directory"""
        config_files = []

        # Common configuration file extensions
        config_extensions = {'.yml', '.yaml', '.json', '.conf', '.ini', '.cfg', '.toml', '.sql'}

        for file_path in container_dir.rglob('*'):
            if (file_path.is_file() and
                (file_path.suffix.lower() in config_extensions or
                 file_path.name in ['Dockerfile', 'docker-compose.yml', 'docker-compose.yaml'])):
                config_files.append(file_path)

        return config_files

    def _process_config_file(self, config_file: Path, service_name: str, container_name: str,
                           host: str, service_type: str, collection_metadata: Dict) -> tuple[Optional[Dict], List[Dict]]:
        """Process a single configuration file

        Returns:
            Tuple of (document, relationships)
        """
        self.logger.debug(f"Processing config file: {config_file}")

        try:
            # Copy file to output directory
            target_path = self._copy_config_file(config_file, host, container_name)

            # Create base document
            document, relationships = self._create_config_file_document(
                config_file, target_path, service_name, container_name, host, service_type, collection_metadata
            )

            # Check if this is a special file requiring additional relationship processing
            if config_file.name in self.special_file_handlers:
                additional_rels = self.special_file_handlers[config_file.name](
                    config_file, document, host, container_name
                )
                relationships.extend(additional_rels)

            return document, relationships

        except Exception as e:
            self.logger.error(f"Failed to process config file {config_file}: {e}")
            return None, []

    def _copy_config_file(self, source_file: Path, host: str, container_name: str) -> Path:
        """Copy configuration file to output directory structure"""
        # Create target directory structure: host/container/filename
        target_dir = self.config_files_dir / host / container_name
        target_dir.mkdir(parents=True, exist_ok=True)

        target_path = target_dir / source_file.name
        shutil.copy2(source_file, target_path)

        return target_path

    def _save_docker_compose_file(self, content: str, filename: str, hostname: str, directory: str) -> Path:
        """
        Save docker-compose file content to output directory structure.

        Args:
            content: Docker-compose file content
            filename: Filename (e.g., docker-compose.yml)
            hostname: Hostname where file is located
            directory: Original directory path (e.g., /root/dockerhome)

        Returns:
            Path to saved file
        """
        # Use directory name as subfolder to differentiate multiple compose files on same host
        # e.g., rag_output/configuration_files/server-containers/docker-compose/dockerhome/docker-compose.yml
        dir_name = Path(directory).name if directory else "default"
        target_dir = self.config_files_dir / hostname / "docker-compose" / dir_name
        target_dir.mkdir(parents=True, exist_ok=True)

        target_path = target_dir / filename

        # Write content to file
        with open(target_path, 'w') as f:
            f.write(content)

        self.logger.info(f"Saved docker-compose file to {target_path}")

        return target_path

    def _create_config_file_document(self, source_file: Path, target_path: Path,
                                      service_name: str, container_name: str, host: str,
                                      service_type: str, collection_metadata: Dict) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Create configuration_file entity document with 3-tier schema

        Returns:
            Tuple of (document, relationships)
        """

        # Generate unique document ID
        content_hash = self._generate_file_hash(source_file)
        sanitized_name = source_file.stem.replace('.', '-')
        doc_id = f"config_{host}_{sanitized_name}_{content_hash[:8]}"

        # Determine configuration type
        config_type = self.config_type_mappings.get(service_type, 'application')

        # Get file metadata
        file_stats = source_file.stat()
        file_size = file_stats.st_size

        # Create relative path for storage
        relative_path = target_path.relative_to(self.config_files_dir)

        # Determine file format
        file_format = source_file.suffix.lstrip('.').lower() or 'txt'
        if file_format not in ['ini', 'yaml', 'json', 'conf', 'env', 'txt', 'xml', 'toml', 'properties']:
            file_format = 'txt'

        # Build content for vector search (description, NOT file content)
        full_path = str(source_file)
        content = self._build_config_content_description(
            source_file.name, config_type, service_type, container_name, host, full_path
        )

        # Build document with 3-tier structure
        document = {
            # Root
            "id": doc_id,
            "type": "configuration_file",

            # Tier 1: Vector Search Content
            "title": f"{service_type.title()} Configuration - {source_file.name}",
            "content": content,

            # Tier 2: Summary Metadata
            "metadata": {
                # Identity
                "hostname": host,
                "config_name": source_file.name,
                "config_type": config_type,

                # File Information
                "file_path": str(relative_path),
                "file_size": file_size,
                "file_format": file_format,

                # Usage (relationships are authoritative)
                "service_name": service_type,
                "container_name": container_name,
                "configures_type": "container",  # Default, may be updated

                # File Retrieval
                "file_storage_path": str(relative_path),
                "checksum_sha256": content_hash,

                # Timestamps
                "file_last_modified": datetime.fromtimestamp(file_stats.st_mtime).isoformat(),
                "collected_at": collection_metadata.get('collection_timestamp', datetime.now().isoformat()),
                "last_updated": datetime.now().isoformat()
            },

            # Tier 3: Detailed Information
            "details": {
                "file_info": {
                    "full_path": full_path,
                    "size_bytes": file_size,
                    "format": file_format
                },
                "storage": {
                    "stored_on_host": host,
                    "stored_on_type": "virtual_server"  # Default assumption
                }
            }
        }

        # Try to parse configuration file if parser available
        parsed_config = None
        parser = registry.get_parser(service_type, config_type)

        # Special handling for docker-compose files
        is_docker_compose = source_file.name in ['docker-compose.yml', 'docker-compose.yaml']
        if is_docker_compose:
            # Override config_type and get docker-compose parser
            config_type = 'docker_compose'
            document["metadata"]["config_type"] = config_type
            parser = registry.get_parser('docker-compose', 'docker_compose')

        if parser:
            try:
                # Read and parse file content
                with open(source_file, 'r', encoding='utf-8', errors='ignore') as f:
                    file_content = f.read()

                parsed_config = parser.parse(file_content, str(source_file))
                if parsed_config:
                    # Check if parser can create full entities (e.g., NPM proxy_host entities)
                    if hasattr(parser, 'create_proxy_host_entity'):
                        try:
                            proxy_host_entity = parser.create_proxy_host_entity(
                                parsed_config,
                                str(source_file)
                            )
                            if proxy_host_entity:
                                # Replace configuration_file document with proxy_host entity
                                document = proxy_host_entity
                                self.logger.info(
                                    f"Created proxy_host entity for {source_file.name}"
                                )
                        except Exception as e:
                            self.logger.warning(
                                f"Failed to create proxy_host entity for {source_file.name}: {e}, "
                                f"falling back to configuration_file"
                            )

                    # If still a configuration_file (not replaced by entity), add parsed data
                    if document["type"] == "configuration_file":
                        # Add parsed data to metadata
                        document["metadata"]["parsed_config"] = parsed_config

                        # Extract and add search terms
                        search_terms = parser.extract_search_terms(parsed_config)
                        if search_terms:
                            # Add search terms to content for better vector search
                            document["content"] += " " + " ".join(search_terms)

                        self.logger.debug(
                            f"Successfully parsed {source_file.name} using {parser.__class__.__name__}"
                        )
                else:
                    self.logger.debug(f"Parser returned no data for {source_file.name}")

            except Exception as e:
                self.logger.warning(f"Failed to parse config file {source_file.name}: {e}")

        # Create relationships
        relationships = []

        # Storage relationships (STORED_ON / STORES)
        storage_rels = self.rel_builder.create_storage_relationships(
            config_id=doc_id,
            host=host,
            file_path=full_path
        )
        relationships.extend(storage_rels)

        # Configuration relationships (CONFIGURES / CONFIGURED_BY)
        # For docker-compose files, let the parser create relationships to multiple containers
        # For other files, create default relationship to the service's container
        if is_docker_compose and parser and parsed_config:
            # Use parser to create relationships to all containers defined in compose file
            try:
                parser_rels = parser.create_relationships(
                    config_id=doc_id,
                    parsed_config=parsed_config,
                    hostname=host,
                    collected_data=self.collected_data
                )
                relationships.extend(parser_rels)
                self.logger.info(
                    f"Created {len(parser_rels)} docker-compose relationships for {source_file.name}"
                )
            except Exception as e:
                self.logger.error(f"Failed to create parser relationships for {source_file.name}: {e}")
        else:
            # Default: create relationship to the service's container
            container_id = f"container_{host}_{container_name}"
            config_rels = self.rel_builder.create_configuration_relationships(
                config_id=doc_id,
                target_id=container_id,
                target_type='container',
                config_type=config_type if not is_docker_compose else 'application_settings',
                required=True
            )
            relationships.extend(config_rels)

        return document, relationships

    def _build_config_content_description(self, filename: str, config_type: str,
                                         service_type: str, container_name: str,
                                         host: str, file_path: str) -> str:
        """Build rich content description for vector search (NO file content)"""

        # Build description
        parts = [
            f"{service_type.title()} configuration file '{filename}'.",
            f"Type: {config_type}.",
            f"Configures {container_name} container on {host}.",
            f"Located at {file_path}."
        ]

        return ' '.join(parts)

    # ====================
    # Special File Handlers (Placeholders)
    # ====================

    def _process_docker_compose_special(self, config_file: Path, document: Dict,
                                       host: str, container_name: str) -> List[Dict[str, Any]]:
        """
        Process docker-compose file to create relationships to all containers it defines.

        TODO: Parse docker-compose.yml to extract service names
        TODO: Create CONFIGURES relationship for each container

        For now, returns empty list (placeholder).

        Args:
            config_file: Path to docker-compose file
            document: Base config document
            host: Host where compose file runs
            container_name: Container name (service directory name)

        Returns:
            List of additional relationships
        """
        self.logger.info(f"TODO: Process docker-compose file {config_file.name} for container relationships")
        # Placeholder - will be implemented to parse compose file and create
        # one CONFIGURES relationship per container service
        return []

    def _process_prometheus_config_special(self, config_file: Path, document: Dict,
                                          host: str, container_name: str) -> List[Dict[str, Any]]:
        """
        Process prometheus.yml to create MONITORS relationships.

        TODO: Parse prometheus.yml to extract scrape targets
        TODO: Create MONITORS relationship for each target

        For now, returns empty list (placeholder).

        Args:
            config_file: Path to prometheus.yml
            document: Base config document
            host: Host where prometheus runs
            container_name: Container name

        Returns:
            List of additional relationships
        """
        self.logger.info(f"TODO: Process prometheus config {config_file.name} for monitoring relationships")
        # Placeholder - will be implemented to parse prometheus config and create
        # MONITORS relationships to each scraped target
        return []

    def _process_authentik_config_special(self, config_file: Path, document: Dict,
                                         host: str, container_name: str) -> List[Dict[str, Any]]:
        """
        Process Authentik configuration files.

        TODO: Parse Authentik config to extract authentication/authorization settings
        TODO: Create appropriate relationships (AUTHENTICATES, AUTHORIZES, etc.)

        For now, returns empty list (placeholder).

        Args:
            config_file: Path to authentik config
            document: Base config document
            host: Host where authentik runs
            container_name: Container name

        Returns:
            List of additional relationships
        """
        self.logger.info(f"TODO: Process authentik config {config_file.name} for auth relationships")
        # Placeholder - will be implemented when Authentik relationship types are defined
        return []

    def _parse_and_enhance_document(self, document: Dict[str, Any], source_file: Path,
                                    service_type: str, config_type: str) -> None:
        """
        Parse configuration file and enhance document with structured data.

        Args:
            document: The document to enhance (modified in place)
            source_file: Path to the source configuration file
            service_type: Service type
            config_type: Configuration type
        """
        # Check file size - skip very large files
        file_stats = source_file.stat()
        if file_stats.st_size > MAX_PARSE_SIZE:
            self.logger.warning(
                f"Skipping parse of large file {source_file.name} ({file_stats.st_size} bytes)"
            )
            return

        # Check if file is text-based (skip binary files)
        mime_type, _ = mimetypes.guess_type(str(source_file))
        if mime_type and not mime_type.startswith('text/'):
            self.logger.debug(f"Skipping binary file {source_file.name} (MIME: {mime_type})")
            return

        # Get appropriate parser from registry
        parser = registry.get_parser(service_type, config_type)
        if not parser:
            self.logger.debug(
                f"No parser available for service_type={service_type}, config_type={config_type}"
            )
            return

        try:
            # Read file content
            with open(source_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Parse configuration
            parsed = parser.parse(content, str(source_file))
            if parsed:
                # Add parsed data to document metadata
                document["metadata"]["parsed_config"] = parsed

                # Extract and add search terms to tags
                search_terms = parser.extract_search_terms(parsed)
                if search_terms:
                    # Add unique search terms to tags
                    existing_tags = set(document["tags"])
                    new_tags = [term for term in search_terms if term not in existing_tags]
                    document["tags"].extend(new_tags)

                self.logger.info(
                    f"Successfully parsed {source_file.name} using {parser.__class__.__name__}"
                )
            else:
                self.logger.debug(f"Parser returned no data for {source_file.name}")

        except Exception as e:
            self.logger.warning(f"Failed to parse config file {source_file.name}: {e}")

    def _process_prometheus_config(self, source_file: Path, target_path: Path,
                                 service_name: str, container_name: str, host: str,
                                 service_type: str, collection_metadata: Dict) -> List[Dict[str, Any]]:
        """Process Prometheus configuration and extract individual scrape targets"""
        documents = []

        # Create main document for the entire config file
        main_doc = self._create_single_service_document(
            source_file, target_path, service_name, container_name, host, service_type, collection_metadata
        )
        main_doc["metadata"]["multi_service"] = True
        documents.append(main_doc)

        try:
            # Parse Prometheus configuration
            with open(source_file, 'r') as f:
                config_content = yaml.safe_load(f)

            # Extract individual scrape configs
            scrape_configs = config_content.get('scrape_configs', [])

            for i, scrape_config in enumerate(scrape_configs):
                job_name = scrape_config.get('job_name', f'job_{i}')

                # Create extracted document for each scrape job
                job_content = yaml.dump(scrape_config, default_flow_style=False)
                job_file_name = f"{job_name}_scrape_config.yml"

                # Save individual scrape config to 'decomposed' subdirectory
                decomposed_dir = target_path.parent / 'decomposed'
                decomposed_dir.mkdir(parents=True, exist_ok=True)
                job_file_path = decomposed_dir / job_file_name
                with open(job_file_path, 'w') as f:
                    f.write(job_content)

                # Create document for individual scrape job
                content_hash = hashlib.md5(job_content.encode()).hexdigest()
                job_doc_id = f"config_{host}_{container_name}_{job_name}_{content_hash[:8]}"

                relative_job_path = job_file_path.relative_to(self.config_files_dir)

                job_document = {
                    "id": job_doc_id,
                    "type": "configuration_file_decomposed",
                    "title": f"Prometheus Scrape Job - {job_name}",
                    "content": job_file_name,
                    "metadata": {
                        "host": host,
                        "service": container_name,
                        "service_type": service_type,
                        "config_type": "monitoring",
                        "file_path": str(relative_job_path),
                        "file_size": len(job_content.encode()),
                        "last_modified": datetime.now().isoformat(),
                        "multi_service": False,
                        "parent_config": main_doc["id"],
                        "extracted_from": source_file.name,
                        "job_name": job_name,
                        "targets": scrape_config.get('static_configs', [{}])[0].get('targets', []),
                        "processed_at": datetime.now().isoformat()
                    }
                }

                documents.append(job_document)

        except Exception as e:
            self.logger.error(f"Failed to parse Prometheus config {source_file}: {e}")

        return documents

    def _process_docker_compose(self, source_file: Path, target_path: Path,
                              service_name: str, container_name: str, host: str,
                              service_type: str, collection_metadata: Dict) -> List[Dict[str, Any]]:
        """Process Docker Compose file and extract individual service configurations"""
        documents = []

        # Create main document for the entire compose file
        main_doc = self._create_single_service_document(
            source_file, target_path, service_name, container_name, host, service_type, collection_metadata
        )
        main_doc["metadata"]["multi_service"] = True
        main_doc["metadata"]["config_type"] = "container_orchestration"
        documents.append(main_doc)

        try:
            # Parse Docker Compose configuration
            with open(source_file, 'r') as f:
                compose_content = yaml.safe_load(f)

            # Extract individual services
            services = compose_content.get('services', {})

            for service_name_key, service_config in services.items():
                # Create extracted document for each service
                service_content = yaml.dump({service_name_key: service_config}, default_flow_style=False)
                service_file_name = f"{service_name_key}_service.yml"

                # Save individual service config to 'decomposed' subdirectory
                decomposed_dir = target_path.parent / 'decomposed'
                decomposed_dir.mkdir(parents=True, exist_ok=True)
                service_file_path = decomposed_dir / service_file_name
                with open(service_file_path, 'w') as f:
                    f.write(service_content)

                # Create document for individual service
                content_hash = hashlib.md5(service_content.encode()).hexdigest()
                service_doc_id = f"config_{host}_{container_name}_{service_name_key}_{content_hash[:8]}"

                relative_service_path = service_file_path.relative_to(self.config_files_dir)

                service_document = {
                    "id": service_doc_id,
                    "type": "configuration_file_decomposed",
                    "title": f"Docker Service - {service_name_key}",
                    "content": service_file_name,
                    "metadata": {
                        "host": host,
                        "service": service_name_key,
                        "service_type": "docker_service",
                        "config_type": "container",
                        "file_path": str(relative_service_path),
                        "file_size": len(service_content.encode()),
                        "last_modified": datetime.now().isoformat(),
                        "multi_service": False,
                        "parent_config": main_doc["id"],
                        "extracted_from": source_file.name,
                        "docker_image": service_config.get('image', 'unknown'),
                        "ports": service_config.get('ports', []),
                        "volumes": service_config.get('volumes', []),
                        "processed_at": datetime.now().isoformat()
                    }
                }

                documents.append(service_document)

        except Exception as e:
            self.logger.error(f"Failed to parse Docker Compose {source_file}: {e}")

        return documents

    def _generate_file_hash(self, file_path: Path) -> str:
        """Generate SHA256 hash of file content for unique identification"""
        hash_sha256 = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_sha256.update(chunk)
            return hash_sha256.hexdigest()
        except Exception as e:
            self.logger.warning(f"Failed to hash file {file_path}: {e}")
            return hashlib.sha256(str(file_path).encode()).hexdigest()

    def _update_rag_data_json(self, documents: List[Dict[str, Any]], relationships: List[Dict[str, Any]], output_path: Path) -> Path:
        """Update rag_data.json with configuration file documents and relationships"""
        rag_data_file = output_path / 'rag_data.json'

        # Load existing rag_data.json or create new structure
        if rag_data_file.exists():
            try:
                with open(rag_data_file, 'r') as f:
                    rag_data = json.load(f)
                self.logger.info("Loaded existing rag_data.json")
            except Exception as e:
                self.logger.warning(f"Failed to load existing rag_data.json: {e}, creating new")
                rag_data = self._create_empty_rag_data()
        else:
            self.logger.info("Creating new rag_data.json")
            rag_data = self._create_empty_rag_data()

        # Remove existing configuration documents (only configuration_file type now)
        original_doc_count = len(rag_data.get('documents', []))
        rag_data['documents'] = [
            doc for doc in rag_data.get('documents', [])
            if doc.get('type') != 'configuration_file'
        ]
        removed_doc_count = original_doc_count - len(rag_data['documents'])
        if removed_doc_count > 0:
            self.logger.info(f"Removed {removed_doc_count} existing configuration documents")

        # Add new configuration documents
        rag_data['documents'].extend(documents)
        self.logger.info(f"Added {len(documents)} new configuration documents")

        # Remove existing configuration relationships (STORED_ON, STORES, CONFIGURES, CONFIGURED_BY)
        if 'relationships' not in rag_data:
            rag_data['relationships'] = []

        original_rel_count = len(rag_data['relationships'])
        rag_data['relationships'] = [
            rel for rel in rag_data['relationships']
            if rel.get('type') not in ['STORED_ON', 'STORES', 'CONFIGURES', 'CONFIGURED_BY']
            or rel.get('source_type') != 'configuration_file' and rel.get('target_type') != 'configuration_file'
        ]
        removed_rel_count = original_rel_count - len(rag_data['relationships'])
        if removed_rel_count > 0:
            self.logger.info(f"Removed {removed_rel_count} existing configuration relationships")

        # Add new configuration relationships
        rag_data['relationships'].extend(relationships)
        self.logger.info(f"Added {len(relationships)} new configuration relationships")

        # Update metadata
        rag_data['metadata']['export_timestamp'] = datetime.now().isoformat()

        # Count configuration documents
        config_doc_count = len([
            doc for doc in rag_data['documents']
            if doc.get('type') == 'configuration_file'
        ])
        rag_data['metadata']['total_configuration_files'] = config_doc_count

        # Count decomposed files separately
        decomposed_count = len([
            doc for doc in rag_data['documents']
            if doc.get('type') == 'configuration_file_decomposed'
        ])
        rag_data['metadata']['total_configuration_files_decomposed'] = decomposed_count

        # Save updated rag_data.json
        with open(rag_data_file, 'w') as f:
            json.dump(rag_data, f, indent=2, default=str)

        self.logger.info(f"Updated rag_data.json with {len(documents)} configuration documents")
        return rag_data_file

    def _create_empty_rag_data(self) -> Dict[str, Any]:
        """Create empty rag_data.json structure"""
        return {
            "metadata": {
                "export_timestamp": datetime.now().isoformat(),
                "total_systems": 0,
                "total_containers": 0,
                "total_vms": 0,
                "total_manual_documents": 0,
                "total_configuration_files": 0
            },
            "documents": [],
            "entities": {
                "systems": {},
                "services": {},
                "categories": {},
                "infrastructure": {}
            },
            "relationships": []
        }