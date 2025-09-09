# src/processors/container_processor.py
"""
Container RAG processor implementing the 4-step RAG data extraction pipeline:
1. Data Cleaning and Temporal Removal
2. Metadata Extraction and Relationship Mapping
3. LLM-Based Semantic Tagging
4. RAG Data Assembly and Storage

Outputs containers.jsonl and updates rag_data.json incrementally.
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from .base_processor import BaseProcessor, ProcessingResult
from ..utils.rag_utils import TemporalDataCleaner, MetadataExtractor, RAGDataAssembler
from ..utils.llm_client import create_llm_client, LLMRequest


class ContainerProcessor(BaseProcessor):
    """
    Processes Docker container data through the complete RAG extraction pipeline.
    Updates rag_data.json incrementally with container documents and host entities.
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)

        # Initialize processing components
        self.cleaner = TemporalDataCleaner(
            custom_rules=config.get('cleaning_rules', {})
        )
        self.metadata_extractor = MetadataExtractor(
            config=config.get('metadata_config', {})
        )
        self.assembler = RAGDataAssembler(
            config=config.get('assembly_config', {})
        )

        # LLM configuration
        self.llm_config = config.get('llm', {})
        self.llm_client = None
        self.enable_llm_tagging = config.get('enable_llm_tagging', True)
        self.parallel_processing = config.get('parallel_processing', True)
        self.max_workers = config.get('max_workers', 4)

        # Output configuration
        self.output_dir = Path(config.get('output_dir', 'rag_output'))
        self.save_intermediate = config.get('save_intermediate', True)

        # Initialize LLM client if enabled
        if self.enable_llm_tagging and self.llm_config:
            try:
                self.llm_client = create_llm_client(self.llm_config)
                self.logger.info(f"Initialized LLM client: {self.llm_config.get('type', 'unknown')}")
            except Exception as e:
                self.logger.error(f"Failed to initialize LLM client: {e}")
                self.llm_client = None

    def validate_config(self) -> bool:
        """Validate processor configuration"""
        try:
            if not self.output_dir:
                self.logger.error("Output directory not configured")
                return False

            if self.enable_llm_tagging and not self.llm_config:
                self.logger.warning("LLM tagging enabled but no LLM config provided")
                return False

            self.logger.info("Container processor configuration validated")
            return True

        except Exception as e:
            self.logger.error(f"Configuration validation failed: {e}")
            return False

    def process(self, collected_data: Dict[str, Any]) -> ProcessingResult:
        """
        Process collected container data through the RAG pipeline
        
        Args:
            collected_data: Dictionary containing results from collectors
            
        Returns:
            ProcessingResult: Contains processed RAG data or error information
        """
        try:
            self.logger.info("Starting container RAG processing pipeline")

            # Extract container data from collected results
            containers = self._extract_container_data(collected_data)

            if not containers:
                self.logger.warning("No container data found for processing")
                return ProcessingResult(
                    success=True,
                    data={'containers_processed': 0, 'message': 'No containers to process'},
                    metadata={'processor_type': 'container_rag'}
                )

            self.logger.info(f"Processing {len(containers)} containers")

            # Create output directory
            output_path = self._create_output_directory(str(self.output_dir))

            # Process containers through pipeline
            if self.parallel_processing and len(containers) > 1:
                rag_entities = self._process_containers_parallel(containers)
            else:
                rag_entities = self._process_containers_sequential(containers)

            # Save containers.jsonl
            containers_file = self._save_containers_jsonl(rag_entities, output_path)

            # Update rag_data.json
            rag_data_file = self._update_rag_data_json(rag_entities, collected_data, output_path)

            self.logger.info(f"Container processing completed: {len(rag_entities)} entities generated")

            return ProcessingResult(
                success=True,
                data={
                    'containers_file': str(containers_file),
                    'rag_data_file': str(rag_data_file),
                    'containers_processed': len(containers),
                    'entities_generated': len(rag_entities),
                    'output_directory': str(output_path)
                },
                metadata={
                    'processor_type': 'container_rag',
                    'containers_processed': len(containers),
                    'entities_generated': len(rag_entities),
                    'llm_enabled': self.enable_llm_tagging,
                    'output_directory': str(output_path)
                }
            )

        except Exception as e:
            self.logger.exception("Container processing failed")
            return ProcessingResult(
                success=False,
                error=str(e),
                metadata={'processor_type': 'container_rag'}
            )

    def _extract_container_data(self, collected_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract container data from collection results"""
        containers = []

        for system_name, collection_result in collected_data.items():
            try:
                # Handle different result formats
                if hasattr(collection_result, 'success') and collection_result.success:
                    system_data = collection_result.data
                elif isinstance(collection_result, dict) and collection_result.get('success'):
                    system_data = collection_result.get('data', {})
                else:
                    self.logger.warning(f"Skipping {system_name}: collection was not successful")
                    continue

                # Extract containers from system data
                system_containers = system_data.get('containers', [])
                for container in system_containers:
                    # Add system context
                    container['_system'] = system_name
                    container['_system_type'] = 'docker'
                    containers.append(container)

                self.logger.debug(f"Extracted {len(system_containers)} containers from {system_name}")

            except Exception as e:
                self.logger.error(f"Failed to extract containers from {system_name}: {e}")
                continue

        return containers

    def _process_containers_parallel(self, containers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process containers in parallel"""
        self.logger.info(f"Processing {len(containers)} containers in parallel with {self.max_workers} workers")

        rag_entities = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_container = {
                executor.submit(self._process_single_container, container): container
                for container in containers
            }

            for future in as_completed(future_to_container):
                container = future_to_container[future]
                try:
                    rag_entity = future.result()
                    if rag_entity:
                        rag_entities.append(rag_entity)
                except Exception as e:
                    container_name = container.get('name', 'unknown')
                    self.logger.error(f"Failed to process container {container_name}: {e}")

        return rag_entities

    def _process_containers_sequential(self, containers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process containers sequentially"""
        self.logger.info(f"Processing {len(containers)} containers sequentially")

        rag_entities = []

        for i, container in enumerate(containers, 1):
            try:
                container_name = container.get('name', f'container_{i}')
                self.logger.debug(f"Processing container {i}/{len(containers)}: {container_name}")

                rag_entity = self._process_single_container(container)
                if rag_entity:
                    rag_entities.append(rag_entity)

            except Exception as e:
                container_name = container.get('name', 'unknown')
                self.logger.error(f"Failed to process container {container_name}: {e}")

        return rag_entities

    def _process_single_container(self, container: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process a single container through the complete RAG pipeline"""
        container_name = container.get('name', 'unknown')
        system_name = container.get('_system', 'unknown')
        entity_id = f"container_{system_name}_{container_name}"

        try:
            # Step 1: Data Cleaning and Temporal Removal
            self.logger.debug(f"Step 1: Cleaning temporal data for {container_name}")
            cleaned_data = self.cleaner.clean_data(container, 'container')

            # Step 2: Metadata Extraction and Relationship Mapping
            self.logger.debug(f"Step 2: Extracting metadata for {container_name}")
            metadata = self.metadata_extractor.extract_metadata(cleaned_data, 'container', entity_id)

            # Step 3: LLM-Based Semantic Tagging
            self.logger.debug(f"Step 3: Generating semantic tags for {container_name}")
            tags = self._generate_semantic_tags(entity_id, 'container', cleaned_data)

            # Step 4: RAG Data Assembly and Storage
            self.logger.debug(f"Step 4: Assembling RAG entity for {container_name}")
            rag_entity = self.assembler.assemble_rag_entity(
                entity_id=entity_id,
                entity_type='container',
                cleaned_data=cleaned_data,
                metadata=metadata,
                tags=tags
            )

            # Convert to document format with additional metadata
            document = self._convert_to_document_format(rag_entity, container)

            # Save intermediate results if configured
            if self.save_intermediate:
                self._save_intermediate_results(entity_id, {
                    'cleaned_data': cleaned_data,
                    'metadata': metadata,
                    'tags': tags
                })

            return document

        except Exception as e:
            self.logger.error(f"Failed to process container {container_name}: {e}")
            return None

    def _convert_to_document_format(self, rag_entity: Dict[str, Any], original_container: Dict[str, Any]) -> Dict[
        str, Any]:
        """Convert RAG entity to document format matching the target schema"""

        # Extract service type from image
        service_type = self._extract_service_type_from_image(original_container.get('image', ''))

        # Count persistent mounts
        mounts = original_container.get('mounts', [])
        persistent_mounts = len([m for m in mounts if m.get('type') in ['bind', 'volume']])

        # Extract exposed ports
        ports = original_container.get('ports', {})
        exposed_ports = [port for port in ports.keys() if port] if ports else []

        # Get restart policy
        restart_policy = original_container.get('restart_policy', {})
        restart_policy_name = restart_policy.get('Name', 'unknown') if isinstance(restart_policy, dict) else str(
            restart_policy)

        # Create enhanced content
        content_parts = [
            f"{original_container.get('name', 'unknown')} is a {service_type} service running on {original_container.get('_system', 'unknown')}.",
            f"It uses the {original_container.get('image', 'unknown')} Docker image and is currently {original_container.get('status', 'unknown')}."
        ]

        if exposed_ports:
            content_parts.append(f"It exposes ports: {', '.join(exposed_ports)}.")

        if persistent_mounts > 0:
            content_parts.append(f"It has {persistent_mounts} persistent data mounts.")

        if restart_policy_name != 'unknown':
            content_parts.append(f"Restart policy: {restart_policy_name}.")

        document = {
            "id": rag_entity['id'],
            "type": "service",
            "title": f"{original_container.get('name', 'unknown')} on {original_container.get('_system', 'unknown')}",
            "content": " ".join(content_parts),
            "metadata": {
                "system_name": original_container.get('_system', 'unknown'),
                "container_name": original_container.get('name', 'unknown'),
                "image": original_container.get('image', 'unknown'),
                "status": original_container.get('status', 'unknown'),
                "service_type": service_type
            },
            "tags": rag_entity.get('tags', [])
        }

        return document

    def _extract_service_type_from_image(self, image: str) -> str:
        """Extract service type from Docker image name"""
        if not image:
            return 'unknown'

        image_lower = image.lower()

        # Service type mappings
        service_mappings = {
            'redis': 'cache',
            'postgres': 'database',
            'mysql': 'database',
            'nginx-proxy-manager': 'nginx-proxy-manager',
            'grafana': 'grafana',
            'prometheus': 'prometheus',
            'cadvisor': 'cadvisor',
            'node-exporter': 'node-exporter',
            'blackbox-exporter': 'blackbox-exporter',
            'registry': 'registry',
            'gitea': 'git repository',
            'homepage': 'homepage',
            'watchtower': 'watchtower',
            'fail2ban': 'fail2ban',
            'home-assistant': 'home-assistant',
            'zigbee2mqtt': 'zigbee2mqtt',
            'esphome': 'esphome',
            'mosquitto': 'eclipse-mosquitto',
            'influx': 'time series database',
            'node-red': 'node-red',
            'zwavejs2mqtt': 'zwavejs2mqtt',
            'docker-socket-proxy': 'docker-socket-proxy',
            'docker-registry-ui': 'docker-registry-ui',
            'paperless': 'paperless-ngx',
            'omada-controller': 'omada-controller',
            'omada_exporter': 'omada_exporter',
            'authentik': 'server',
            'proxy': 'proxy'
        }

        for key, service_type in service_mappings.items():
            if key in image_lower:
                return service_type

        # Fallback to image name without tag
        return image.split('/')[-1].split(':')[0]

    def _generate_semantic_tags(self, entity_id: str, entity_type: str, cleaned_data: Dict[str, Any]) -> List[str]:
        """Generate semantic tags using LLM or fallback methods"""
        if not self.enable_llm_tagging or not self.llm_client:
            self.logger.debug(f"LLM tagging disabled or unavailable for {entity_id}, using fallback")
            return self._generate_fallback_tags(cleaned_data)

        try:
            # Create content for LLM analysis
            content = self._create_llm_content(cleaned_data)

            # Create LLM request
            llm_request = LLMRequest(
                entity_id=entity_id,
                entity_type=entity_type,
                content=content,
                context={'processor': 'container'}
            )

            # Get LLM response
            responses = self.llm_client.generate_tags([llm_request])

            if responses and len(responses) > 0:
                response = responses[0]
                if response.success and response.tags:
                    self.logger.debug(f"LLM generated tags for {entity_id}: {response.tags}")
                    # Convert dict tags to list
                    return list(response.tags.values()) + ['docker', 'container', 'service']
                else:
                    self.logger.warning(f"LLM tagging failed for {entity_id}: {response.error}")

            # Fallback to rule-based tags
            return self._generate_fallback_tags(cleaned_data)

        except Exception as e:
            self.logger.error(f"Error in semantic tagging for {entity_id}: {e}")
            return self._generate_fallback_tags(cleaned_data)

    def _create_llm_content(self, cleaned_data: Dict[str, Any]) -> str:
        """Create content string for LLM analysis"""
        content_parts = []

        # Basic container info
        if 'name' in cleaned_data:
            content_parts.append(f"Container name: {cleaned_data['name']}")
        if 'image' in cleaned_data:
            content_parts.append(f"Docker image: {cleaned_data['image']}")
        if 'command' in cleaned_data:
            content_parts.append(f"Command: {cleaned_data['command']}")

        # Environment variables (handle both list and dict formats)
        if 'environment' in cleaned_data and cleaned_data['environment']:
            env_data = cleaned_data['environment']

            if isinstance(env_data, list):
                # Docker format: ["KEY=value", "KEY2=value2"]
                env_keys = []
                for env_item in env_data[:10]:  # First 10 items
                    if '=' in str(env_item):
                        key = str(env_item).split('=', 1)[0]
                        env_keys.append(key)
                content_parts.append(f"Environment variables: {', '.join(env_keys)}")

            elif isinstance(env_data, dict):
                # Dictionary format: {"KEY": "value", "KEY2": "value2"}
                env_keys = list(env_data.keys())[:10]  # First 10 keys
                content_parts.append(f"Environment variables: {', '.join(env_keys)}")

        # Labels
        if 'labels' in cleaned_data and cleaned_data['labels']:
            labels = cleaned_data['labels']
            label_info = []
            for key, value in list(labels.items())[:5]:  # First 5 labels
                label_info.append(f"{key}={value}")
            content_parts.append(f"Labels: {', '.join(label_info)}")

        # Ports
        if 'ports' in cleaned_data and cleaned_data['ports']:
            ports = list(cleaned_data['ports'].keys())
            content_parts.append(f"Exposed ports: {', '.join(ports)}")

        # Volumes
        if 'mounts' in cleaned_data and cleaned_data['mounts']:
            mount_types = [mount.get('type', 'unknown') for mount in cleaned_data['mounts']]
            content_parts.append(f"Mount types: {', '.join(set(mount_types))}")

        return "\n".join(content_parts)

    def _generate_fallback_tags(self, cleaned_data: Dict[str, Any]) -> List[str]:
        """Generate fallback tags using rule-based approach"""
        tags = ['docker', 'container', 'service']

        # Extract from image name
        image = cleaned_data.get('image', '').lower()
        if image:
            service_name = image.split('/')[-1].split(':')[0]
            tags.append(service_name)

            # Add specific technology tags
            if 'redis' in image:
                tags.extend(['cache', 'database'])
            elif 'postgres' in image or 'mysql' in image:
                tags.extend(['database', 'storage'])
            elif 'nginx' in image:
                tags.extend(['proxy', 'web-server'])
            elif 'prometheus' in image or 'grafana' in image:
                tags.extend(['monitoring', 'metrics'])

        return list(set(tags))  # Remove duplicates

    def _save_containers_jsonl(self, documents: List[Dict[str, Any]], output_path: Path) -> Path:
        """Save container documents as JSONL file"""
        containers_file = output_path / 'containers.jsonl'

        with open(containers_file, 'w') as f:
            for document in documents:
                f.write(json.dumps(document, default=str) + '\n')

        self.logger.info(f"Saved {len(documents)} container documents to {containers_file}")
        return containers_file

    def _update_rag_data_json(self, documents: List[Dict[str, Any]], collected_data: Dict[str, Any],
                              output_path: Path) -> Path:
        """Update rag_data.json with container documents and host entities"""
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

        # Remove existing container documents (same format we're inserting)
        original_count = len(rag_data.get('documents', []))
        rag_data['documents'] = [
            doc for doc in rag_data.get('documents', [])
            if not (doc.get('type') == 'service' and doc.get('id', '').startswith('container_'))
        ]
        removed_count = original_count - len(rag_data['documents'])
        if removed_count > 0:
            self.logger.info(f"Removed {removed_count} existing container documents")

        # Add new container documents
        rag_data['documents'].extend(documents)
        self.logger.info(f"Added {len(documents)} new container documents")

        # Update host entities in entities.systems
        self._update_host_entities(rag_data, collected_data)

        # Update metadata
        rag_data['metadata']['export_timestamp'] = datetime.now().isoformat()
        rag_data['metadata']['total_containers'] = len([
            doc for doc in rag_data['documents']
            if doc.get('type') == 'service' and doc.get('id', '').startswith('container_')
        ])

        # Save updated rag_data.json
        with open(rag_data_file, 'w') as f:
            json.dump(rag_data, f, indent=2, default=str)

        self.logger.info(f"Updated rag_data.json with {len(documents)} container documents")
        return rag_data_file

    def _create_empty_rag_data(self) -> Dict[str, Any]:
        """Create empty rag_data.json structure"""
        return {
            "metadata": {
                "export_timestamp": datetime.now().isoformat(),
                "total_systems": 0,
                "total_containers": 0,
                "total_vms": 0
            },
            "documents": [],
            "entities": {
                "systems": {},
                "services": {},
                "categories": {}
            },
            "relationships": []
        }

    def _update_host_entities(self, rag_data: Dict[str, Any], collected_data: Dict[str, Any]):
        """Update host entities with container counts"""
        systems = rag_data.get('entities', {}).get('systems', {})

        # Count containers per system
        system_container_counts = {}
        for system_name in collected_data.keys():
            # Count containers for this system in our documents
            container_count = len([
                doc for doc in rag_data['documents']
                if (doc.get('type') == 'service' and
                    doc.get('id', '').startswith('container_') and
                    doc.get('metadata', {}).get('system_name') == system_name)
            ])
            system_container_counts[system_name] = container_count

        # Update or add system entities
        for system_name, container_count in system_container_counts.items():
            if system_name in systems:
                # Update existing system
                systems[system_name]['containers'] = container_count
                systems[system_name]['status'] = 'active' if container_count > 0 else 'inactive'
                self.logger.debug(f"Updated system {system_name}: {container_count} containers")
            else:
                # Add new system
                systems[system_name] = {
                    "type": "docker",
                    "containers": container_count,
                    "vms": 0,
                    "status": "active" if container_count > 0 else "inactive"
                }
                self.logger.debug(f"Added new system {system_name}: {container_count} containers")

        # Update total systems count in metadata
        rag_data['metadata']['total_systems'] = len(systems)

    def _save_intermediate_results(self, entity_id: str, intermediate_data: Dict[str, Any]):
        """Save intermediate processing results for debugging"""
        try:
            intermediate_dir = self.output_dir / 'intermediate'
            intermediate_dir.mkdir(parents=True, exist_ok=True)

            filename = f"{entity_id}_intermediate.json"
            filepath = intermediate_dir / filename

            with open(filepath, 'w') as f:
                json.dump(intermediate_data, f, indent=2, default=str)

        except Exception as e:
            self.logger.warning(f"Failed to save intermediate results for {entity_id}: {e}")