# src/processors/container_processor.py
"""
Container RAG processor implementing the 4-step RAG data extraction pipeline:
1. Data Cleaning and Temporal Removal
2. Metadata Extraction and Relationship Mapping  
3. LLM-Based Semantic Tagging
4. RAG Data Assembly and Storage
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

from .base_processor import BaseProcessor, ProcessingResult
from ..utils.rag_utils import TemporalDataCleaner, MetadataExtractor, RAGDataAssembler
from ..utils.llm_client import create_llm_client, LLMRequest, LLMResponse


class ContainerProcessor(BaseProcessor):
    """
    Processes Docker container data through the complete RAG extraction pipeline.
    Handles parallel processing and configurable LLM integration.
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
            # Check required config
            if not self.output_dir:
                self.logger.error("Output directory not configured")
                return False
            
            # Validate LLM config if enabled
            if self.enable_llm_tagging:
                if not self.llm_config:
                    self.logger.warning("LLM tagging enabled but no LLM config provided")
                    return False
                
                required_llm_fields = ['type']
                for field in required_llm_fields:
                    if field not in self.llm_config:
                        self.logger.error(f"Missing required LLM config field: {field}")
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
            
            # Save results
            results = self._save_results(rag_entities, output_path)
            
            self.logger.info(f"Container processing completed: {len(rag_entities)} entities generated")
            
            return ProcessingResult(
                success=True,
                data=results,
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
                    container['_system_type'] = 'docker'  # Assuming Docker for container processor
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
            # Submit all container processing tasks
            future_to_container = {
                executor.submit(self._process_single_container, container): container 
                for container in containers
            }
            
            # Collect results as they complete
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
        entity_id = f"container_{container.get('_system', 'unknown')}_{container_name}"
        
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
            
            # Save intermediate results if configured
            if self.save_intermediate:
                self._save_intermediate_results(entity_id, {
                    'cleaned_data': cleaned_data,
                    'metadata': metadata,
                    'tags': tags
                })
            
            return rag_entity
            
        except Exception as e:
            self.logger.error(f"Failed to process container {container_name}: {e}")
            return None
    
    def _generate_semantic_tags(self, entity_id: str, entity_type: str, cleaned_data: Dict[str, Any]) -> Dict[str, str]:
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
                    return response.tags
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
        
        # Environment variables (key names only for privacy)
        if 'environment' in cleaned_data and cleaned_data['environment']:
            env_keys = list(cleaned_data['environment'].keys())[:10]  # First 10 keys
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
        
        return "\\n".join(content_parts)
    
    def _generate_fallback_tags(self, cleaned_data: Dict[str, Any]) -> Dict[str, str]:
        """Generate fallback tags using rule-based approach"""
        tags = {}
        
        # Extract from image name
        image = cleaned_data.get('image', '').lower()
        if image:
            # Common service patterns
            if 'redis' in image:
                tags.update({
                    'generic_name': 'redis',
                    'problem_solved': 'caching',
                    'infrastructure_role': 'middleware'
                })
            elif 'postgres' in image or 'mysql' in image:
                tags.update({
                    'generic_name': 'database',
                    'problem_solved': 'storage',
                    'infrastructure_role': 'backend'
                })
            elif 'nginx' in image:
                tags.update({
                    'generic_name': 'nginx',
                    'problem_solved': 'proxy',
                    'infrastructure_role': 'frontend'
                })
            elif 'grafana' in image:
                tags.update({
                    'generic_name': 'grafana',
                    'problem_solved': 'visualization',
                    'infrastructure_role': 'monitoring'
                })
            elif 'prometheus' in image:
                tags.update({
                    'generic_name': 'prometheus',
                    'problem_solved': 'metrics',
                    'infrastructure_role': 'monitoring'
                })
            else:
                # Extract service name from image
                service_name = image.split('/')[-1].split(':')[0]
                tags['generic_name'] = service_name
        
        # Extract system component from labels
        labels = cleaned_data.get('labels', {})
        if labels:
            if 'com.docker.compose.project' in labels:
                tags['system_component'] = labels['com.docker.compose.project']
            elif 'traefik.http.routers' in str(labels):
                tags['infrastructure_role'] = 'frontend'
        
        return tags
    
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
    
    def _save_results(self, rag_entities: List[Dict[str, Any]], output_path: Path) -> Dict[str, Any]:
        """Save final RAG results"""
        try:
            # Save as JSONL for easy streaming
            containers_file = output_path / 'containers.jsonl'
            with open(containers_file, 'w') as f:
                for entity in rag_entities:
                    f.write(json.dumps(entity, default=str) + '\\n')
            
            # Save summary metadata
            metadata = {
                'extraction_timestamp': self._get_timestamp_str(),
                'processor_version': '1.0.0',
                'entities_count': len(rag_entities),
                'entity_types': ['container'],
                'llm_enabled': self.enable_llm_tagging,
                'parallel_processing': self.parallel_processing
            }
            
            metadata_file = output_path / 'containers_metadata.json'
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2, default=str)
            
            self.logger.info(f"Saved {len(rag_entities)} container entities to {containers_file}")
            
            return {
                'containers_file': str(containers_file),
                'metadata_file': str(metadata_file),
                'entities_count': len(rag_entities),
                'output_directory': str(output_path)
            }
            
        except Exception as e:
            self.logger.error(f"Failed to save results: {e}")
            raise