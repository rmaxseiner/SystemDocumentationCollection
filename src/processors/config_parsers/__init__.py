# src/processors/config_parsers/__init__.py
"""
Configuration file parsers package.

This package provides parsers for various configuration file formats,
extracting structured data for improved RAG searchability.

Available parsers:
- NPMConfigParser: Nginx Proxy Manager configurations

Usage:
    from .config_parsers.registry import registry

    parser = registry.get_parser('nginx-proxy-manager', 'proxy')
    if parser:
        parsed_data = parser.parse(content, file_path)
"""

from .base import BaseConfigParser
from .registry import registry, ParserRegistry
from .nginx_proxy import NPMConfigParser

__all__ = [
    'BaseConfigParser',
    'registry',
    'ParserRegistry',
    'NPMConfigParser',
]
