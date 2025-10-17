# src/processors/sub_processors/hardware_sub_processor.py
"""
Hardware Sub-Processor
Processes hardware and hardware_allocation sections from unified collector output.
Creates server/hardware RAG documents.
"""

from typing import Dict, Any, List
from datetime import datetime

from .base_sub_processor import SubProcessor


class HardwareSubProcessor(SubProcessor):
    """
    Processes hardware sections from unified collector output.

    Handles both:
    - hardware: Physical server hardware
    - hardware_allocation: VM/LXC resource allocation
    """

    def __init__(self, system_name: str, config: Dict[str, Any]):
        """
        Initialize hardware sub-processor

        Args:
            system_name: System name
            config: Processor configuration
        """
        super().__init__(system_name, config)
        self.enable_llm_tagging = config.get('enable_llm_tagging', True)

    def get_section_name(self) -> str:
        # Note: This processor handles both 'hardware' and 'hardware_allocation'
        return "hardware"

    def process(self, section_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Legacy process method - still used for compatibility
        Now delegated to process_with_all_sections

        Args:
            section_data: Hardware or hardware_allocation section only

        Returns:
            List with single hardware/server document
        """
        # Call the full method with just this section
        return self.process_with_all_sections({'hardware': section_data})

    def process_with_all_sections(self, all_sections: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Process hardware section data along with additional system sections

        Args:
            all_sections: Complete unified document sections including:
                - hardware/hardware_allocation: CPU, memory, storage, GPUs
                - system_overview: OS, kernel, uptime, hostname
                - network_details: Interfaces, routes, ports
                - resource_usage: Load, processes, disk I/O
                - docker: (optional) Container information
                - proxmox: (optional) Proxmox information

        Returns:
            List with single comprehensive hardware/server document
        """
        self.log_start()

        # Get hardware section (could be 'hardware' or 'hardware_allocation')
        hardware_section = all_sections.get('hardware') or all_sections.get('hardware_allocation')

        if not hardware_section or not self.validate_section_data(hardware_section):
            return []

        # Determine if this is physical hardware or allocation
        is_virtualized = 'allocated_vcpus' in hardware_section.get('cpu', {})

        # Create hardware document with all sections
        if is_virtualized:
            document = self._create_allocation_document(hardware_section)
        else:
            document = self._create_comprehensive_server_document(all_sections)

        self.log_end(1)

        return [document] if document else []

    def _create_hardware_document(self, hardware_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create document for physical hardware"""

        # Extract hardware components
        cpu = hardware_data.get('cpu', {})
        memory = hardware_data.get('memory', {})
        storage_devices = hardware_data.get('storage', {}).get('devices', [])
        network = hardware_data.get('network', {})
        gpus = hardware_data.get('gpus', [])

        # Build content
        content_parts = [
            f"{self.system_name} is a physical server"
        ]

        # CPU description
        cpu_model = cpu.get('model_name', 'Unknown CPU')
        cpu_cores = cpu.get('cores', cpu.get('physical_cores', 0))
        cpu_threads = cpu.get('threads', cpu.get('logical_cores', 0))
        content_parts.append(
            f"with {cpu_model} ({cpu_cores} cores, {cpu_threads} threads)"
        )

        # Memory description
        memory_gb = memory.get('total_gb', 0)
        content_parts.append(f"and {memory_gb}GB RAM.")

        # Storage description
        if storage_devices:
            total_storage_gb = sum(device.get('size_gb', 0) for device in storage_devices)
            content_parts.append(
                f"Storage: {len(storage_devices)} devices totaling {total_storage_gb}GB."
            )

        # GPU description
        if gpus:
            gpu_descriptions = []
            for gpu in gpus:
                vendor = gpu.get('vendor', 'Unknown')
                model = gpu.get('model', 'GPU')
                gpu_descriptions.append(f"{vendor} {model}")
            content_parts.append(f"GPUs: {', '.join(gpu_descriptions)}.")

        # Network description
        if network:
            interfaces = network.get('interfaces', [])
            if interfaces:
                content_parts.append(f"Network: {len(interfaces)} interfaces.")

        content = " ".join(content_parts)

        # Extract metadata
        metadata = {
            'system_name': self.system_name,
            'system_type': 'physical_server',
            'cpu_model': cpu_model,
            'cpu_cores': cpu_cores,
            'cpu_threads': cpu_threads,
            'memory_gb': memory_gb,
            'storage_devices_count': len(storage_devices),
            'storage_total_gb': sum(device.get('size_gb', 0) for device in storage_devices),
            'gpu_count': len(gpus),
            'network_interfaces_count': len(network.get('interfaces', [])),
            'last_updated': datetime.now().isoformat()
        }

        # Generate tags
        tags = ['server', 'hardware', 'physical', 'infrastructure']
        if gpus:
            tags.append('gpu')
        if len(storage_devices) > 4:
            tags.append('storage-server')

        document = {
            'id': f'server_{self.system_name}',
            'type': 'server',
            'title': f'{self.system_name} hardware configuration',
            'content': content,
            'metadata': metadata,
            'tags': tags
        }

        return document

    def _create_comprehensive_server_document(self, all_sections: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create comprehensive server document using all available sections

        Args:
            all_sections: All collected sections including hardware, system_overview,
                         network_details, resource_usage, docker, etc.

        Returns:
            Comprehensive server document matching backup format
        """
        # Extract all sections
        hardware_data = all_sections.get('hardware', {})
        system_overview = all_sections.get('system_overview', {})
        network_details = all_sections.get('network_details', {})
        resource_usage = all_sections.get('resource_usage', {})
        docker_data = all_sections.get('docker', {})

        # Extract hardware components
        cpu = hardware_data.get('cpu', {})
        memory = hardware_data.get('memory', {})
        storage_devices = hardware_data.get('storage_devices', [])
        motherboard = hardware_data.get('motherboard', {})
        gpus = hardware_data.get('gpus', [])
        pci_devices = hardware_data.get('pci_devices', [])
        usb_devices = hardware_data.get('usb_devices', [])
        temperatures = hardware_data.get('temperatures', {})

        # Build comprehensive content
        content = self._build_comprehensive_content(
            cpu, memory, storage_devices, gpus, system_overview,
            network_details, docker_data, resource_usage
        )

        # Build hardware_details section
        hardware_details = {
            'cpu': {
                'model': cpu.get('model_name', 'Unknown'),
                'cores': cpu.get('cores', cpu.get('physical_cores', 0)),
                'threads': cpu.get('threads', cpu.get('logical_cores', 0)),
                'frequency': cpu.get('frequency', 'Unknown'),
                'architecture': cpu.get('architecture', system_overview.get('architecture', 'Unknown'))
            },
            'memory': {
                'total_gb': memory.get('total_gb', 0),
                'available_gb': memory.get('available_gb', 0),
                'modules': memory.get('modules', [])
            },
            'motherboard': {
                'manufacturer': motherboard.get('manufacturer', 'Unknown'),
                'product': motherboard.get('product', 'Unknown'),
                'version': motherboard.get('version', 'Unknown')
            }
        }

        # Add GPUs if present
        if gpus:
            hardware_details['gpus'] = gpus

        # Add PCI devices if present
        if pci_devices:
            hardware_details['pci_devices'] = pci_devices[:20]  # Limit to first 20

        # Add USB devices if present
        if usb_devices:
            hardware_details['usb_devices'] = usb_devices[:20]  # Limit to first 20

        # Add temperatures if present
        if temperatures:
            hardware_details['temperatures'] = temperatures

        # Build network_details section (from collected network data)
        network_section = {}
        if network_details:
            network_section = {
                'interfaces': network_details.get('interfaces', ''),
                'routes': network_details.get('routes', ''),
                'listening_ports': network_details.get('listening_ports', [])
            }
            if network_details.get('dns_config'):
                network_section['dns_config'] = network_details['dns_config']

        # Build system_info section
        system_info = {
            'system_overview': {
                'hostname': system_overview.get('hostname', self.system_name),
                'kernel': system_overview.get('kernel', 'Unknown'),
                'architecture': system_overview.get('architecture', 'Unknown'),
                'uptime': system_overview.get('uptime', 'Unknown')
            }
        }

        # Add OS release info
        if system_overview.get('os_release'):
            system_info['system_overview']['os_release'] = system_overview['os_release']

        # Add resource usage
        if resource_usage:
            system_info['resource_usage'] = {
                'load_average': resource_usage.get('load_average', 'Unknown'),
                'top_processes_cpu': resource_usage.get('top_processes_cpu', [])[:10],
                'top_processes_memory': resource_usage.get('top_processes_memory', [])[:10],
                'process_count': resource_usage.get('process_count', 0)
            }
            if resource_usage.get('disk_io'):
                system_info['resource_usage']['disk_io'] = resource_usage['disk_io']

        # Add Docker configuration if present
        docker_configuration = {}
        if docker_data:
            docker_configuration = {
                'version': docker_data.get('version', 'Unknown'),
                'running_containers': len(docker_data.get('containers', [])),
                'total_networks': len(docker_data.get('networks', [])),
                'total_volumes': len(docker_data.get('volumes', []))
            }

        # Build comprehensive metadata
        metadata = {
            'system_name': self.system_name,
            'system_type': 'physical_server',
            'cpu_model': cpu.get('model_name', 'Unknown'),
            'cpu_cores': cpu.get('cores', cpu.get('physical_cores', 0)),
            'cpu_threads': cpu.get('threads', cpu.get('logical_cores', 0)),
            'memory_gb': memory.get('total_gb', 0),
            'storage_devices_count': len(storage_devices),
            'storage_total_tb': round(sum(self._parse_size_to_bytes(d.get('size', '0B')) for d in storage_devices) / (1024 ** 4), 2),
            'gpu_count': len(gpus),
            'os_type': system_overview.get('os_release', {}).get('ID', 'linux'),
            'kernel_version': system_overview.get('kernel', 'Unknown'),
            'container_count': len(docker_data.get('containers', [])),
            'last_updated': datetime.now().isoformat()
        }

        # Add GPU info if present
        if gpus:
            metadata['gpu_info'] = [{'vendor': g.get('vendor'), 'model': g.get('model')} for g in gpus]

        # Generate tags
        tags = ['server', 'hardware', 'physical', 'infrastructure']
        if gpus:
            tags.append('gpu')
        if len(storage_devices) > 4:
            tags.append('storage-server')
        if docker_data:
            tags.append('docker')

        # Build final document
        document = {
            'id': f'server_{self.system_name}',
            'type': 'server',
            'title': f'{self.system_name} Server Configuration',
            'content': content,
            'metadata': metadata,
            'hardware_details': hardware_details,
            'tags': tags
        }

        # Add optional sections if they have data
        if network_section:
            document['network_details'] = network_section

        if system_info:
            document['system_info'] = system_info

        if docker_configuration and docker_configuration.get('running_containers', 0) > 0:
            document['docker_configuration'] = docker_configuration

        return document

    def _build_comprehensive_content(
        self,
        cpu: Dict,
        memory: Dict,
        storage_devices: List,
        gpus: List,
        system_overview: Dict,
        network_details: Dict,
        docker_data: Dict,
        resource_usage: Dict
    ) -> str:
        """Build comprehensive human-readable content description"""

        content_parts = []

        # System overview
        hostname = system_overview.get('hostname', self.system_name)
        os_name = system_overview.get('os_release', {}).get('PRETTY_NAME', 'Linux')
        kernel = system_overview.get('kernel', 'unknown kernel')

        content_parts.append(
            f"{hostname} is a physical server running {os_name} with kernel {kernel}."
        )

        # Hardware description
        cpu_model = cpu.get('model_name', 'Unknown CPU')
        cpu_cores = cpu.get('cores', cpu.get('physical_cores', 0))
        cpu_threads = cpu.get('threads', cpu.get('logical_cores', 0))
        memory_gb = memory.get('total_gb', 0)

        content_parts.append(
            f"The server is equipped with a {cpu_model} processor ({cpu_cores} cores, {cpu_threads} threads) and {memory_gb}GB of RAM."
        )

        # Storage description
        if storage_devices:
            total_storage_tb = round(sum(self._parse_size_to_bytes(d.get('size', '0B')) for d in storage_devices) / (1024 ** 4), 2)
            ssd_count = sum(1 for d in storage_devices if not d.get('rota', True))
            hdd_count = len(storage_devices) - ssd_count

            storage_desc = f"{len(storage_devices)} storage devices totaling {total_storage_tb}TB"
            if ssd_count > 0 and hdd_count > 0:
                storage_desc += f" ({ssd_count} SSDs, {hdd_count} HDDs)"
            elif ssd_count > 0:
                storage_desc += f" (all SSDs)"
            elif hdd_count > 0:
                storage_desc += f" (all HDDs)"

            content_parts.append(f"Storage consists of {storage_desc}.")

        # GPU description
        if gpus:
            gpu_descriptions = []
            for gpu in gpus:
                vendor = gpu.get('vendor', 'Unknown')
                model = gpu.get('model', 'GPU')
                gpu_descriptions.append(f"{vendor} {model}")

            content_parts.append(f"Graphics capabilities are provided by {', '.join(gpu_descriptions)}.")

        # Network description
        if network_details and network_details.get('interfaces'):
            interfaces_text = network_details['interfaces']
            # Count network interfaces from the text (simple heuristic)
            interface_count = interfaces_text.count('\n') // 3  # Rough estimate
            content_parts.append(f"The system has {interface_count} network interfaces configured.")

        # Docker description
        if docker_data:
            container_count = len(docker_data.get('containers', []))
            if container_count > 0:
                content_parts.append(f"Docker is running with {container_count} containers deployed.")

        # Resource usage
        if resource_usage:
            load_avg = resource_usage.get('load_average', '')
            if load_avg:
                content_parts.append(f"Current system load: {load_avg}.")

        return " ".join(content_parts)

    def _parse_size_to_bytes(self, size_str: str) -> int:
        """Parse size string like '931.5G' or '1.8T' to bytes"""
        try:
            size_str = size_str.strip().upper()

            # Extract numeric part and unit
            import re
            match = re.match(r'([\d.]+)([KMGTPE]?)B?', size_str)
            if not match:
                return 0

            number = float(match.group(1))
            unit = match.group(2) if match.group(2) else 'B'

            # Convert to bytes
            units = {'B': 1, 'K': 1024, 'M': 1024**2, 'G': 1024**3, 'T': 1024**4, 'P': 1024**5, 'E': 1024**6}
            return int(number * units.get(unit, 1))
        except:
            return 0

    def _create_allocation_document(self, allocation_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create document for virtualized hardware allocation"""

        # Extract allocation components
        cpu = allocation_data.get('cpu', {})
        memory = allocation_data.get('memory', {})
        storage = allocation_data.get('storage', [])
        network = allocation_data.get('network', [])
        virtualization = allocation_data.get('virtualization', {})

        # Build content
        content_parts = [
            f"{self.system_name} is a virtualized system"
        ]

        # Virtualization type
        virt_type = virtualization.get('type', 'unknown')
        if virt_type != 'unknown':
            content_parts.append(f"running as {virt_type}")

        # CPU allocation
        allocated_vcpus = cpu.get('allocated_vcpus', 0)
        cpu_model = cpu.get('model_name', 'Unknown CPU')
        content_parts.append(
            f"with {allocated_vcpus} vCPUs ({cpu_model})"
        )

        # Memory allocation
        memory_gb = memory.get('allocated_gb', 0)
        content_parts.append(f"and {memory_gb}GB allocated RAM.")

        # Storage allocation
        if storage:
            total_storage_gb = sum(mount.get('size_gb', 0) for mount in storage if isinstance(mount, dict))
            content_parts.append(
                f"Storage: {len(storage)} mounted filesystems."
            )

        # Network allocation
        if network:
            content_parts.append(f"Network: {len(network)} virtual interfaces.")

        content = " ".join(content_parts)

        # Extract metadata
        metadata = {
            'system_name': self.system_name,
            'system_type': 'virtual_machine' if virt_type == 'vm' else 'container',
            'virtualization_type': virt_type,
            'cpu_allocated_vcpus': allocated_vcpus,
            'cpu_model': cpu_model,
            'memory_allocated_gb': memory_gb,
            'storage_mounts_count': len(storage),
            'network_interfaces_count': len(network),
            'last_updated': datetime.now().isoformat()
        }

        # Generate tags
        tags = ['virtualized', 'infrastructure']
        if virt_type == 'lxc':
            tags.extend(['container', 'lxc'])
        elif virt_type == 'vm':
            tags.extend(['virtual-machine', 'vm'])

        document = {
            'id': f'system_{self.system_name}',
            'type': 'virtual_system',
            'title': f'{self.system_name} resource allocation',
            'content': content,
            'metadata': metadata,
            'tags': tags
        }

        return document
