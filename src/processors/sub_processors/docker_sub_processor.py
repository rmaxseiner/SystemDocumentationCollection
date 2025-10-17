# src/processors/sub_processors/docker_sub_processor.py
"""
Docker Sub-Processor
Processes docker section from unified collector output.
Reuses container processing logic from ContainerProcessor.
"""

from typing import Dict, Any, List, Optional
from pathlib import Path

from .base_sub_processor import SubProcessor
from ..container_processor import ContainerProcessor


class DockerSubProcessor(SubProcessor):
    """
    Processes docker section from unified collector output.

    Reuses the proven container processing pipeline from ContainerProcessor:
    1. Data Cleaning and Temporal Removal
    2. Metadata Extraction and Relationship Mapping
    3. LLM-Based Semantic Tagging
    4. RAG Data Assembly and Storage
    """

    def __init__(self, system_name: str, config: Dict[str, Any]):
        """
        Initialize docker sub-processor

        Args:
            system_name: System name
            config: Processor configuration
        """
        super().__init__(system_name, config)

        # Create a ContainerProcessor instance to reuse its processing logic
        # We'll use it for individual container processing, not for orchestration
        self.container_processor = ContainerProcessor(
            name=f"docker_{system_name}",
            config=config
        )

    def get_section_name(self) -> str:
        return "docker"

    def process(self, section_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Process docker section data

        Args:
            section_data: Docker section from unified collector
                Expected structure:
                {
                    "containers": [...],
                    "networks": [...],
                    "volumes": [...]
                }

        Returns:
            List of RAG documents for containers
        """
        self.log_start()

        if not self.validate_section_data(section_data):
            return []

        # Extract containers from section
        containers = section_data.get('containers', [])

        if not containers:
            self.logger.info(f"No containers found in docker section for {self.system_name}")
            return []

        self.logger.info(f"Processing {len(containers)} containers from {self.system_name}")

        # Add system context to each container
        for container in containers:
            container['_system'] = self.system_name
            container['_system_type'] = 'docker'

        # Process containers using ContainerProcessor logic
        # We'll use parallel or sequential processing based on config
        if self.container_processor.parallel_processing and len(containers) > 1:
            documents = self.container_processor._process_containers_parallel(containers)
        else:
            documents = self.container_processor._process_containers_sequential(containers)

        self.log_end(len(documents))

        return documents
