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

    def process(self, section_data: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Legacy process method - still used for compatibility
        Now delegated to process_with_all_sections

        Args:
            section_data: Hardware or hardware_allocation section only

        Returns:
            Tuple of (documents, relationships)
        """
        # Call the full method with just this section
        return self.process_with_all_sections({'hardware': section_data})

    def process_with_all_sections(self, all_sections: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
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
            Tuple of (documents, relationships)
        """
        self.log_start()

        # Get hardware section (could be 'hardware' or 'hardware_allocation')
        hardware_section = all_sections.get('hardware') or all_sections.get('hardware_allocation')

        if not hardware_section or not self.validate_section_data(hardware_section):
            return [], []

        # Determine if this is physical hardware or allocation
        is_virtualized = 'allocated_vcpus' in hardware_section.get('cpu', {})

        # Create hardware document with all sections
        if is_virtualized:
            document = self._create_allocation_document(hardware_section)
            relationships = []  # Virtualized systems handled by other processors
        else:
            document = self._create_physical_server_document(all_sections)
            relationships = []  # Physical servers have no parent relationships

        self.log_end(1)

        if document:
            return [document], relationships
        else:
            return [], []

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

        document = {
            'id': f'server_{self.system_name}',
            'type': 'server',
            'title': f'{self.system_name} hardware configuration',
            'content': content,
            'metadata': metadata
        }

        return document

    def _create_physical_server_document(self, all_sections: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create physical server document matching new schema

        Args:
            all_sections: All collected sections including hardware, system_overview,
                         network_details, resource_usage, docker, etc.

        Returns:
            Physical server document matching new schema
        """
        # Extract all sections
        hardware_data = all_sections.get('hardware', {})
        system_overview = all_sections.get('system_overview', {})
        network_details = all_sections.get('network_details', {})
        docker_data = all_sections.get('docker', {})
        proxmox_data = all_sections.get('proxmox', {})

        # Extract hardware components
        cpu = hardware_data.get('cpu', {})
        memory = hardware_data.get('memory', {})
        storage_devices = hardware_data.get('storage_devices', [])
        motherboard = hardware_data.get('motherboard', {})
        gpus = hardware_data.get('gpus', [])
        pci_devices = hardware_data.get('pci_devices', [])
        usb_devices = hardware_data.get('usb_devices', [])
        temperatures = hardware_data.get('temperatures', {})

        # Get hostname
        hostname = system_overview.get('hostname', self.system_name)

        # Extract IP addresses from network interfaces
        primary_ip = None
        network_interfaces_list = []
        if network_details and network_details.get('interfaces'):
            ip_list = self._extract_ip_addresses(network_details['interfaces'])
            if ip_list:
                primary_ip = ip_list[0]['ip_address'].split('/')[0]  # First IP, without CIDR
            network_interfaces_list = self._build_network_interfaces_list(network_details['interfaces'])

        # Build TIER 1: Vector Search Content
        content = self._build_physical_server_content(
            hostname, system_overview, cpu, memory, storage_devices,
            gpus, primary_ip, docker_data, proxmox_data
        )

        # Calculate storage summary
        storage_total_tb = round(sum(self._parse_size_to_bytes(d.get('size', '0B')) for d in storage_devices) / (1024 ** 4), 2)
        storage_types = {'nvme': 0, 'ssd': 0, 'hdd': 0}
        for device in storage_devices:
            device_type = device.get('type', 'HDD').upper()
            if 'NVME' in device_type or device.get('tran') == 'nvme':
                storage_types['nvme'] += 1
            elif not device.get('rota', True) or 'SSD' in device_type:
                storage_types['ssd'] += 1
            else:
                storage_types['hdd'] += 1

        # Extract memory info
        memory_type = self._extract_memory_type(memory.get('modules'))
        memory_speed_mhz = self._extract_memory_speed(memory.get('modules'))

        # Calculate workload counts
        container_count = len(docker_data.get('containers', [])) if docker_data else None
        vm_count = len(proxmox_data.get('vms', [])) + len(proxmox_data.get('lxc_containers', [])) if proxmox_data else None

        # Determine OS distribution
        os_release = system_overview.get('os_release', {})
        os_distribution = os_release.get('PRETTY_NAME', os_release.get('NAME', 'Linux'))
        os_version = os_release.get('VERSION', os_release.get('VERSION_ID', 'Unknown'))

        # Build TIER 2: Summary Metadata
        metadata = {
            'hostname': hostname,
            'system_type': 'physical_server',
            'primary_ip': primary_ip,
            'os_distribution': os_distribution,
            'os_version': os_version,
            'kernel_version': system_overview.get('kernel', 'Unknown'),
            'architecture': system_overview.get('architecture', 'x86_64'),
            'cpu_model': cpu.get('model_name', 'Unknown'),
            'cpu_cores': cpu.get('cores', cpu.get('physical_cores', 0)),
            'cpu_threads': cpu.get('threads', cpu.get('logical_cores', 0)),
            'memory_total_gb': round(memory.get('total_gb', 0), 2),
            'memory_type': memory_type,
            'memory_speed_mhz': memory_speed_mhz,
            'storage_total_tb': storage_total_tb,
            'storage_devices_count': len(storage_devices),
            'storage_types': storage_types,
            'gpu_count': len(gpus),
            'gpu_vendor': gpus[0].get('vendor') if gpus else None,
            'container_count': container_count,
            'vm_count': vm_count,
            'last_updated': datetime.now().isoformat()
        }

        # Build TIER 3: Detailed Information
        details = {
            'cpu': self._build_cpu_details(cpu, system_overview),
            'memory': self._build_memory_details(memory),
            'motherboard': self._build_motherboard_details(motherboard),
            'gpus': self._build_gpu_details(gpus),
            'storage_devices': self._build_storage_details(storage_devices),
            'network_interfaces': network_interfaces_list
        }

        # Add optional details sections
        if pci_devices:
            details['pci_devices'] = pci_devices
        if usb_devices:
            details['usb_devices'] = usb_devices
        if temperatures:
            details['temperatures'] = self._build_temperature_details(temperatures)

        # Build final document (NEW SCHEMA)
        document = {
            'id': f'server_{hostname}',
            'type': 'physical_server',
            'title': f'{hostname} Physical Server',
            'content': content,
            'metadata': metadata,
            'details': details
        }

        return document

    def _build_comprehensive_content(
        self,
        cpu: Dict,
        memory: Dict,
        storage_devices: List,
        gpus: List,
        system_overview: Dict,
        network_details: Dict,
        docker_data: Dict
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

    def _extract_ip_addresses(self, network_interfaces_text: str) -> List[Dict[str, str]]:
        """
        Extract IP addresses from network interface text output from 'ip addr show'

        Args:
            network_interfaces_text: Raw output from 'ip addr show' command

        Returns:
            List of dictionaries with interface, ip_address, and type (ipv4/ipv6)
        """
        import re

        ip_addresses = []

        if not network_interfaces_text:
            return ip_addresses

        # Split by interface (lines starting with digit followed by colon)
        current_interface = None

        for line in network_interfaces_text.split('\n'):
            # Match interface line: "2: eno1: <BROADCAST,MULTICAST,UP,LOWER_UP> ..."
            interface_match = re.match(r'^\d+:\s+([^:@]+)', line)
            if interface_match:
                current_interface = interface_match.group(1).strip()
                continue

            if not current_interface:
                continue

            # Skip loopback and docker bridge interfaces
            if current_interface in ['lo', 'docker0'] or current_interface.startswith('br-') or current_interface.startswith('veth'):
                # Match IPv4 address: "    inet 10.30.0.142/24 ..."
                ipv4_match = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)', line)
                if ipv4_match and current_interface == 'lo':
                    # Skip loopback 127.0.0.1
                    continue
                # Skip docker/veth addresses but continue parsing
                continue

            # Match IPv4 address: "    inet 10.30.0.142/24 ..."
            ipv4_match = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)', line)
            if ipv4_match:
                ip_addr = ipv4_match.group(1)
                netmask = ipv4_match.group(2)

                # Skip localhost
                if ip_addr.startswith('127.'):
                    continue

                # Determine scope (global vs link-local)
                if 'scope global' in line:
                    ip_addresses.append({
                        'interface': current_interface,
                        'ip_address': f"{ip_addr}/{netmask}",
                        'type': 'ipv4',
                        'scope': 'global'
                    })

            # Match IPv6 address: "    inet6 fe80::ce28:aaff:fe4f:fdc1/64 scope link"
            ipv6_match = re.search(r'inet6\s+([0-9a-fA-F:]+)/(\d+)', line)
            if ipv6_match:
                ip_addr = ipv6_match.group(1)
                netmask = ipv6_match.group(2)

                # Skip link-local IPv6 (fe80::) and localhost (::1)
                if ip_addr.startswith('fe80:') or ip_addr == '::1':
                    continue

                if 'scope global' in line:
                    ip_addresses.append({
                        'interface': current_interface,
                        'ip_address': f"{ip_addr}/{netmask}",
                        'type': 'ipv6',
                        'scope': 'global'
                    })

        return ip_addresses

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
        # Determine if this is a container or VM based on virtualization type
        # LXC = container, everything else (kvm, qemu, vm, etc.) = virtual_machine
        is_container = virt_type == 'lxc'

        metadata = {
            'system_name': self.system_name,
            'system_type': 'linux-container' if is_container else 'virtual_machine',
            'virtualization_type': virt_type,
            'cpu_allocated_vcpus': allocated_vcpus,
            'cpu_model': cpu_model,
            'memory_allocated_gb': memory_gb,
            'storage_mounts_count': len(storage),
            'network_interfaces_count': len(network),
            'last_updated': datetime.now().isoformat()
        }

        document = {
            'id': f'system_{self.system_name}',
            'type': 'virtual_server',
            'title': f'{self.system_name} resource allocation',
            'content': content,
            'metadata': metadata
        }

        return document

    def _build_physical_server_content(
        self,
        hostname: str,
        system_overview: Dict,
        cpu: Dict,
        memory: Dict,
        storage_devices: List,
        gpus: List,
        primary_ip: str,
        docker_data: Dict,
        proxmox_data: Dict
    ) -> str:
        """Build rich content description for vector matching"""
        content_parts = []

        # Basic description
        os_name = system_overview.get('os_release', {}).get('PRETTY_NAME', 'Linux')
        cpu_model = cpu.get('model_name', 'Unknown CPU')
        cpu_cores = cpu.get('cores', cpu.get('physical_cores', 0))
        memory_gb = round(memory.get('total_gb', 0), 1)

        # Calculate storage
        storage_count = len(storage_devices)
        storage_tb = round(sum(self._parse_size_to_bytes(d.get('size', '0B')) for d in storage_devices) / (1024 ** 4), 2)

        content_parts.append(
            f"{hostname} is a physical server running {os_name} with {cpu_cores}-core {cpu_model}, {memory_gb}GB RAM, "
            f"{storage_count} storage devices totaling {storage_tb}TB."
        )

        # Network info
        if primary_ip:
            content_parts.append(f"Primary IP: {primary_ip}.")

        # GPU info
        if gpus:
            gpu_desc = []
            for gpu in gpus:
                vendor = gpu.get('vendor', 'Unknown')
                model = gpu.get('model', 'GPU')
                gpu_desc.append(f"{vendor} {model}")
            content_parts.append(f"Equipped with {', '.join(gpu_desc)}.")

        # Workload info
        if docker_data:
            container_count = len(docker_data.get('containers', []))
            if container_count > 0:
                content_parts.append(f"Hosts {container_count} Docker containers.")

        if proxmox_data:
            vm_count = len(proxmox_data.get('vms', []))
            lxc_count = len(proxmox_data.get('lxc_containers', []))
            if vm_count > 0 or lxc_count > 0:
                content_parts.append(f"Runs Proxmox with {vm_count} VMs and {lxc_count} LXC containers.")

        return " ".join(content_parts)

    def _build_network_interfaces_list(self, network_text: str) -> List[Dict]:
        """Build structured network interfaces list from ip addr output"""
        import re
        interfaces = []
        current_interface = None
        current_data = {}

        for line in network_text.split('\n'):
            # Match interface line
            interface_match = re.match(r'^\d+:\s+([^:@]+).*state\s+(\w+)', line)
            if interface_match:
                # Save previous interface
                if current_interface and current_data.get('ip_addresses'):
                    interfaces.append(current_data)

                # Start new interface
                current_interface = interface_match.group(1).strip()
                state = interface_match.group(2)

                # Skip loopback, docker, veth interfaces
                if current_interface in ['lo'] or current_interface.startswith(('docker', 'br-', 'veth', 'fwbr', 'fwpr', 'fwln')):
                    current_interface = None
                    current_data = {}
                    continue

                current_data = {
                    'interface': current_interface,
                    'state': state,
                    'ip_addresses': [],
                    'mac_address': None,
                    'speed_mbps': None,
                    'driver': None
                }
                continue

            if not current_interface:
                continue

            # Match MAC address
            mac_match = re.search(r'link/ether\s+([0-9a-fA-F:]+)', line)
            if mac_match:
                current_data['mac_address'] = mac_match.group(1)

            # Match IPv4
            ipv4_match = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+/\d+)', line)
            if ipv4_match and 'scope global' in line:
                current_data['ip_addresses'].append({
                    'ip_address': ipv4_match.group(1),
                    'type': 'ipv4',
                    'scope': 'global'
                })

            # Match IPv6
            ipv6_match = re.search(r'inet6\s+([0-9a-fA-F:]+/\d+)', line)
            if ipv6_match and 'scope global' in line:
                ip_addr = ipv6_match.group(1).split('/')[0]
                if not ip_addr.startswith('fe80:'):
                    current_data['ip_addresses'].append({
                        'ip_address': ipv6_match.group(1),
                        'type': 'ipv6',
                        'scope': 'global'
                    })

        # Save last interface
        if current_interface and current_data.get('ip_addresses'):
            interfaces.append(current_data)

        return interfaces

    def _extract_memory_type(self, modules_data) -> str:
        """Extract memory type from modules data"""
        if isinstance(modules_data, str):
            # Parse from dmidecode output
            if 'DDR5' in modules_data:
                return 'DDR5'
            elif 'DDR4' in modules_data:
                return 'DDR4'
            elif 'DDR3' in modules_data:
                return 'DDR3'
        elif isinstance(modules_data, list):
            for module in modules_data:
                if isinstance(module, dict) and module.get('type'):
                    return module['type']
        return None

    def _extract_memory_speed(self, modules_data) -> int:
        """Extract memory speed from modules data"""
        import re
        if isinstance(modules_data, str):
            # Parse from dmidecode output
            match = re.search(r'Speed:\s*(\d+)\s*MT/s', modules_data)
            if match:
                return int(match.group(1))
        elif isinstance(modules_data, list):
            for module in modules_data:
                if isinstance(module, dict) and module.get('speed_mhz'):
                    return module['speed_mhz']
        return None

    def _build_cpu_details(self, cpu: Dict, system_overview: Dict) -> Dict:
        """Build CPU details section"""
        return {
            'model': cpu.get('model_name', 'Unknown'),
            'cores': cpu.get('cores', cpu.get('physical_cores', 0)),
            'threads': cpu.get('threads', cpu.get('logical_cores', 0)),
            'frequency_mhz': int(cpu.get('frequency_mhz', 0)) if cpu.get('frequency_mhz') else None,
            'architecture': cpu.get('architecture') or system_overview.get('architecture', 'x86_64'),
            'cache_l1_kb': cpu.get('cache_l1_kb'),
            'cache_l2_kb': cpu.get('cache_l2_kb'),
            'cache_l3_kb': cpu.get('cache_l3_kb')
        }

    def _build_memory_details(self, memory: Dict) -> Dict:
        """Build memory details section"""
        modules_data = memory.get('modules', [])

        # If modules is a string (dmidecode output), keep it as is
        if isinstance(modules_data, str):
            return {
                'total_gb': round(memory.get('total_gb', 0), 2),
                'available_gb': round(memory.get('available_gb', 0), 2) if memory.get('available_gb') else None,
                'type': self._extract_memory_type(modules_data),
                'speed_mhz': self._extract_memory_speed(modules_data),
                'modules': modules_data
            }

        # If modules is a list, build structured list
        modules_list = []
        for module in modules_data:
            if isinstance(module, dict):
                modules_list.append({
                    'size_gb': module.get('size_gb'),
                    'type': module.get('type'),
                    'speed_mhz': module.get('speed_mhz'),
                    'manufacturer': module.get('manufacturer'),
                    'slot': module.get('slot')
                })

        return {
            'total_gb': round(memory.get('total_gb', 0), 2),
            'available_gb': round(memory.get('available_gb', 0), 2) if memory.get('available_gb') else None,
            'type': self._extract_memory_type(modules_data),
            'speed_mhz': self._extract_memory_speed(modules_data),
            'modules': modules_list if modules_list else modules_data
        }

    def _build_motherboard_details(self, motherboard: Dict) -> Dict:
        """Build motherboard details section"""
        return {
            'manufacturer': motherboard.get('manufacturer'),
            'product': motherboard.get('product'),
            'version': motherboard.get('version'),
            'bios_version': motherboard.get('bios_version'),
            'bios_date': motherboard.get('bios_date')
        }

    def _build_gpu_details(self, gpus: List) -> List[Dict]:
        """Build GPU details list"""
        gpu_list = []
        for gpu in gpus:
            gpu_info = {
                'vendor': gpu.get('vendor', 'Unknown'),
                'model': gpu.get('model', 'Unknown'),
                'driver_version': gpu.get('driver_version'),
                'memory_total_mb': gpu.get('memory_total_mb'),
                'is_discrete': gpu.get('is_discrete', True),
                'pci_address': gpu.get('pci_address'),
                'pcie_generation': gpu.get('pcie_generation'),
                'pcie_width': gpu.get('pcie_width')
            }
            gpu_list.append(gpu_info)
        return gpu_list

    def _build_storage_details(self, storage_devices: List) -> List[Dict]:
        """Build storage devices list"""
        storage_list = []
        for device in storage_devices:
            # Determine device type
            device_type = 'HDD'
            if 'nvme' in device.get('name', '').lower() or device.get('tran') == 'nvme':
                device_type = 'NVMe'
            elif not device.get('rota', True):
                device_type = 'SSD'

            # Calculate size in TB
            size_bytes = self._parse_size_to_bytes(device.get('size', '0B'))
            size_tb = round(size_bytes / (1024 ** 4), 3)

            # Determine connection type
            connection_type = device.get('tran', 'SATA').upper()
            if 'nvme' in device.get('name', '').lower():
                connection_type = 'NVMe'

            storage_info = {
                'device_name': device.get('name', 'unknown'),
                'type': device_type,
                'size_tb': size_tb,
                'model': device.get('model'),
                'serial_number': device.get('serial'),
                'mount_point': device.get('mount_point'),
                'connection_type': connection_type,
                'smart_status': device.get('smart_status'),
                'firmware_version': device.get('firmware_version')
            }
            storage_list.append(storage_info)
        return storage_list

    def _build_temperature_details(self, temperatures: Dict) -> Dict:
        """Build temperature details section"""
        return {
            'sensors_output': temperatures.get('sensors_output') if isinstance(temperatures, dict) else str(temperatures),
            'parsed_temperatures': temperatures.get('parsed_temperatures') if isinstance(temperatures, dict) else None
        }
