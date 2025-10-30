# src/processors/sub_processors/base_sub_processor.py
"""
Base Sub-Processor
Base class for sub-processors that process specific sections from unified collector output.
Mirrors the SubCollector pattern for consistency.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List
import logging
from datetime import datetime


class SubProcessor(ABC):
    """
    Abstract base class for section-specific processors.
    Each sub-processor processes a specific section from unified collector output.
    """

    def __init__(self, system_name: str, config: Dict[str, Any]):
        """
        Initialize sub-processor

        Args:
            system_name: Name of the system being processed
            config: Processor configuration
        """
        self.system_name = system_name
        self.config = config
        self.logger = logging.getLogger(f'processor.{self.get_section_name()}')

    @abstractmethod
    def get_section_name(self) -> str:
        """
        Return the name of the section this processor handles.
        Must match the section name in unified collector output.
        """
        pass

    @abstractmethod
    def process(self, section_data: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Process section data and return RAG documents and relationships

        Args:
            section_data: The section data from unified collector

        Returns:
            Tuple of (documents, relationships):
                - documents: List of RAG documents (dicts) ready for rag_data.json
                - relationships: List of relationship dicts defining connections between entities
        """
        pass

    def log_start(self):
        """Log start of processing"""
        self.logger.info(f"Starting {self.get_section_name()} processing for {self.system_name}")

    def log_end(self, document_count: int):
        """Log end of processing"""
        self.logger.info(f"Completed {self.get_section_name()} processing: {document_count} documents")

    def validate_section_data(self, section_data: Dict[str, Any]) -> bool:
        """
        Validate that section data has expected structure

        Args:
            section_data: Section data to validate

        Returns:
            True if valid, False otherwise
        """
        if not isinstance(section_data, dict):
            self.logger.error(f"Section data must be a dictionary, got {type(section_data)}")
            return False
        return True
