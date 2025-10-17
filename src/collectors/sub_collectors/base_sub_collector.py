# src/collectors/sub_collectors/base_sub_collector.py
"""
Base class for all sub-collectors in the unified collector system.
Sub-collectors focus on collecting specific aspects of a system (Docker, hardware, etc.)
"""

from abc import ABC, abstractmethod
from typing import Dict, Any
import logging


class SubCollector(ABC):
    """
    Abstract base class for all sub-collectors.

    Sub-collectors are lightweight components that collect specific data sections.
    Unlike full collectors, they:
    - Don't manage SSH connections (receive connected SSHConnector)
    - Return data dictionaries (not CollectionResult objects)
    - Focus on single responsibility
    - Are orchestrated by MainCollector
    """

    def __init__(self, ssh_connector, system_name: str):
        """
        Initialize sub-collector

        Args:
            ssh_connector: Already-connected SSHConnector instance
            system_name: Name of the system being collected from
        """
        self.ssh = ssh_connector
        self.system_name = system_name
        self.logger = logging.getLogger(f"subcollector.{self.__class__.__name__}")

    @abstractmethod
    def collect(self) -> Dict[str, Any]:
        """
        Collect data section.

        Returns:
            Dict containing collected data for this sub-collector's domain.
            Should NOT include success/error status - raise exceptions on failure.

        Raises:
            Exception: If collection fails
        """
        pass

    @abstractmethod
    def get_section_name(self) -> str:
        """
        Get the name of the section this sub-collector produces.

        Returns:
            String name for the section in the unified document
        """
        pass

    def log_start(self):
        """Log the start of collection"""
        self.logger.info(f"Starting {self.get_section_name()} collection for {self.system_name}")

    def log_end(self, item_count: int = None):
        """Log the end of collection"""
        if item_count is not None:
            self.logger.info(f"Completed {self.get_section_name()} collection: {item_count} items")
        else:
            self.logger.info(f"Completed {self.get_section_name()} collection")

    def log_error(self, error: Exception):
        """Log collection error"""
        self.logger.error(f"Failed to collect {self.get_section_name()}: {error}")
