# src/processors/config_parsers/registry.py
"""
Parser registry for configuration file parsers.
Manages all available parsers and routes config files to appropriate parser.
"""

from typing import Optional, List
import logging

from .base import BaseConfigParser
from .nginx_proxy import NPMConfigParser
from .docker_compose import DockerComposeParser


class ParserRegistry:
    """
    Registry for configuration file parsers.

    Maintains a list of available parsers and provides lookup
    functionality to find the appropriate parser for a given
    service_type and config_type combination.
    """

    def __init__(self):
        """Initialize registry with available parsers."""
        self.logger = logging.getLogger('parser_registry')
        self.parsers: List[BaseConfigParser] = [
            NPMConfigParser(),
            DockerComposeParser(),
            # Future parsers can be added here:
            # ApacheConfigParser(),
            # HAProxyConfigParser(),
            # PrometheusConfigParser(),
            # AuthentikConfigParser(),
            # etc.
        ]
        self.logger.info(f"Initialized parser registry with {len(self.parsers)} parsers")

    def get_parser(
        self,
        service_type: str,
        config_type: str
    ) -> Optional[BaseConfigParser]:
        """
        Find appropriate parser for the given configuration type.

        Args:
            service_type: Service type (e.g., 'nginx-proxy-manager', 'grafana')
            config_type: Configuration type (e.g., 'proxy', 'monitoring')

        Returns:
            BaseConfigParser instance if a matching parser is found, None otherwise
        """
        for parser in self.parsers:
            if parser.can_process(service_type, config_type):
                self.logger.debug(
                    f"Found parser {parser.__class__.__name__} for "
                    f"service_type={service_type}, config_type={config_type}"
                )
                return parser

        self.logger.debug(
            f"No parser found for service_type={service_type}, config_type={config_type}"
        )
        return None

    def list_parsers(self) -> List[str]:
        """
        Get list of registered parser names.

        Returns:
            List of parser class names
        """
        return [parser.__class__.__name__ for parser in self.parsers]


# Global registry instance
# This is the single instance used throughout the application
registry = ParserRegistry()
