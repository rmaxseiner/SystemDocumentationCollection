# src/processors/host_processor.py
"""
Host RAG processor for Proxmox VMs and LXC containers.
Processes [hostname]_proxmox.json files to extract VMs and LXC containers
and generate host documents for the RAG data pipeline.

Outputs host documents and updates rag_data.json with entities and relationships.
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import re

from .base_processor import BaseProcessor, ProcessingResult
from ..utils.rag_utils import TemporalDataCleaner, MetadataExtractor, RAGDataAssembler
from ..utils.llm_client import create_llm_client, LLMRequest
from ..utils.content_validator import ContentValidator


class HostProcessor(BaseProcessor):
    """
    Processes Proxmox VM and LXC container data to generate host documents.
    Updates rag_data.json with host entities and relationships to physical servers.
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

        # Processing configuration
        self.output_dir = config.get('output_directory', 'rag_output')
        self.collected_data_dir = config.get('collected_data_directory', 'collected_data')

    def validate_config(self) -> bool:
        """Validate processor configuration"""
        required_paths = [self.output_dir, self.collected_data_dir]

        for path_str in required_paths:
            path = Path(path_str)
            if not path.exists():
                self.logger.warning(f"Path does not exist: {path}")

        return True

    def process(self, collected_data: Dict[str, Any]) -> ProcessingResult:
        """
        Process Proxmox data to generate host documents.

        Args:
            collected_data: Dictionary containing results from collectors

        Returns:
            ProcessingResult: Contains processed host data
        """
        try:
            self.logger.info("Starting host processing...")

            # Find all Proxmox data files
            proxmox_files = self._find_proxmox_files()
            if not proxmox_files:
                return ProcessingResult(
                    success=False,
                    error="No Proxmox data files found"
                )

            # Initialize LLM client if needed
            if self.enable_llm_tagging:
                try:
                    self.llm_client = create_llm_client(self.llm_config)
                except Exception as e:
                    self.logger.warning(f"Failed to initialize LLM client: {e}")
                    self.enable_llm_tagging = False

            # Process each Proxmox file
            all_hosts = []
            system_stats = {}

            for file_path in proxmox_files:
                hosts, stats = self._process_proxmox_file(file_path)
                all_hosts.extend(hosts)
                system_stats.update(stats)

            # Generate RAG documents
            documents = self._generate_rag_documents(all_hosts)
            entities = self._generate_entities(system_stats)
            relationships = self._generate_relationships(all_hosts)

            # Update rag_data.json
            self._update_rag_data(documents, entities, relationships)

            result_data = {
                'hosts_processed': len(all_hosts),
                'systems_found': len(system_stats),
                'documents_generated': len(documents),
                'relationships_created': len(relationships)
            }

            self.logger.info(f"Host processing completed: {result_data}")

            return ProcessingResult(
                success=True,
                data=result_data
            )

        except Exception as e:
            self.logger.error(f"Host processing failed: {e}", exc_info=True)
            return ProcessingResult(
                success=False,
                error=str(e)
            )

    def _find_proxmox_files(self) -> List[Path]:
        """Find all *_proxmox.json files in the collected_data directory"""
        data_dir = Path(self.collected_data_dir)
        if not data_dir.exists():
            return []

        # Find files matching pattern [hostname]_proxmox.json
        proxmox_files = list(data_dir.glob("*_proxmox.json"))
        self.logger.info(f"Found {len(proxmox_files)} Proxmox data files")

        return proxmox_files

    def _process_proxmox_file(self, file_path: Path) -> tuple[List[Dict], Dict]:
        """Process a single Proxmox data file"""
        # Extract hostname from filename (e.g., pve-nuc_proxmox.json -> pve-nuc)
        hostname = file_path.stem.replace('_proxmox', '')

        try:
            with open(file_path, 'r') as f:
                data = json.load(f)

            if not data.get('success') or 'data' not in data:
                self.logger.warning(f"Invalid data format in {file_path}")
                return [], {}

            proxmox_data = data['data']

            # Process VMs
            hosts = []
            vms = proxmox_data.get('vms', [])
            lxc_containers = proxmox_data.get('lxc_containers', [])

            for vm in vms:
                host_info = self._process_vm(vm, hostname)
                if host_info:
                    hosts.append(host_info)

            for lxc in lxc_containers:
                host_info = self._process_lxc(lxc, hostname)
                if host_info:
                    hosts.append(host_info)

            # Generate system stats
            system_stats = {
                hostname: {
                    'type': 'proxmox',
                    'vm_count': len(vms),
                    'lxc_count': len(lxc_containers),
                    'status': 'active'
                }
            }

            self.logger.info(f"Processed {hostname}: {len(vms)} VMs, {len(lxc_containers)} LXC containers")

            return hosts, system_stats

        except Exception as e:
            self.logger.error(f"Failed to process {file_path}: {e}")
            return [], {}

    def _process_vm(self, vm_data: Dict, physical_server: str) -> Optional[Dict]:
        """Process a single VM entry"""
        try:
            vmid = vm_data.get('vmid', '')
            name = vm_data.get('name', f'vm-{vmid}')
            status = vm_data.get('status', 'unknown')
            config = vm_data.get('configuration', {})

            # Extract network info
            ip_address = None
            network_vlan = None

            # Parse network configuration (net0, net1, etc.)
            for key, value in config.items():
                if key.startswith('net') and isinstance(value, str):
                    # Extract VLAN tag if present
                    if 'tag=' in value:
                        vlan_match = re.search(r'tag=(\d+)', value)
                        if vlan_match:
                            network_vlan = vlan_match.group(1)
                    break

            # Create host info
            host_info = {
                'id': f'host_{physical_server}_vm-{vmid}',
                'host_id': f'vm-{vmid}',
                'host_type': 'vm',
                'name': name,
                'hosted_by': physical_server,
                'status': status,
                'cpu_cores': int(config.get('cores', 1)),
                'memory_mb': int(config.get('memory', 512)),
                'ip_address': ip_address,
                'hostname': name,
                'os_type': config.get('ostype', 'unknown'),
                'network_vlan': network_vlan,
                'boot_on_start': config.get('onboot') == '1',
                'virtualization_features': [],
                'raw_config': config
            }

            return host_info

        except Exception as e:
            self.logger.warning(f"Failed to process VM {vm_data.get('vmid', 'unknown')}: {e}")
            return None

    def _process_lxc(self, lxc_data: Dict, physical_server: str) -> Optional[Dict]:
        """Process a single LXC container entry"""
        try:
            vmid = lxc_data.get('vmid', '')
            name = lxc_data.get('name', f'lxc-{vmid}')
            status = lxc_data.get('status', 'unknown')
            config = lxc_data.get('configuration', {})

            # Extract network info
            ip_address = None
            network_vlan = None

            # Parse network configuration
            net0 = config.get('net0', '')
            if net0:
                # Extract IP address
                ip_match = re.search(r'ip=([^,]+)', net0)
                if ip_match:
                    ip_address = ip_match.group(1)

                # Extract VLAN tag
                vlan_match = re.search(r'tag=(\d+)', net0)
                if vlan_match:
                    network_vlan = vlan_match.group(1)

            # Extract storage allocation
            storage_allocation = None
            rootfs = config.get('rootfs', '')
            if rootfs:
                size_match = re.search(r'size=(\d+[GMK])', rootfs)
                if size_match:
                    storage_allocation = size_match.group(1)

            # Extract virtualization features
            virt_features = []
            features = config.get('features', '')
            if features:
                if 'nesting=1' in features:
                    virt_features.append('nesting')

            # Create host info
            host_info = {
                'id': f'host_{physical_server}_lxc-{vmid}',
                'host_id': f'lxc-{vmid}',
                'host_type': 'lxc',
                'name': name,
                'hosted_by': physical_server,
                'status': status,
                'cpu_cores': int(config.get('cores', 1)),
                'memory_mb': int(config.get('memory', 512)),
                'ip_address': ip_address,
                'hostname': config.get('hostname', name),
                'os_type': config.get('ostype', 'unknown'),
                'storage_allocation': storage_allocation,
                'network_vlan': network_vlan,
                'boot_on_start': config.get('onboot') == '1',
                'virtualization_features': virt_features,
                'raw_config': config
            }

            return host_info

        except Exception as e:
            self.logger.warning(f"Failed to process LXC {lxc_data.get('vmid', 'unknown')}: {e}")
            return None

    def _generate_rag_documents(self, hosts: List[Dict]) -> List[Dict]:
        """Generate RAG documents for hosts"""
        documents = []

        for host in hosts:
            try:
                # Generate content description
                content = self._generate_host_content(host)

                # Generate tags
                tags = self._generate_host_tags(host)

                # Create document
                doc = {
                    'id': host['id'],
                    'type': 'host',
                    'title': f"{host['name']} ({host['host_type'].upper()}) on {host['hosted_by']}",
                    'content': content,
                    'metadata': {
                        'host_id': host['host_id'],
                        'host_type': host['host_type'],
                        'name': host['name'],
                        'hosted_by': host['hosted_by'],
                        'status': host['status'],
                        'cpu_cores': host['cpu_cores'],
                        'memory_mb': host['memory_mb'],
                        'ip_address': host['ip_address'],
                        'hostname': host['hostname'],
                        'os_type': host['os_type']
                    },
                    'tags': tags
                }

                documents.append(doc)

            except Exception as e:
                self.logger.warning(f"Failed to generate document for host {host.get('id', 'unknown')}: {e}")

        return documents

    def _generate_host_content(self, host: Dict) -> str:
        """Generate human-readable content for a host"""
        host_type = host['host_type'].upper()
        name = host['name']
        hosted_by = host['hosted_by']
        status = host['status']
        cores = host['cpu_cores']
        memory_gb = round(host['memory_mb'] / 1024, 1)
        os_type = host['os_type']

        content_parts = [
            f"{name} is a {os_type} {host_type}",
            f"(ID: {host['host_id']}) {status} on {hosted_by}",
            f"with {cores} CPU cores and {memory_gb}GB memory."
        ]

        # Add IP address if available
        if host.get('ip_address'):
            content_parts.append(f"It has IP {host['ip_address']}")
            if host.get('network_vlan'):
                content_parts[-1] += f" on VLAN {host['network_vlan']}"
            content_parts[-1] += "."

        # Add storage info for LXC
        if host['host_type'] == 'lxc' and host.get('storage_allocation'):
            content_parts.append(f"Storage allocation: {host['storage_allocation']}.")

        # Add boot info
        if host.get('boot_on_start'):
            content_parts.append("It boots automatically.")

        # Add virtualization features
        if host.get('virtualization_features'):
            features = ', '.join(host['virtualization_features'])
            content_parts.append(f"Supports {features}.")

        return ' '.join(content_parts)

    def _generate_host_tags(self, host: Dict) -> List[str]:
        """Generate tags for a host"""
        tags = [
            host['host_type'],
            'virtualization',
            'proxmox',
            'host',
            host['os_type']
        ]

        # Add status-based tags
        if host['status'] == 'running':
            tags.append('active')
        elif host['status'] == 'stopped':
            tags.append('inactive')

        # Add feature-based tags
        if host.get('virtualization_features'):
            tags.extend(host['virtualization_features'])

        # Add network tags
        if host.get('network_vlan'):
            tags.append(f"vlan-{host['network_vlan']}")

        # Use LLM for additional tagging if enabled
        if self.enable_llm_tagging and self.llm_client:
            try:
                llm_tags = self._get_llm_tags(host)
                tags.extend(llm_tags)
            except Exception as e:
                self.logger.warning(f"LLM tagging failed for {host['id']}: {e}")

        # Remove duplicates and return
        return list(set(tags))

    def _get_llm_tags(self, host: Dict) -> List[str]:
        """Get additional tags from LLM based on host information"""
        content = self._generate_host_content(host)

        # Create LLM request with correct dataclass fields
        request = LLMRequest(
            entity_id=host['id'],
            entity_type='host',
            content=content,
            context={
                'processor': 'host',
                'host_type': host.get('host_type', 'unknown')
            }
        )

        # Use generate_tags method (batch API)
        responses = self.llm_client.generate_tags([request])

        if responses and len(responses) > 0 and responses[0].success:
            # Extract tags from response
            if responses[0].tags:
                return list(responses[0].tags.values())

        return []

    def _generate_entities(self, system_stats: Dict) -> Dict:
        """Generate entities for systems hosting VMs/LXC containers"""
        entities = {}

        for hostname, stats in system_stats.items():
            entities[hostname] = {
                'type': stats['type'],
                'vm_count': stats['vm_count'],
                'lxc_count': stats['lxc_count'],
                'total_hosts': stats['vm_count'] + stats['lxc_count'],
                'status': stats['status']
            }

        return entities

    def _generate_relationships(self, hosts: List[Dict]) -> List[Dict]:
        """Generate relationships between hosts and physical servers"""
        relationships = []

        for host in hosts:
            relationship = {
                'id': f"host_{host['host_id']}_hosted_on_{host['hosted_by']}",
                'type': 'hosted_on',
                'source_id': host['id'],
                'source_type': 'host',
                'target_id': host['hosted_by'],
                'target_type': 'server',
                'metadata': {
                    'relationship_type': 'virtualization',
                    'host_type': host['host_type'],
                    'description': f"Host {host['name']} is hosted on physical server {host['hosted_by']}"
                }
            }
            relationships.append(relationship)

        return relationships

    def _update_rag_data(self, documents: List[Dict], entities: Dict, relationships: List[Dict]):
        """Update the main rag_data.json file with new host data"""
        rag_file = Path(self.output_dir) / 'rag_data.json'

        # Load existing data or create new structure
        if rag_file.exists():
            with open(rag_file, 'r') as f:
                rag_data = json.load(f)
        else:
            rag_data = {
                'metadata': {},
                'documents': [],
                'entities': {'systems': {}},
                'relationships': []
            }

        # Update metadata
        rag_data['metadata'].update({
            'host_processing_timestamp': datetime.now().isoformat(),
            'total_hosts': len(documents)
        })

        # Remove existing host documents to avoid duplicates
        rag_data['documents'] = [
            doc for doc in rag_data['documents']
            if not doc.get('id', '').startswith('host_')
        ]

        # Add new host documents
        rag_data['documents'].extend(documents)

        # Update entities
        rag_data['entities']['systems'].update(entities)

        # Remove existing host relationships
        rag_data['relationships'] = [
            rel for rel in rag_data['relationships']
            if rel.get('type') != 'hosted_on'
        ]

        # Add new relationships
        rag_data['relationships'].extend(relationships)

        # Save updated data
        self._create_output_directory(self.output_dir)
        with open(rag_file, 'w') as f:
            json.dump(rag_data, f, indent=2, default=str)

        self.logger.info(f"Updated {rag_file} with {len(documents)} host documents")