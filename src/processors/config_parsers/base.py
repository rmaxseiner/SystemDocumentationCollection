# src/processors/config_parsers/base.py
"""
Base class for configuration file parsers.
Provides interface for domain-specific config file parsing.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List


class BaseConfigParser(ABC):
    """
    Base class for domain-specific config parsing.

    Each parser implementation handles a specific type of configuration file
    (e.g., nginx, Apache, Prometheus) and extracts structured data from it.
    """

    @abstractmethod
    def can_process(self, service_type: str, config_type: str) -> bool:
        """
        Determine if this parser can handle the given configuration type.

        Args:
            service_type: Service type (e.g., 'nginx-proxy-manager', 'grafana')
            config_type: Configuration type (e.g., 'proxy', 'monitoring')

        Returns:
            True if this parser handles this config type
        """
        pass

    @abstractmethod
    def parse(self, content: str, file_path: str) -> Optional[Dict[str, Any]]:
        """
        Parse config file content and return structured data.

        Args:
            content: Raw file content as string
            file_path: Path to the file being parsed (for logging/debugging)

        Returns:
            Dictionary of parsed configuration data, or None if parsing fails
        """
        pass

    @abstractmethod
    def extract_search_terms(self, parsed_config: Dict[str, Any]) -> List[str]:
        """
        Extract terms that should be added to tags for searchability.

        These terms help improve RAG search capabilities by adding relevant
        keywords like domain names, IPs, service names, etc.

        Args:
            parsed_config: The parsed configuration dictionary

        Returns:
            List of strings to add to document tags
        """
        pass
