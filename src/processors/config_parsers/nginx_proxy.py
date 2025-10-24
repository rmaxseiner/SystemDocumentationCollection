# src/processors/config_parsers/nginx_proxy.py
"""
Nginx Proxy Manager configuration parser.
Extracts structured data from NPM nginx proxy configuration files.
"""

import re
from typing import Optional, Dict, Any, List
from .base import BaseConfigParser


class NPMConfigParser(BaseConfigParser):
    """
    Parser for Nginx Proxy Manager configuration files.

    Extracts:
    - Server names (primary domain and aliases)
    - Upstream server and port
    - Listen ports
    - SSL configuration
    - Proxy settings
    """

    def can_process(self, service_type: str, config_type: str) -> bool:
        """
        Check if this is an NPM proxy configuration.

        Args:
            service_type: Should be 'nginx-proxy-manager'
            config_type: Should be 'proxy'

        Returns:
            True if this parser handles this config type
        """
        return (
            service_type == "nginx-proxy-manager" and
            config_type == "proxy"
        )

    def parse(self, content: str, file_path: str) -> Optional[Dict[str, Any]]:
        """
        Parse NPM nginx configuration file.

        Args:
            content: Raw nginx config file content
            file_path: Path to file (for error reporting)

        Returns:
            Dictionary with parsed configuration, or None if parsing fails
        """
        try:
            parsed = {}

            # Extract server_name (primary domain and aliases)
            server_match = re.search(r'server_name\s+([^;]+);', content)
            if server_match:
                server_names = server_match.group(1).strip().split()
                parsed["server_name"] = server_names[0] if server_names else None
                parsed["server_name_aliases"] = server_names[1:] if len(server_names) > 1 else []
            else:
                parsed["server_name"] = None
                parsed["server_name_aliases"] = []

            # Extract upstream from set $server and set $port
            upstream_server = re.search(r'set\s+\$server\s+"([^"]+)"', content)
            upstream_port = re.search(r'set\s+\$port\s+(\d+)', content)
            if upstream_server and upstream_port:
                parsed["upstream"] = f"{upstream_server.group(1)}:{upstream_port.group(1)}"
                parsed["upstream_ip"] = upstream_server.group(1)
                parsed["upstream_port"] = int(upstream_port.group(1))
            else:
                parsed["upstream"] = None
                parsed["upstream_ip"] = None
                parsed["upstream_port"] = None

            # Extract listen ports
            listen_ports = re.findall(r'listen\s+(\d+)', content)
            parsed["listen_ports"] = sorted(set(int(p) for p in listen_ports)) if listen_ports else []

            # SSL detection
            has_ssl_keyword = 'ssl' in content or '443' in listen_ports
            parsed["ssl_enabled"] = has_ssl_keyword

            # SSL certificate paths
            cert_match = re.search(r'ssl_certificate\s+([^;]+);', content)
            if cert_match:
                parsed["ssl_certificate"] = cert_match.group(1).strip()
            else:
                parsed["ssl_certificate"] = None

            key_match = re.search(r'ssl_certificate_key\s+([^;]+);', content)
            if key_match:
                parsed["ssl_certificate_key"] = key_match.group(1).strip()
            else:
                parsed["ssl_certificate_key"] = None

            # Force SSL (detect HTTP to HTTPS redirects)
            parsed["force_ssl"] = parsed["ssl_enabled"] and bool(
                re.search(r'return\s+301\s+https://', content)
            )

            # Extract forward scheme
            scheme_match = re.search(r'set\s+\$forward_scheme\s+(\w+)', content)
            if scheme_match:
                parsed["forward_scheme"] = scheme_match.group(1)
            else:
                parsed["forward_scheme"] = None

            # Extract HTTP/2 status
            parsed["http2_enabled"] = bool(re.search(r'http2\s+on', content))

            # Extract location blocks (basic detection)
            location_blocks = re.findall(r'location\s+([^\s{]+)', content)
            parsed["locations"] = location_blocks if location_blocks else []

            # Only return parsed data if we got at least some meaningful information
            if parsed.get("server_name") or parsed.get("upstream"):
                return parsed
            else:
                return None

        except Exception as e:
            print(f"Error parsing NPM config {file_path}: {e}")
            return None

    def extract_search_terms(self, parsed_config: Dict[str, Any]) -> List[str]:
        """
        Extract searchable terms from parsed NPM configuration.

        Args:
            parsed_config: The parsed configuration dictionary

        Returns:
            List of search terms to add to document tags
        """
        terms = []

        # Add primary domain
        if parsed_config.get("server_name"):
            terms.append(parsed_config["server_name"])

        # Add domain aliases
        if parsed_config.get("server_name_aliases"):
            terms.extend(parsed_config["server_name_aliases"])

        # Add upstream (full address)
        if parsed_config.get("upstream"):
            terms.append(parsed_config["upstream"])

        # Add upstream IP separately for easier searching
        if parsed_config.get("upstream_ip"):
            terms.append(parsed_config["upstream_ip"])

        # Add SSL-related tags
        if parsed_config.get("ssl_enabled"):
            terms.append("ssl-enabled")
            terms.append("https")

        # Add HTTP/2 tag
        if parsed_config.get("http2_enabled"):
            terms.append("http2")

        # Add force SSL tag
        if parsed_config.get("force_ssl"):
            terms.append("force-ssl")

        return terms
