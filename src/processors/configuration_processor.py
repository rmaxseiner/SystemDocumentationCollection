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
import logging
from datetime import datetime
import shutil
import re

from .base_processor import BaseProcessor, ProcessingResult


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

        # Multi-service configuration handlers
        self.multi_service_handlers = {
            'prometheus.yml': self._process_prometheus_config,
            'docker-compose.yml': self._process_docker_compose,
            'docker-compose.yaml': self._process_docker_compose,
        }

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
            collected_data: Not used for configuration processing

        Returns:
            ProcessingResult: Contains processed configuration results
        """
        try:
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
            processed_services = 0

            for service_dir in service_dirs:
                try:
                    service_docs = self._process_service_directory(service_dir)
                    if service_docs:
                        all_documents.extend(service_docs)
                        processed_services += 1
                except Exception as e:
                    self.logger.error(f"Failed to process service directory {service_dir}: {e}")
                    continue

            # Update rag_data.json with configuration documents
            rag_data_file = self._update_rag_data_json(all_documents, output_path)

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

    def _process_service_directory(self, service_dir: Path) -> List[Dict[str, Any]]:
        """Process a single service directory containing configuration files"""
        self.logger.debug(f"Processing service directory: {service_dir}")

        documents = []
        service_name = service_dir.name

        # Load collection metadata if available
        metadata_file = service_dir / 'collection_metadata.yml'
        collection_metadata = {}
        if metadata_file.exists():
            try:
                with open(metadata_file, 'r') as f:
                    collection_metadata = yaml.safe_load(f) or {}
            except Exception as e:
                self.logger.warning(f"Failed to load metadata for {service_name}: {e}")

        # Extract host and service info from metadata with fallback logic
        # If collection_host is not in metadata, try to infer from subdirectory names or use service_name
        host = collection_metadata.get('collection_host')
        if not host or host == 'unknown':
            # Log warning about missing host metadata
            self.logger.warning(f"No collection_host found in metadata for {service_name}, using service_name as fallback")
            host = service_name

        container_name = collection_metadata.get('container_name', service_name)
        service_type = collection_metadata.get('service_type', service_name)

        # Process each subdirectory (container/service instance)
        for container_dir in service_dir.iterdir():
            if not container_dir.is_dir() or container_dir.name == '__pycache__':
                continue

            container_name = container_dir.name

            # Process configuration files in this container directory
            config_files = self._get_config_files(container_dir)

            for config_file in config_files:
                # Skip metadata files
                if config_file.name == 'collection_metadata.yml':
                    continue

                doc = self._process_config_file(
                    config_file,
                    service_name,
                    container_name,
                    host,
                    service_type,
                    collection_metadata
                )
                if doc:
                    if isinstance(doc, list):
                        documents.extend(doc)
                    else:
                        documents.append(doc)

        return documents

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
                           host: str, service_type: str, collection_metadata: Dict) -> Optional[Any]:
        """Process a single configuration file"""
        self.logger.debug(f"Processing config file: {config_file}")

        try:
            # Copy file to output directory
            target_path = self._copy_config_file(config_file, host, container_name)

            # Check if this is a multi-service configuration file
            if config_file.name in self.multi_service_handlers:
                return self.multi_service_handlers[config_file.name](
                    config_file, target_path, service_name, container_name, host, service_type, collection_metadata
                )
            else:
                # Single service configuration
                return self._create_single_service_document(
                    config_file, target_path, service_name, container_name, host, service_type, collection_metadata
                )

        except Exception as e:
            self.logger.error(f"Failed to process config file {config_file}: {e}")
            return None

    def _copy_config_file(self, source_file: Path, host: str, container_name: str) -> Path:
        """Copy configuration file to output directory structure"""
        # Create target directory structure: host/container/filename
        target_dir = self.config_files_dir / host / container_name
        target_dir.mkdir(parents=True, exist_ok=True)

        target_path = target_dir / source_file.name
        shutil.copy2(source_file, target_path)

        return target_path

    def _create_single_service_document(self, source_file: Path, target_path: Path,
                                      service_name: str, container_name: str, host: str,
                                      service_type: str, collection_metadata: Dict) -> Dict[str, Any]:
        """Create document for single-service configuration file"""

        # Generate unique document ID
        content_hash = self._generate_file_hash(source_file)
        doc_id = f"config_{host}_{container_name}_{source_file.stem}_{content_hash[:8]}"

        # Determine configuration type
        config_type = self.config_type_mappings.get(service_type, 'application')

        # Get file metadata
        file_stats = source_file.stat()

        # Create relative path for metadata
        relative_path = target_path.relative_to(self.config_files_dir)

        document = {
            "id": doc_id,
            "type": "configuration_file",
            "title": f"Configuration - {container_name}/{source_file.name}",
            "content": source_file.name,
            "metadata": {
                "host": host,
                "service": container_name,
                "service_type": service_type,
                "config_type": config_type,
                "file_path": str(relative_path),
                "file_size": file_stats.st_size,
                "last_modified": datetime.fromtimestamp(file_stats.st_mtime).isoformat(),
                "multi_service": False,
                "parent_config": None,
                "extracted_from": None,
                "collection_metadata": collection_metadata,
                "processed_at": datetime.now().isoformat()
            },
            "tags": [
                "configuration",
                service_type,
                config_type,
                host,
                container_name,
                source_file.suffix.lstrip('.') if source_file.suffix else 'config'
            ]
        }

        return document

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
                    },
                    "tags": [
                        "configuration",
                        "configuration_decomposed",
                        "prometheus",
                        "monitoring",
                        "scrape_job",
                        job_name,
                        host,
                        container_name
                    ]
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
                    },
                    "tags": [
                        "configuration",
                        "configuration_decomposed",
                        "docker",
                        "container",
                        "service",
                        service_name_key,
                        host,
                        container_name
                    ]
                }

                documents.append(service_document)

        except Exception as e:
            self.logger.error(f"Failed to parse Docker Compose {source_file}: {e}")

        return documents

    def _generate_file_hash(self, file_path: Path) -> str:
        """Generate MD5 hash of file content for unique identification"""
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            self.logger.warning(f"Failed to hash file {file_path}: {e}")
            return hashlib.md5(str(file_path).encode()).hexdigest()

    def _update_rag_data_json(self, documents: List[Dict[str, Any]], output_path: Path) -> Path:
        """Update rag_data.json with configuration file documents"""
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

        # Remove existing configuration documents (both types)
        original_doc_count = len(rag_data.get('documents', []))
        rag_data['documents'] = [
            doc for doc in rag_data.get('documents', [])
            if doc.get('type') not in ['configuration_file', 'configuration_file_decomposed']
        ]
        removed_doc_count = original_doc_count - len(rag_data['documents'])
        if removed_doc_count > 0:
            self.logger.info(f"Removed {removed_doc_count} existing configuration documents")

        # Add new configuration documents
        rag_data['documents'].extend(documents)
        self.logger.info(f"Added {len(documents)} new configuration documents")

        # Update metadata
        rag_data['metadata']['export_timestamp'] = datetime.now().isoformat()

        # Count configuration documents (both types)
        config_doc_count = len([
            doc for doc in rag_data['documents']
            if doc.get('type') in ['configuration_file', 'configuration_file_decomposed']
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