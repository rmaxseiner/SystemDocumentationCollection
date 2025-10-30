# src/processors/config_parsers/nginx_proxy.py
"""
Nginx Proxy Manager configuration parser.
Extracts structured data from NPM nginx proxy configuration files and generates proxy_host entities.
"""

import re
from datetime import datetime
from pathlib import Path
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

            # Extract HSTS configuration
            hsts_match = re.search(r'Strict-Transport-Security.*?max-age=(\d+)', content, re.IGNORECASE)
            parsed["hsts_enabled"] = bool(hsts_match)
            parsed["hsts_max_age"] = int(hsts_match.group(1)) if hsts_match else None

            # Extract block exploits
            parsed["block_exploits"] = 'conf.d/include/block-exploits.conf' in content

            # Extract asset caching
            parsed["asset_caching"] = 'conf.d/include/assets.conf' in content

            # Extract IPv6 support
            parsed["ipv6"] = '[::]' in content

            # Extract NPM ID from filename
            file_path_obj = Path(file_path)
            try:
                npm_id = int(file_path_obj.stem)
                parsed["npm_id"] = npm_id
            except (ValueError, AttributeError):
                parsed["npm_id"] = None

            # Extract domain from header comment
            domain_match = re.search(r'#\s+-+\s*\n#\s+(.+?)\s*\n#\s+-+', content)
            if domain_match:
                domain_line = domain_match.group(1).strip()
                domains = [d.strip() for d in domain_line.split(',')]
                if domains and not parsed.get("server_name"):
                    parsed["server_name"] = domains[0]
                    parsed["server_name_aliases"] = domains[1:] if len(domains) > 1 else []

            # Extract certificate info
            cert_path_match = re.search(r'ssl_certificate\s+/etc/letsencrypt/live/([^/]+)/', content)
            if cert_path_match:
                cert_id_str = cert_path_match.group(1)
                parsed["certificate_path_id"] = cert_id_str

                # Extract numeric certificate ID from "npm-9" format
                if cert_id_str.startswith('npm-'):
                    try:
                        cert_id_numeric = int(cert_id_str.split('-')[1])
                        parsed["certificate_id"] = cert_id_numeric
                    except (ValueError, IndexError):
                        parsed["certificate_id"] = None
                else:
                    parsed["certificate_id"] = None

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

    def create_proxy_host_entity(
        self,
        parsed_config: Dict[str, Any],
        file_path: str
    ) -> Optional[Dict[str, Any]]:
        """
        Create a complete proxy_host entity from parsed configuration.

        Args:
            parsed_config: Parsed configuration from parse() method
            file_path: Path to the original config file

        Returns:
            Complete proxy_host entity dict, or None if required fields missing
        """
        try:
            domain = parsed_config.get("server_name")
            if not domain:
                return None

            # Generate entity ID
            domain_slug = domain.lower().replace('.', '-').replace('_', '-')
            entity_id = f"proxy_{domain_slug}"

            # Build title
            title = f"Reverse Proxy - {domain}"

            # Generate rich content for vector search
            content = self._generate_content_description(parsed_config, domain)

            # Collect all domain names
            domain_names = [domain]
            if parsed_config.get("server_name_aliases"):
                domain_names.extend(parsed_config["server_name_aliases"])

            # SSL info
            ssl_enabled = parsed_config.get("ssl_enabled", False)
            force_ssl = parsed_config.get("force_ssl", False)
            certificate_id = parsed_config.get("certificate_id")

            # Determine certificate name
            cert_name = None
            cert_provider = None
            if ssl_enabled and certificate_id:
                if certificate_id == 9:
                    cert_name = "*.maxseiner.casa"
                    cert_provider = "letsencrypt"
                else:
                    cert_name = f"Certificate {certificate_id}"
                    cert_provider = "letsencrypt"

            # Build tier 2 metadata
            metadata = {
                "domain": domain,
                "domain_names": domain_names,
                "backend_host": parsed_config.get("upstream_ip"),
                "backend_port": parsed_config.get("upstream_port"),
                "backend_protocol": parsed_config.get("forward_scheme", "http"),
                "ssl_enabled": ssl_enabled,
                "force_ssl": force_ssl,
                "certificate_id": certificate_id,
                "enabled": True,
                "npm_id": parsed_config.get("npm_id"),
                "created_at": None,
                "last_updated": datetime.now().isoformat()
            }

            # Build tier 3 details
            details = {
                "frontend": {
                    "domain_names": domain_names,
                    "scheme": "https" if ssl_enabled else "http",
                    "listen_port": 443 if ssl_enabled else 80,
                    "force_ssl": force_ssl,
                    "hsts_enabled": parsed_config.get("hsts_enabled", False),
                    "hsts_subdomains": False,
                    "http2_support": parsed_config.get("http2_enabled", False),
                    "ipv6": parsed_config.get("ipv6", True)
                },
                "backend": {
                    "forward_host": parsed_config.get("upstream_ip"),
                    "forward_port": parsed_config.get("upstream_port"),
                    "forward_scheme": parsed_config.get("forward_scheme", "http"),
                    "preserve_host": False,
                    "custom_locations": None
                },
                "ssl": {
                    "certificate_id": certificate_id,
                    "certificate_name": cert_name,
                    "provider": cert_provider,
                    "domain_names": [cert_name] if cert_name else None,
                    "expires": "2025-11-21" if cert_name == "*.maxseiner.casa" else None,
                    "auto_renew": True if ssl_enabled else None,
                    "certificate_path": parsed_config.get("ssl_certificate"),
                    "key_path": parsed_config.get("ssl_certificate_key"),
                    "intermediate_path": None
                } if ssl_enabled else None,
                "caching": {
                    "enabled": parsed_config.get("asset_caching", True),
                    "cache_time": None,
                    "cache_valid_codes": None
                },
                "access": {
                    "auth_enabled": False,
                    "auth_type": None,
                    "auth_users": None,
                    "allow_ips": None,
                    "deny_ips": None,
                    "access_list_id": None
                },
                "advanced": {
                    "websocket_support": False,
                    "block_exploits": parsed_config.get("block_exploits", False),
                    "custom_nginx_config": None,
                    "access_log_disabled": False,
                    "error_log_disabled": False
                },
                "performance": {
                    "http2": parsed_config.get("http2_enabled", False),
                    "gzip": True,
                    "client_max_body_size": None
                },
                "npm_metadata": {
                    "npm_id": parsed_config.get("npm_id"),
                    "owner_user_id": None,
                    "is_deleted": False
                },
                "notes": None
            }

            # Build complete 3-tier entity
            proxy_host = {
                # Root
                "id": entity_id,
                "type": "proxy_host",

                # Tier 1: Vector Search
                "title": title,
                "content": content,

                # Tier 2: Metadata
                "metadata": metadata,

                # Tier 3: Details
                "details": details
            }

            return proxy_host

        except Exception as e:
            print(f"Error creating proxy_host entity from {file_path}: {e}")
            return None

    def _generate_content_description(
        self,
        parsed_config: Dict[str, Any],
        domain: str
    ) -> str:
        """
        Generate rich content description for vector search.

        Args:
            parsed_config: Parsed configuration dict
            domain: Primary domain name

        Returns:
            Multi-sentence description of the proxy host
        """
        parts = []

        # Main description
        backend = f"{parsed_config.get('upstream_ip')}:{parsed_config.get('upstream_port')}"
        protocol = parsed_config.get('forward_scheme', 'http')
        ssl_enabled = parsed_config.get('ssl_enabled', False)

        parts.append(
            f"Nginx Proxy Manager reverse proxy configuration for {domain} providing "
            f"{'secure HTTPS' if ssl_enabled else 'HTTP'} access to backend service. "
            f"Routes {'public' if ssl_enabled else 'internal'} traffic from domain "
            f"to backend service at {backend}."
        )

        # SSL details
        if ssl_enabled:
            cert_id = parsed_config.get('certificate_id')
            if cert_id == 9:
                cert_info = "Let's Encrypt wildcard certificate for *.maxseiner.casa"
            else:
                cert_info = "SSL certificate"

            parts.append(f"SSL termination using {cert_info} with automatic renewal.")

            if parsed_config.get('hsts_enabled'):
                parts.append("HSTS enabled for enhanced security requiring HTTPS connections.")

        # Protocol support
        if parsed_config.get('http2_enabled'):
            parts.append("HTTP/2 protocol support for improved performance.")

        # Security
        if parsed_config.get('block_exploits'):
            parts.append("Common exploit blocking enabled.")

        # Caching
        if parsed_config.get('asset_caching'):
            parts.append("Asset caching enabled for static content.")

        # Backend protocol
        parts.append(f"Backend service uses {protocol.upper()} protocol.")

        # Multiple domains
        if parsed_config.get('server_name_aliases'):
            other_domains = ', '.join(parsed_config['server_name_aliases'])
            parts.append(f"Also accessible via alternate domains: {other_domains}.")

        return ' '.join(parts)
