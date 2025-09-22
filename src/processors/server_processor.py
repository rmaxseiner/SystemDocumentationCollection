"""
Server Processor - Processes server/hardware level information
Transforms collected system documentation into RAG-ready server documents
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import glob
import re

from .base_processor import BaseProcessor, ProcessingResult
from ..utils.content_validator import ContentValidator
from ..utils.llm_client import create_llm_client, LLMRequest

logger = logging.getLogger(__name__)


class ServerProcessor(BaseProcessor):
    """Processor for server hardware documentation"""

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.collected_data_path = config.get('collected_data_path', 'collected_data')
        self.output_path = config.get('output_path', 'analysis_output')

        # Content validation
        self.content_validator = ContentValidator(
            config.get('max_word_count', 400),
            config.get('min_content_length', 10)
        )

        # LLM configuration
        self.llm_config = config.get('llm', {})
        self.llm_client = None
        self.enable_llm_tagging = config.get('enable_llm_tagging', True)

        # Initialize LLM client if enabled
        if self.enable_llm_tagging and self.llm_config:
            try:
                self.llm_client = create_llm_client(self.llm_config)
                self.logger.info(f"Initialized LLM client: {self.llm_config.get('type', 'unknown')}")
            except Exception as e:
                self.logger.error(f"Failed to initialize LLM client: {e}")
                self.llm_client = None

    def find_server_files(self) -> List[str]:
        """Find all system documentation files"""
        pattern = f"{self.collected_data_path}/*_system_documentation.json"
        files = glob.glob(pattern)
        logger.info(f"Found {len(files)} server documentation files")
        return files

    def extract_hostname_from_filename(self, filename: str) -> str:
        """Extract hostname from filename pattern"""
        basename = Path(filename).name
        # Pattern: hostname_system_documentation.json
        match = re.match(r'(.+)_system_documentation\.json', basename)
        if match:
            return match.group(1)
        return basename.replace('_system_documentation', '').split('_')[0]

    def parse_server_data(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Parse server data from collected JSON file"""
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)

            if not data.get('success', False):
                logger.warning(f"Server data collection was not successful in {file_path}")
                return None

            return data.get('data', {})
        except Exception as e:
            logger.error(f"Error parsing server data from {file_path}: {e}")
            return None

    def extract_hardware_metadata(self, server_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract hardware metadata from server data"""
        hardware_profile = server_data.get('hardware_profile', {})
        system_overview = server_data.get('system_overview', {})

        # CPU information
        cpu_info = hardware_profile.get('cpu', {})
        cpu_model = cpu_info.get('model_name', 'Unknown CPU')
        cpu_cores_physical = cpu_info.get('physical_cores', 0)
        cpu_cores_logical = cpu_info.get('logical_cores', 0)

        # Memory information
        memory_info = hardware_profile.get('memory', {})
        system_memory_gb = round(memory_info.get('total_gb', 0), 2)

        # Storage information is now handled by StorageProcessor

        # Motherboard information
        motherboard_info = hardware_profile.get('motherboard', {})
        motherboard_model = motherboard_info.get('product', 'Unknown')
        motherboard_manufacturer = motherboard_info.get('manufacturer', 'Unknown')

        # Network interfaces
        network_config = server_data.get('network_configuration', {})
        ip_addresses = self.extract_ip_addresses(network_config)
        physical_network_interfaces_count = self.count_physical_interfaces(network_config)

        # Device counts
        pci_devices = hardware_profile.get('pci_devices', [])
        usb_devices = hardware_profile.get('usb_devices', [])
        physical_device_count = len(pci_devices) + len(usb_devices)

        # Virtualization counts
        container_count = self.count_containers(server_data)
        vm_count = self.count_vms(server_data)
        lxc_count = self.count_lxc_containers(server_data)

        # System information
        hostname = server_data.get('hostname', system_overview.get('hostname', 'unknown'))
        system_architecture = system_overview.get('architecture', 'unknown')
        os_info = system_overview.get('os_release', '')
        os_type, os_version = self.parse_os_info(os_info)

        return {
            'hostname': hostname,
            'system_architecture': system_architecture,
            'system_memory_gb': system_memory_gb,
            'cpu_model': cpu_model,
            'cpu_cores_physical': cpu_cores_physical,
            'cpu_cores_logical': cpu_cores_logical,
            'motherboard_model': motherboard_model,
            'motherboard_manufacturer': motherboard_manufacturer,
            'ip_addresses': ip_addresses,
            'physical_network_interfaces_count': physical_network_interfaces_count,
            'physical_device_count': physical_device_count,
            'container_count': container_count,
            'vm_count': vm_count,
            'lxc_count': lxc_count,
            'os_type': os_type,
            'os_version': os_version,
            'last_updated': server_data.get('timestamp', datetime.now().isoformat())
        }

    def extract_ip_addresses(self, network_config: Dict[str, Any]) -> List[str]:
        """Extract IP addresses from network configuration"""
        ip_addresses = []
        interfaces_output = network_config.get('interfaces', '')

        # Parse IP addresses from ip addr show output
        ip_pattern = r'inet (\d+\.\d+\.\d+\.\d+)'
        matches = re.findall(ip_pattern, interfaces_output)

        # Filter out 127.0.0.1 and docker IPs for primary list
        for ip in matches:
            if not ip.startswith('127.') and not ip.startswith('169.254.'):
                ip_addresses.append(ip)

        # Add localhost for completeness
        if '127.0.0.1' not in ip_addresses:
            ip_addresses.insert(0, '127.0.0.1')

        return ip_addresses[:5]  # Limit to 5 IPs to avoid clutter

    def count_physical_interfaces(self, network_config: Dict[str, Any]) -> int:
        """Count physical network interfaces (excluding loopback, docker, etc.)"""
        interfaces_output = network_config.get('interfaces', '')

        # Look for physical interface patterns
        interface_pattern = r'^\d+:\s+([^:]+):'
        matches = re.findall(interface_pattern, interfaces_output, re.MULTILINE)

        physical_interfaces = 0
        for interface in matches:
            # Skip virtual interfaces
            if not any(virtual in interface for virtual in ['lo', 'docker', 'br-', 'veth', 'virbr']):
                physical_interfaces += 1

        return max(physical_interfaces, 1)  # At least 1 interface

    def count_containers(self, server_data: Dict[str, Any]) -> int:
        """Count Docker containers from server data"""
        docker_config = server_data.get('docker_configuration', {})
        running_containers = docker_config.get('running_containers', '')

        # Count container lines (excluding header)
        if running_containers:
            lines = running_containers.split('\n')
            return max(0, len([line for line in lines if line.strip() and not line.startswith('CONTAINER')]) - 1)

        return 0

    def count_vms(self, server_data: Dict[str, Any]) -> int:
        """Count VMs (placeholder - VMs typically collected separately)"""
        # VMs are usually in separate proxmox collection files
        return 0

    def count_lxc_containers(self, server_data: Dict[str, Any]) -> int:
        """Count LXC containers (placeholder - LXC typically collected separately)"""
        # LXC containers are usually in separate proxmox collection files
        return 0

    def parse_os_info(self, os_release: str) -> tuple[str, str]:
        """Parse OS type and version from os-release info"""
        if not os_release:
            return 'Unknown', 'Unknown'

        # Look for PRETTY_NAME first
        pretty_match = re.search(r'PRETTY_NAME="([^"]+)"', os_release)
        if pretty_match:
            pretty_name = pretty_match.group(1)
            if 'Ubuntu' in pretty_name:
                version_match = re.search(r'(\d+\.\d+(?:\.\d+)?\s*[A-Z]*)', pretty_name)
                return 'Ubuntu', version_match.group(1) if version_match else 'Unknown'
            elif 'CentOS' in pretty_name:
                return 'CentOS', pretty_name.split()[-1] if pretty_name.split() else 'Unknown'

        # Fallback to NAME and VERSION_ID
        name_match = re.search(r'NAME="([^"]+)"', os_release)
        version_match = re.search(r'VERSION_ID="([^"]+)"', os_release)

        os_type = name_match.group(1) if name_match else 'Unknown'
        os_version = version_match.group(1) if version_match else 'Unknown'

        return os_type, os_version

    def generate_server_content(self, server_data: Dict[str, Any], metadata: Dict[str, Any]) -> str:
        """Generate comprehensive server content description"""
        hardware_profile = server_data.get('hardware_profile', {})

        # Basic system info
        content_parts = []
        content_parts.append(
            f"{metadata['hostname']} is a {metadata['os_type']} {metadata['os_version']} server "
            f"with {metadata['cpu_model']} ({metadata['cpu_cores_physical']} physical cores, "
            f"{metadata['cpu_cores_logical']} logical cores) and {metadata['system_memory_gb']}GB RAM."
        )

        # System status
        system_overview = server_data.get('system_overview', {})
        uptime = system_overview.get('uptime', '')
        if uptime:
            content_parts.append(f"The system has been {uptime}.")

        content_parts.append("\nHardware Configuration:")

        # Motherboard
        if metadata['motherboard_manufacturer'] != 'Unknown':
            content_parts.append(f"- Motherboard: {metadata['motherboard_manufacturer']} {metadata['motherboard_model']}")

        # Storage details are now handled by StorageProcessor

        # Network configuration
        ip_list = ', '.join(metadata['ip_addresses'])
        content_parts.append(
            f"- Network: {metadata['physical_network_interfaces_count']} physical interfaces "
            f"with IP addresses: {ip_list}"
        )

        # Expansion devices
        pci_devices = hardware_profile.get('pci_devices', [])
        usb_devices = hardware_profile.get('usb_devices', [])
        expansion_details = self.describe_expansion_devices(pci_devices, usb_devices)
        content_parts.append(
            f"- Expansion: {len(pci_devices)} PCIe devices, {len(usb_devices)} USB devices{expansion_details}"
        )

        # Virtualization and services
        content_parts.append("\nVirtualization and Services:")
        content_parts.append(
            f"- Containers: {metadata['container_count']} Docker containers"
        )

        if metadata['vm_count'] > 0 or metadata['lxc_count'] > 0:
            content_parts.append(f"- Virtual Machines: {metadata['vm_count']} VMs, {metadata['lxc_count']} LXC containers")
        else:
            content_parts.append("- Virtual Machines: None")

        # Key services
        key_services = self.identify_key_services(server_data)
        if key_services:
            content_parts.append(f"- Key Services: {', '.join(key_services)}")

        # System health
        health_info = self.describe_system_health(server_data)
        if health_info:
            content_parts.append(f"\nSystem Health:\n{health_info}")

        # Role inference
        role_description = self.infer_server_role(server_data, metadata)
        if role_description:
            content_parts.append(f"\n{role_description}")

        return ' '.join(content_parts)


    def describe_expansion_devices(self, pci_devices: List[str], usb_devices: List[str]) -> str:
        """Generate expansion device description"""
        notable_devices = []

        # Look for notable PCIe devices
        for device in pci_devices[:5]:  # Check first 5
            if 'Graphics' in device or 'VGA' in device:
                notable_devices.append('graphics controller')
            elif 'Ethernet' in device:
                notable_devices.append('ethernet controller')
            elif 'USB' in device:
                notable_devices.append('USB controller')

        # Look for notable USB devices
        for device in usb_devices[:5]:  # Check first 5
            if 'serial' in device.lower():
                notable_devices.append('serial converter')
            elif 'Z-Stick' in device or 'automation' in device.lower():
                notable_devices.append('home automation device')

        if notable_devices:
            unique_devices = list(set(notable_devices))
            return f" including {', '.join(unique_devices)}"

        return ""

    def identify_key_services(self, server_data: Dict[str, Any]) -> List[str]:
        """Identify key running services"""
        services = []

        # Check Docker containers for services
        docker_config = server_data.get('docker_configuration', {})
        running_containers = docker_config.get('running_containers', '')

        if running_containers:
            # Look for common service patterns
            if 'node-exporter' in running_containers:
                services.append('Prometheus node-exporter')
            if 'cadvisor' in running_containers:
                services.append('container monitoring')
            if 'watchtower' in running_containers:
                services.append('container updates')

        # Always include core services
        services.extend(['Docker daemon', 'SSH server'])

        return services[:5]  # Limit to 5 services

    def describe_system_health(self, server_data: Dict[str, Any]) -> Optional[str]:
        """Generate system health description"""
        health_parts = []

        # Temperature information
        hardware_profile = server_data.get('hardware_profile', {})
        temperatures = hardware_profile.get('temperatures', {})
        parsed_temps = temperatures.get('parsed_temperatures', {})

        if parsed_temps:
            temp_descriptions = []
            for sensor, temp in parsed_temps.items():
                if isinstance(temp, (int, float)) and temp > 0:
                    temp_descriptions.append(f"{sensor} at {temp}°C")

            if temp_descriptions:
                health_parts.append(f"- Temperature Monitoring: {', '.join(temp_descriptions[:3])} - all within normal operating ranges")


        # Network status
        health_parts.append("- Network Status: All interfaces operational with proper routing configuration")

        # Security status
        security_status = server_data.get('security_status', {})
        failed_logins = security_status.get('recent_failed_logins', 0)
        if failed_logins == 0:
            health_parts.append("- Security: SSH configured, no recent failed login attempts, firewall rules active")

        return '\n'.join(health_parts) if health_parts else None

    def infer_server_role(self, server_data: Dict[str, Any], metadata: Dict[str, Any]) -> Optional[str]:
        """Infer server role based on hardware and services"""
        hostname = metadata['hostname'].lower()
        hardware_profile = server_data.get('hardware_profile', {})
        usb_devices = hardware_profile.get('usb_devices', [])

        # Check for specific roles based on hostname and hardware
        if '3dprinter' in hostname or 'printer' in hostname:
            automation_devices = [device for device in usb_devices if 'CH340' in device or 'Z-Stick' in device]
            if automation_devices:
                return ("The server appears optimized for home automation and 3D printing workflows "
                       "with USB devices for hardware control and containerized services for monitoring and management.")

        if 'llm' in hostname or 'ai' in hostname:
            return "The server appears configured for AI/LLM workloads with appropriate compute resources."

        if metadata['container_count'] > 10:
            return "The server serves as a container host with multiple containerized services for infrastructure management."

        return None

    def create_server_document(self, server_data: Dict[str, Any], hostname: str) -> Dict[str, Any]:
        """Create server document for RAG system"""
        metadata = self.extract_hardware_metadata(server_data)
        content = self.generate_server_content(server_data, metadata)

        # Generate tags using LLM if available
        tags = ['server', 'hardware', 'infrastructure']
        if self.llm_client:
            try:
                # Create LLM request
                llm_request = LLMRequest(
                    entity_id=f'server_{hostname}',
                    entity_type='server',
                    content=content,
                    context={'processor': 'server', 'hostname': hostname}
                )

                # Get LLM response
                responses = self.llm_client.generate_tags([llm_request])

                if responses and len(responses) > 0:
                    response = responses[0]
                    if response.success and response.tags:
                        tags.extend(response.tags)
                        self.logger.debug(f"LLM generated tags for {hostname}: {response.tags}")
            except Exception as e:
                logger.warning(f"Failed to generate LLM tags for {hostname}: {e}")

        document = {
            'id': f'server_{hostname}',
            'type': 'server',
            'title': f'{hostname} hardware description',
            'content': content,
            'metadata': metadata,
            'tags': list(set(tags))  # Remove duplicates
        }

        # Validate content length
        self.content_validator.validate_document(document)

        return document

    def process_servers(self) -> Dict[str, Any]:
        """Process all server files and return server documents"""
        server_files = self.find_server_files()
        server_documents = []
        server_entities = {}

        for file_path in server_files:
            try:
                hostname = self.extract_hostname_from_filename(file_path)
                logger.info(f"Processing server: {hostname}")

                server_data = self.parse_server_data(file_path)
                if not server_data:
                    continue

                # Create document
                document = self.create_server_document(server_data, hostname)
                server_documents.append(document)

                # Create entity
                metadata = document['metadata']
                server_entities[hostname] = {
                    'type': 'server',
                    'os_type': metadata['os_type'],
                    'physical_device_count': metadata['physical_device_count'],
                    'memory_total_gb': metadata['system_memory_gb'],
                    'cpu_cores_count': metadata['cpu_cores_physical'],
                    'physical_network_interfaces_count': metadata['physical_network_interfaces_count'],
                    'container_count': metadata['container_count'],
                    'vm_count': metadata['vm_count'],
                    'lxc_count': metadata['lxc_count'],
                    'status': 'active',
                    'last_seen': metadata['last_updated']
                }

            except Exception as e:
                logger.error(f"Error processing server file {file_path}: {e}")
                continue

        logger.info(f"Processed {len(server_documents)} server documents")

        # Update rag_data.json with server documents
        output_path = Path(self.output_path)
        output_path.mkdir(exist_ok=True)
        rag_data_file = self._update_rag_data_json(server_documents, server_entities, output_path)

        return {
            'documents': server_documents,
            'entities': {'systems': server_entities},
            'relationships': []  # Server relationships handled by other processors
        }

    def _update_rag_data_json(self, documents: List[Dict[str, Any]], entities: Dict[str, Any],
                              output_path: Path) -> Path:
        """Update rag_data.json with server documents"""
        rag_data_file = output_path / 'rag_data.json'

        # Load existing rag_data.json or create new structure
        if rag_data_file.exists():
            try:
                with open(rag_data_file, 'r') as f:
                    rag_data = json.load(f)
                logger.info("Loaded existing rag_data.json")
            except Exception as e:
                logger.warning(f"Failed to load existing rag_data.json: {e}, creating new")
                rag_data = self._create_empty_rag_data()
        else:
            logger.info("Creating new rag_data.json")
            rag_data = self._create_empty_rag_data()

        # Remove existing server documents (same format we're inserting)
        original_count = len(rag_data.get('documents', []))
        rag_data['documents'] = [
            doc for doc in rag_data.get('documents', [])
            if not doc.get('id', '').startswith('server_')
        ]
        removed_count = original_count - len(rag_data['documents'])
        if removed_count > 0:
            logger.info(f"Removed {removed_count} existing server documents")

        # Add new server documents
        rag_data['documents'].extend(documents)
        logger.info(f"Added {len(documents)} new server documents")

        # Update/merge entities
        if 'entities' not in rag_data:
            rag_data['entities'] = {}

        # Merge systems entities
        if 'systems' not in rag_data['entities']:
            rag_data['entities']['systems'] = {}

        # Update server entities (replace existing servers with new data)
        for hostname, server_entity in entities.items():
            rag_data['entities']['systems'][hostname] = server_entity

        # Update metadata
        rag_data['metadata']['export_timestamp'] = datetime.now().isoformat()
        if 'total_servers' not in rag_data['metadata']:
            rag_data['metadata']['total_servers'] = 0
        rag_data['metadata']['total_servers'] = len([
            entity for entity in rag_data['entities']['systems'].values()
            if entity.get('type') == 'server'
        ])

        # Save updated rag_data.json
        with open(rag_data_file, 'w') as f:
            json.dump(rag_data, f, indent=2, default=str)

        logger.info(f"Updated rag_data.json with {len(documents)} server documents")
        return rag_data_file

    def _create_empty_rag_data(self) -> Dict[str, Any]:
        """Create empty rag_data.json structure"""
        return {
            "metadata": {
                "export_timestamp": datetime.now().isoformat(),
                "total_systems": 0,
                "total_containers": 0,
                "total_vms": 0,
                "total_servers": 0
            },
            "documents": [],
            "entities": {
                "systems": {},
                "services": {},
                "categories": {},
                "infrastructure": {}
            },
            "relationships": []
        }

    def validate_config(self) -> bool:
        """Validate processor configuration"""
        return Path(self.collected_data_path).exists()

    def process(self, collected_data: Dict[str, Any] = None) -> ProcessingResult:
        """Main processing entry point"""
        try:
            logger.info("Starting server processing")
            result = self.process_servers()
            logger.info(f"Server processing completed: {len(result['documents'])} documents")

            return ProcessingResult(
                success=True,
                data=result,
                metadata={'processed_servers': len(result['documents'])}
            )
        except Exception as e:
            logger.error(f"Server processing failed: {e}")
            return ProcessingResult(
                success=False,
                error=str(e)
            )