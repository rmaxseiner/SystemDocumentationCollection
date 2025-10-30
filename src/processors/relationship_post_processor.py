#!/usr/bin/env python3
"""
Relationship Post-Processor

Infers and creates relationships between entities based on domain names and IP:port matching:
1. DNS → Proxy relationships (domain-based matching)
2. Proxy → Service relationships (IP:port-based matching)

Author: System Documentation Collection
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime


class RelationshipPostProcessor:
    """
    Post-processor that infers relationships between entities after all data has been collected.

    Creates:
    - DNS → Proxy (ROUTES_TO/ROUTES_FROM) based on domain matching
    - Proxy → Service (PROXIES/PROXIED_BY) based on IP:port matching
    """

    def __init__(self, rag_data_path: Path):
        """
        Initialize the relationship post-processor.

        Args:
            rag_data_path: Path to rag_data.json file
        """
        self.rag_data_path = rag_data_path
        self.logger = logging.getLogger(__name__)

        self.documents = []
        self.relationships = []

        # Statistics
        self.stats = {
            'dns_proxy_matched': 0,
            'dns_proxy_unmatched': 0,
            'proxy_service_matched': 0,
            'proxy_service_unmatched': 0,
            'relationships_created': 0
        }

    def process(self) -> bool:
        """
        Main processing method.

        Returns:
            True if successful, False otherwise
        """
        try:
            self.logger.info("Starting relationship post-processing")

            # Load rag_data.json
            if not self._load_rag_data():
                return False

            # Build relationships
            dns_proxy_rels = self._build_dns_proxy_relationships()
            proxy_service_rels = self._build_proxy_service_relationships()

            # Add new relationships to existing ones
            new_relationships = dns_proxy_rels + proxy_service_rels
            self.relationships.extend(new_relationships)
            self.stats['relationships_created'] = len(new_relationships)

            # Save updated rag_data.json
            if not self._save_rag_data():
                return False

            # Log statistics
            self._log_statistics()

            self.logger.info(f"Relationship post-processing completed: {len(new_relationships)} relationships created")
            return True

        except Exception as e:
            self.logger.error(f"Relationship post-processing failed: {e}", exc_info=True)
            return False

    def _load_rag_data(self) -> bool:
        """Load rag_data.json"""
        try:
            if not self.rag_data_path.exists():
                self.logger.error(f"rag_data.json not found at {self.rag_data_path}")
                return False

            with open(self.rag_data_path, 'r') as f:
                rag_data = json.load(f)

            self.documents = rag_data.get('documents', [])
            self.relationships = rag_data.get('relationships', [])

            self.logger.info(f"Loaded {len(self.documents)} documents and {len(self.relationships)} existing relationships")
            return True

        except Exception as e:
            self.logger.error(f"Failed to load rag_data.json: {e}")
            return False

    def _save_rag_data(self) -> bool:
        """Save updated rag_data.json"""
        try:
            with open(self.rag_data_path, 'r') as f:
                rag_data = json.load(f)

            # Update relationships
            rag_data['relationships'] = self.relationships

            # Update metadata
            rag_data['metadata']['export_timestamp'] = datetime.now().isoformat()
            rag_data['metadata']['relationship_post_processing'] = {
                'processed_at': datetime.now().isoformat(),
                'relationships_added': self.stats['relationships_created'],
                'dns_proxy_matched': self.stats['dns_proxy_matched'],
                'proxy_service_matched': self.stats['proxy_service_matched']
            }

            # Save
            with open(self.rag_data_path, 'w') as f:
                json.dump(rag_data, f, indent=2, default=str)

            self.logger.info(f"Saved updated rag_data.json with {len(self.relationships)} total relationships")
            return True

        except Exception as e:
            self.logger.error(f"Failed to save rag_data.json: {e}")
            return False

    def _build_dns_proxy_relationships(self) -> List[Dict[str, Any]]:
        """
        Build DNS → Proxy relationships based on domain matching.

        Matching logic:
        - DNS domain matches Proxy primary domain OR any domain alias

        Returns:
            List of new relationship objects
        """
        self.logger.info("Building DNS → Proxy relationships")

        relationships = []
        timestamp = datetime.now().isoformat()

        # Get all DNS records and proxy hosts
        dns_records = [d for d in self.documents if d.get('type') == 'dns_record']
        proxy_hosts = [d for d in self.documents if d.get('type') == 'proxy_host']

        # Deduplicate by ID (keep first occurrence)
        seen_dns = set()
        dns_records = [d for d in dns_records if d.get('id') not in seen_dns and not seen_dns.add(d.get('id'))]

        seen_proxies = set()
        proxy_hosts = [d for d in proxy_hosts if d.get('id') not in seen_proxies and not seen_proxies.add(d.get('id'))]

        self.logger.info(f"Found {len(dns_records)} DNS records and {len(proxy_hosts)} proxy hosts (after deduplication)")

        # Match each DNS record to proxy hosts
        for dns in dns_records:
            dns_id = dns.get('id')
            dns_domain = dns.get('metadata', {}).get('domain')

            if not dns_domain:
                self.logger.warning(f"DNS record {dns_id} missing domain field")
                continue

            # Find matching proxy host(s)
            matching_proxies = []
            for proxy in proxy_hosts:
                proxy_domain = proxy.get('metadata', {}).get('domain')
                proxy_domain_names = proxy.get('metadata', {}).get('domain_names', [])

                # Match primary domain or any alias
                if dns_domain == proxy_domain or dns_domain in proxy_domain_names:
                    matching_proxies.append(proxy)

            if matching_proxies:
                self.stats['dns_proxy_matched'] += 1

                for proxy in matching_proxies:
                    proxy_id = proxy.get('id')

                    # Create bidirectional relationships
                    # DNS ROUTES_TO Proxy
                    relationships.append({
                        'id': f'{dns_id}_routes_to_{proxy_id}',
                        'type': 'ROUTES_TO',
                        'source_id': dns_id,
                        'source_type': 'dns_record',
                        'target_id': proxy_id,
                        'target_type': 'proxy_host',
                        'metadata': {
                            'matching_method': 'domain',
                            'matched_domain': dns_domain,
                            'created_at': timestamp
                        }
                    })

                    # Proxy ROUTES_FROM DNS
                    relationships.append({
                        'id': f'{proxy_id}_routes_from_{dns_id}',
                        'type': 'ROUTES_FROM',
                        'source_id': proxy_id,
                        'source_type': 'proxy_host',
                        'target_id': dns_id,
                        'target_type': 'dns_record',
                        'metadata': {
                            'matching_method': 'domain',
                            'matched_domain': dns_domain,
                            'created_at': timestamp
                        }
                    })

                    self.logger.debug(f"Matched DNS {dns_domain} to Proxy {proxy_id}")
            else:
                self.stats['dns_proxy_unmatched'] += 1
                self.logger.warning(f"No matching proxy found for DNS record: {dns_domain} ({dns_id})")

        self.logger.info(f"Created {len(relationships)} DNS ↔ Proxy relationships")
        return relationships

    def _build_proxy_service_relationships(self) -> List[Dict[str, Any]]:
        """
        Build Proxy → Service relationships based on IP:port matching.

        Matching logic:
        1. Get proxy backend IP:port
        2. Find containers with matching host_port
        3. Extract server name from container ID
        4. Find server and match IP
        5. Get service from container.part_of_service

        Returns:
            List of new relationship objects
        """
        self.logger.info("Building Proxy → Service relationships")

        relationships = []
        timestamp = datetime.now().isoformat()

        # Get all proxy hosts, containers, and servers
        proxy_hosts = [d for d in self.documents if d.get('type') == 'proxy_host']
        containers = [d for d in self.documents if d.get('type') == 'container']
        servers = [d for d in self.documents if 'server' in d.get('type', '')]

        # Deduplicate by ID (keep first occurrence)
        seen_proxies = set()
        proxy_hosts = [d for d in proxy_hosts if d.get('id') not in seen_proxies and not seen_proxies.add(d.get('id'))]

        seen_containers = set()
        containers = [d for d in containers if d.get('id') not in seen_containers and not seen_containers.add(d.get('id'))]

        seen_servers = set()
        servers = [d for d in servers if d.get('id') not in seen_servers and not seen_servers.add(d.get('id'))]

        self.logger.info(f"Found {len(proxy_hosts)} proxy hosts, {len(containers)} containers, {len(servers)} servers (after deduplication)")

        # Build server lookup by name
        server_by_name = {}
        for server in servers:
            server_id = server.get('id', '')
            # Extract server name from ID (e.g., "server_unraid-server" → "unraid-server")
            parts = server_id.split('_', 1)
            if len(parts) >= 2:
                server_name = parts[1]
                if server_name not in server_by_name:
                    server_by_name[server_name] = []
                server_by_name[server_name].append(server)

        # Match each proxy to services
        for proxy in proxy_hosts:
            proxy_id = proxy.get('id')
            backend_host = proxy.get('metadata', {}).get('backend_host')
            backend_port = proxy.get('metadata', {}).get('backend_port')
            backend_protocol = proxy.get('metadata', {}).get('backend_protocol', 'http')

            if not backend_host or not backend_port:
                self.logger.debug(f"Proxy {proxy_id} missing backend configuration")
                continue

            # Skip localhost/127.0.0.1 (proxy and service on same host)
            if backend_host in ['localhost', '127.0.0.1', '::1']:
                self.logger.debug(f"Skipping proxy {proxy_id} with localhost backend")
                continue

            # Find matching containers
            matched_services = set()

            for container in containers:
                container_id = container.get('id')

                # Get port bindings
                ports = container.get('details', {}).get('ports', [])

                for port_binding in ports:
                    host_port = port_binding.get('host_port')
                    host_ip = port_binding.get('host_ip')

                    # Check if port matches
                    if host_port != backend_port:
                        continue

                    # Extract server name from container ID
                    # Format: "container_{server_name}_{container_name}"
                    container_parts = container_id.split('_', 2)
                    if len(container_parts) < 2:
                        self.logger.debug(f"Cannot extract server name from container ID: {container_id}")
                        continue

                    server_name = container_parts[1]

                    # Find server(s) by name
                    matching_servers = server_by_name.get(server_name, [])

                    if not matching_servers:
                        self.logger.debug(f"No server found for name: {server_name} (from container {container_id})")
                        continue

                    # Check if server IP matches backend host
                    for server in matching_servers:
                        server_ip = server.get('metadata', {}).get('primary_ip')

                        if server_ip != backend_host:
                            continue

                        # Match! Get the service this container belongs to
                        service_id = container.get('metadata', {}).get('part_of_service')

                        if not service_id:
                            self.logger.debug(f"Container {container_id} not part of any service")
                            continue

                        # Found a match - add service to matched set
                        matched_services.add(service_id)

                        self.logger.debug(
                            f"Matched Proxy {proxy_id} ({backend_host}:{backend_port}) "
                            f"to Service {service_id} via container {container_id}"
                        )

            # Create relationships for all matched services
            if matched_services:
                self.stats['proxy_service_matched'] += 1

                for service_id in matched_services:
                    # Proxy PROXIES Service
                    relationships.append({
                        'id': f'{proxy_id}_proxies_{service_id}',
                        'type': 'PROXIES',
                        'source_id': proxy_id,
                        'source_type': 'proxy_host',
                        'target_id': service_id,
                        'target_type': 'service',
                        'metadata': {
                            'matching_method': 'ip_port',
                            'backend_host': backend_host,
                            'backend_port': backend_port,
                            'backend_protocol': backend_protocol,
                            'created_at': timestamp
                        }
                    })

                    # Service PROXIED_BY Proxy
                    relationships.append({
                        'id': f'{service_id}_proxied_by_{proxy_id}',
                        'type': 'PROXIED_BY',
                        'source_id': service_id,
                        'source_type': 'service',
                        'target_id': proxy_id,
                        'target_type': 'proxy_host',
                        'metadata': {
                            'matching_method': 'ip_port',
                            'backend_host': backend_host,
                            'backend_port': backend_port,
                            'backend_protocol': backend_protocol,
                            'created_at': timestamp
                        }
                    })
            else:
                self.stats['proxy_service_unmatched'] += 1
                self.logger.warning(
                    f"No matching service found for Proxy: {proxy_id} "
                    f"(backend {backend_host}:{backend_port})"
                )

        self.logger.info(f"Created {len(relationships)} Proxy ↔ Service relationships")
        return relationships

    def _log_statistics(self):
        """Log processing statistics"""
        self.logger.info("=" * 80)
        self.logger.info("Relationship Post-Processing Statistics")
        self.logger.info("=" * 80)
        self.logger.info(f"DNS → Proxy Matching:")
        self.logger.info(f"  Matched: {self.stats['dns_proxy_matched']}")
        self.logger.info(f"  Unmatched: {self.stats['dns_proxy_unmatched']}")
        self.logger.info(f"Proxy → Service Matching:")
        self.logger.info(f"  Matched: {self.stats['proxy_service_matched']}")
        self.logger.info(f"  Unmatched: {self.stats['proxy_service_unmatched']}")
        self.logger.info(f"Total Relationships Created: {self.stats['relationships_created']}")
        self.logger.info("=" * 80)


def main():
    """Standalone execution for testing"""
    import sys

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )

    # Get rag_data.json path
    if len(sys.argv) > 1:
        rag_data_path = Path(sys.argv[1])
    else:
        rag_data_path = Path('rag_output/rag_data.json')

    # Run processor
    processor = RelationshipPostProcessor(rag_data_path)
    success = processor.process()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
