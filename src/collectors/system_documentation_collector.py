# src/collectors/system_documentation_collector.py
"""
System Documentation Collector
Generates comprehensive system documentation for both Unraid and Proxmox hosts.
Enhanced with better error handling and system-specific command handling.
"""

import json
import re
from typing import Dict, List, Any
from datetime import datetime
from .base_collector import SystemStateCollector, CollectionResult

try:
    from ..connectors.ssh_connector import SSHConnector
except ImportError:
    from src.connectors.ssh_connector import SSHConnector


class SystemDocumentationCollector(SystemStateCollector):
    """
    Collects comprehensive system documentation including:
    - Hardware information (CPU, memory, motherboard, GPUs)
    - System configuration
    - Service status
    - Resource usage
    - Network configuration
    - Storage details
    Enhanced with better error handling and system-specific commands.
    Supports detection of NVIDIA, AMD, and Intel discrete GPUs.
    """

    def __init__(self, name: str, config: Dict):
        super().__init__(name, config)

        self.system_type = config.get('system_type', 'auto')  # 'unraid', 'proxmox', 'ubuntu', 'auto'
        self.ssh_connector = SSHConnector(
            host=self.host,
            port=self.port,
            username=self.username,
            ssh_key_path=config.get('ssh_key_path'),
            timeout=config.get('timeout', 60)  # Increased default timeout
        )

    def validate_config(self) -> bool:
        """Validate system documentation collector configuration"""
        if not self.host:
            self.logger.error("Host required for system documentation collection")
            return False
        return True

    def get_system_state(self) -> Dict[str, Any]:
        """Get comprehensive system documentation"""
        try:
            if not self.ssh_connector.connect():
                raise Exception("Failed to establish SSH connection")

            # Detect system type if auto
            if self.system_type == 'auto':
                detected_type = self._detect_system_type()
                self.logger.info(f"Detected system type: {detected_type}")
            else:
                detected_type = self.system_type

            # Collect system documentation
            self.logger.info(f"Starting system documentation collection for {detected_type} system")

            documentation = {
                'system_type': detected_type,
                'timestamp': datetime.now().isoformat(),
                'hostname': self._get_hostname(),
                'system_overview': self._get_system_overview(detected_type),
                'hardware_profile': self._get_hardware_profile(),
                'storage_configuration': self._get_storage_configuration(detected_type),
                'network_configuration': self._get_network_configuration(),
                'service_status': self._get_service_status(detected_type),
                'docker_configuration': self._get_docker_configuration(),
                'resource_usage': self._get_resource_usage(),
                'system_information': self._get_system_information(),
                'security_status': self._get_security_status(),
                'collection_method': 'ssh'
            }

            self.ssh_connector.disconnect()
            self.logger.info("System documentation collection completed successfully")
            return documentation

        except Exception as e:
            self.logger.error(f"Failed to collect system documentation: {e}")
            if self.ssh_connector:
                self.ssh_connector.disconnect()
            raise

    def _detect_system_type(self) -> str:
        """Detect the type of system we're documenting"""
        self.logger.debug("Auto-detecting system type...")

        # Check for Unraid
        result = self.ssh_connector.execute_command("cat /etc/unraid-version 2>/dev/null", log_command=False)
        if result.success and result.output.strip():
            self.logger.debug("Detected Unraid system")
            return 'unraid'

        # Check for Proxmox
        result = self.ssh_connector.execute_command("pveversion 2>/dev/null", log_command=False)
        if result.success and 'pve-manager' in result.output:
            self.logger.debug("Detected Proxmox system")
            return 'proxmox'

        # Check for Ubuntu/Debian
        result = self.ssh_connector.execute_command("lsb_release -i 2>/dev/null", log_command=False)
        if result.success:
            if 'Ubuntu' in result.output:
                self.logger.debug("Detected Ubuntu system")
                return 'ubuntu'
            elif 'Debian' in result.output:
                self.logger.debug("Detected Debian system")
                return 'debian'

        # Fallback to generic Linux
        self.logger.debug("Using generic Linux detection")
        return 'linux'

    def _get_hostname(self) -> str:
        """Get system hostname"""
        result = self.ssh_connector.execute_command("hostname", log_command=False)
        if result.success:
            return result.output.strip()
        return 'unknown'

    def _get_system_overview(self, system_type: str) -> Dict[str, Any]:
        """Get system overview information"""
        self.logger.debug("Collecting system overview...")
        overview = {}

        # Basic system info
        commands = {
            'hostname': 'hostname',
            'kernel': 'uname -r',
            'architecture': 'uname -m',
            'uptime': 'uptime -p 2>/dev/null || uptime',
            'os_release': 'cat /etc/os-release 2>/dev/null'
        }

        for key, cmd in commands.items():
            result = self.ssh_connector.execute_command(cmd, log_command=False)
            if result.success:
                overview[key] = result.output.strip()
            else:
                self.logger.debug(f"Failed to get {key}: {result.error}")
                overview[key] = 'unavailable'

        # System-specific version info
        if system_type == 'unraid':
            result = self.ssh_connector.execute_command("cat /etc/unraid-version 2>/dev/null", log_command=False)
            if result.success:
                overview['unraid_version'] = result.output.strip()
        elif system_type == 'proxmox':
            result = self.ssh_connector.execute_command("pveversion", log_command=False)
            if result.success:
                overview['proxmox_version'] = result.output.strip()
        else:
            # For other Linux distributions, parse os-release for distribution info
            if overview.get('os_release') and overview['os_release'] != 'unavailable':
                dist_info = self._parse_os_release(overview['os_release'])
                if dist_info.get('name'):
                    overview['distribution'] = dist_info['name']
                if dist_info.get('version'):
                    overview['distribution_version'] = dist_info['version']

        return overview

    def _get_hardware_profile(self) -> Dict[str, Any]:
        """Get hardware information"""
        self.logger.debug("Collecting hardware profile...")
        hardware = {}

        # CPU information
        self.logger.debug("Getting CPU information...")
        cpu_info = self._get_cpu_information()
        if cpu_info:
            hardware['cpu'] = cpu_info

        # Memory information
        self.logger.debug("Getting memory information...")
        memory_info = self._get_memory_information()
        if memory_info:
            hardware['memory'] = memory_info

        # Motherboard information
        self.logger.debug("Getting motherboard information...")
        motherboard_info = self._get_motherboard_information()
        if motherboard_info:
            hardware['motherboard'] = motherboard_info

        # Storage devices
        self.logger.debug("Getting storage devices...")
        storage_devices = self._get_storage_devices()
        if storage_devices:
            hardware['storage_devices'] = storage_devices

        # PCI devices
        self.logger.debug("Getting PCI devices...")
        pci_devices = self._get_pci_devices()
        if pci_devices:
            hardware['pci_devices'] = pci_devices

        # USB devices
        self.logger.debug("Getting USB devices...")
        usb_devices = self._get_usb_devices()
        if usb_devices:
            hardware['usb_devices'] = usb_devices

        # Temperature sensors
        self.logger.debug("Getting temperature sensors...")
        temperatures = self._get_temperature_sensors()
        if temperatures:
            hardware['temperatures'] = temperatures

        # GPU information (discrete GPUs)
        self.logger.debug("Getting GPU information...")
        gpus = self._get_gpu_information()
        if gpus:
            hardware['gpus'] = gpus

        return hardware

    def _get_cpu_information(self) -> Dict[str, Any]:
        """Get detailed CPU information"""
        cpu_info = {}

        # Get CPU model and details from /proc/cpuinfo
        result = self.ssh_connector.execute_command("cat /proc/cpuinfo", timeout=10, log_command=False)
        if result.success:
            lines = result.output.split('\n')
            for line in lines:
                if 'model name' in line and 'model_name' not in cpu_info:
                    cpu_info['model_name'] = line.split(':', 1)[1].strip()
                elif 'cpu MHz' in line and 'frequency' not in cpu_info:
                    try:
                        cpu_info['frequency_mhz'] = float(line.split(':', 1)[1].strip())
                    except:
                        pass

        # Get core and thread count
        result = self.ssh_connector.execute_command("nproc", log_command=False)
        if result.success:
            try:
                cpu_info['threads'] = int(result.output.strip())
            except:
                pass

        # Get logical core count
        result = self.ssh_connector.execute_command("grep -c processor /proc/cpuinfo", log_command=False)
        if result.success:
            try:
                cpu_info['logical_cores'] = int(result.output.strip())
            except:
                pass

        # Try to get physical cores
        result = self.ssh_connector.execute_command("grep 'cpu cores' /proc/cpuinfo | head -1", log_command=False)
        if result.success and ':' in result.output:
            try:
                cpu_info['physical_cores'] = int(result.output.split(':', 1)[1].strip())
            except:
                pass

        return cpu_info

    def _get_memory_information(self) -> Dict[str, Any]:
        """Get memory information"""
        memory_info = {}

        # Get memory from /proc/meminfo
        result = self.ssh_connector.execute_command("cat /proc/meminfo", timeout=10, log_command=False)
        if result.success:
            for line in result.output.split('\n'):
                if 'MemTotal:' in line:
                    try:
                        kb = int(line.split()[1])
                        memory_info['total_kb'] = kb
                        memory_info['total_gb'] = round(kb / 1024 / 1024, 2)
                    except:
                        pass
                elif 'MemAvailable:' in line:
                    try:
                        kb = int(line.split()[1])
                        memory_info['available_kb'] = kb
                        memory_info['available_gb'] = round(kb / 1024 / 1024, 2)
                    except:
                        pass

        # Get memory usage summary
        result = self.ssh_connector.execute_command("free -h", log_command=False)
        if result.success:
            memory_info['free_summary'] = result.output

        # Try to get detailed memory module info with dmidecode
        result = self.ssh_connector.execute_command(
            "dmidecode -t memory 2>/dev/null | grep -E 'Size:|Speed:|Type:|Manufacturer:' | head -20",
            timeout=15, log_command=False)
        if result.success and result.output.strip():
            memory_info['modules'] = result.output

        return memory_info

    def _get_motherboard_information(self) -> Dict[str, Any]:
        """Get motherboard information"""
        motherboard = {}

        # Try dmidecode for motherboard info
        commands = {
            'manufacturer': 'dmidecode -s baseboard-manufacturer 2>/dev/null',
            'product': 'dmidecode -s baseboard-product-name 2>/dev/null',
            'version': 'dmidecode -s baseboard-version 2>/dev/null',
            'serial': 'dmidecode -s baseboard-serial-number 2>/dev/null'
        }

        for key, cmd in commands.items():
            result = self.ssh_connector.execute_command(cmd, timeout=10, log_command=False)
            if result.success and result.output.strip():
                motherboard[key] = result.output.strip()

        return motherboard

    def _get_storage_devices(self) -> List[Dict]:
        """Get storage device information (hardware devices only, excludes loop/virtual devices)"""
        devices = []

        # Use lsblk for storage devices - exclude loop devices
        # -d: only show top-level devices (not partitions)
        # -e7: exclude loop devices (major number 7)
        result = self.ssh_connector.execute_command_with_fallback(
            "lsblk -d -e7 -o NAME,SIZE,TYPE,MODEL,SERIAL,ROTA,TRAN -J 2>/dev/null",
            "lsblk -d -e7 -o NAME,SIZE,TYPE,MODEL,SERIAL,ROTA,TRAN",
            timeout=15,
            context="storage devices"
        )

        if result.success:
            try:
                if result.command.endswith('-J 2>/dev/null'):
                    # JSON format
                    data = json.loads(result.output)
                    raw_devices = data.get('blockdevices', [])

                    # Filter out virtual/non-hardware devices by type
                    for device in raw_devices:
                        device_type = device.get('type', '').lower()
                        # Only include physical disk types
                        if device_type in ['disk', 'part', 'raid']:
                            devices.append(device)
                else:
                    # Text format fallback - store as-is since we already filtered with -e7
                    devices = [{'lsblk_output': result.output}]
            except json.JSONDecodeError:
                # If JSON parsing fails, store as text
                devices = [{'lsblk_output': result.output}]

        return devices

    def _get_pci_devices(self) -> List[str]:
        """Get PCI device information"""
        result = self.ssh_connector.execute_command("lspci", timeout=10, log_command=False)
        if result.success:
            return result.output.strip().split('\n')
        return []

    def _get_usb_devices(self) -> List[str]:
        """Get USB device information"""
        result = self.ssh_connector.execute_command("lsusb", timeout=10, log_command=False)
        if result.success:
            return result.output.strip().split('\n')
        return []

    def _get_temperature_sensors(self) -> Dict[str, Any]:
        """Get temperature sensor data"""
        temperatures = {}

        # Try sensors command
        result = self.ssh_connector.execute_command("sensors 2>/dev/null", timeout=15, log_command=False)
        if result.success and result.output.strip():
            temperatures['sensors_output'] = result.output

            # Try to parse specific temperature values
            temp_values = {}
            for line in result.output.split('\n'):
                if '°C' in line and ':' in line:
                    try:
                        parts = line.split(':')
                        sensor_name = parts[0].strip()
                        temp_part = parts[1].strip()
                        # Extract temperature value
                        temp_match = re.search(r'([+-]?\d+\.?\d*)°C', temp_part)
                        if temp_match:
                            temp_values[sensor_name] = float(temp_match.group(1))
                    except:
                        pass

            if temp_values:
                temperatures['parsed_temperatures'] = temp_values

        return temperatures

    def _get_gpu_information(self) -> List[Dict[str, Any]]:
        """Get discrete GPU information (NVIDIA, AMD, Intel)"""
        gpus = []

        # Try NVIDIA GPUs first using nvidia-smi
        self.logger.debug("Checking for NVIDIA GPUs...")
        result = self.ssh_connector.execute_command(
            "nvidia-smi --query-gpu=index,name,driver_version,memory.total,memory.used,memory.free,temperature.gpu,utilization.gpu,pcie.link.gen.current,pcie.link.width.current --format=csv,noheader,nounits 2>/dev/null",
            timeout=15, log_command=False
        )

        if result.success and result.output.strip():
            # Parse NVIDIA GPU information
            for line in result.output.strip().split('\n'):
                try:
                    parts = [p.strip() for p in line.split(',')]
                    if len(parts) >= 6:
                        gpu_info = {
                            'vendor': 'NVIDIA',
                            'index': int(parts[0]),
                            'model': parts[1],
                            'driver_version': parts[2],
                            'memory_total_mb': int(parts[3]) if parts[3] else None,
                            'is_discrete': True  # NVIDIA GPUs detected via nvidia-smi are always discrete
                        }

                        # Add optional fields if available (excluding real-time metrics)
                        if len(parts) > 8 and parts[8]:
                            gpu_info['pcie_generation'] = int(parts[8])
                        if len(parts) > 9 and parts[9]:
                            gpu_info['pcie_width'] = int(parts[9])

                        gpus.append(gpu_info)
                except (ValueError, IndexError) as e:
                    self.logger.debug(f"Failed to parse NVIDIA GPU line: {line}, error: {e}")

        # Try AMD GPUs using rocm-smi
        self.logger.debug("Checking for AMD GPUs...")
        result = self.ssh_connector.execute_command("rocm-smi --showproductname --showmeminfo vram --showtemp 2>/dev/null",
                                                    timeout=15, log_command=False)

        if result.success and result.output.strip() and 'not found' not in result.output.lower():
            # Parse AMD GPU information - rocm-smi output format varies, so capture as structured text
            current_gpu = None
            for line in result.output.strip().split('\n'):
                if 'GPU' in line and '[' in line:
                    # Start of new GPU section (e.g., "GPU[0]")
                    if current_gpu:
                        gpus.append(current_gpu)
                    current_gpu = {
                        'vendor': 'AMD',
                        'is_discrete': True,  # AMD GPUs detected via rocm-smi are always discrete
                        'rocm_smi_output': []
                    }

                if current_gpu:
                    current_gpu['rocm_smi_output'].append(line)

                    # Try to extract specific fields (excluding real-time metrics)
                    if 'Card series:' in line or 'Card model:' in line:
                        current_gpu['model'] = line.split(':', 1)[1].strip()
                    elif 'VRAM Total Memory' in line:
                        try:
                            # Extract memory size
                            mem_match = re.search(r'(\d+)', line)
                            if mem_match:
                                current_gpu['memory_total_mb'] = int(mem_match.group(1))
                        except:
                            pass

            if current_gpu:
                gpus.append(current_gpu)

        # Try Intel GPUs using intel_gpu_top or lspci
        self.logger.debug("Checking for Intel discrete GPUs...")
        result = self.ssh_connector.execute_command(
            "lspci | grep -i 'vga\\|3d\\|display' | grep -i intel",
            timeout=10, log_command=False
        )

        if result.success and result.output.strip():
            for line in result.output.strip().split('\n'):
                # Parse lspci output for Intel GPUs
                # Example: 00:02.0 VGA compatible controller: Intel Corporation Device 4680 (rev 0c)
                if 'intel' in line.lower():
                    gpu_info = {
                        'vendor': 'Intel',
                        'lspci_line': line.strip()
                    }

                    # Try to extract model name
                    if ':' in line:
                        parts = line.split(':', 2)
                        if len(parts) >= 3:
                            model_part = parts[2].strip()
                            gpu_info['model'] = model_part

                    # Check if it's integrated or discrete by looking at the bus ID
                    # Typically integrated GPUs are on bus 00:02.0
                    bus_match = re.match(r'^(\d+):(\d+)\.\d+', line)
                    if bus_match:
                        bus_num = int(bus_match.group(1))
                        device_num = int(bus_match.group(2))
                        # If not the typical integrated GPU location, likely discrete
                        if not (bus_num == 0 and device_num == 2):
                            gpu_info['is_discrete'] = True
                            gpus.append(gpu_info)
                        else:
                            gpu_info['is_discrete'] = False
                            # Still include it but note it might be integrated
                            gpus.append(gpu_info)

        # Fallback: Use lspci to find any discrete GPUs we might have missed
        if not gpus:
            self.logger.debug("No GPUs detected via specialized tools, checking lspci for any discrete GPUs...")
            result = self.ssh_connector.execute_command(
                "lspci | grep -i 'vga\\|3d\\|display' | grep -iv 'audio'",
                timeout=10, log_command=False
            )

            if result.success and result.output.strip():
                for line in result.output.strip().split('\n'):
                    gpu_info = {
                        'vendor': 'Unknown',
                        'lspci_line': line.strip()
                    }

                    # Try to determine vendor from line
                    line_lower = line.lower()
                    if 'nvidia' in line_lower:
                        gpu_info['vendor'] = 'NVIDIA'
                    elif 'amd' in line_lower or 'ati' in line_lower:
                        gpu_info['vendor'] = 'AMD'
                    elif 'intel' in line_lower:
                        gpu_info['vendor'] = 'Intel'

                    # Extract model name
                    if ':' in line:
                        parts = line.split(':', 2)
                        if len(parts) >= 3:
                            gpu_info['model'] = parts[2].strip()

                    gpus.append(gpu_info)

        return gpus

    def _get_storage_configuration(self, system_type: str) -> Dict[str, Any]:
        """Get storage configuration based on system type"""
        self.logger.debug(f"Collecting storage configuration for {system_type}...")
        storage = {}

        # Common storage info
        result = self.ssh_connector.execute_command("df -h", timeout=10, log_command=False)
        if result.success:
            storage['filesystem_usage'] = result.output

        # System-specific storage info
        if system_type == 'unraid':
            self.logger.debug("Getting Unraid-specific storage info...")
            storage.update(self._get_unraid_storage())
        elif system_type == 'proxmox':
            self.logger.debug("Getting Proxmox-specific storage info...")
            storage.update(self._get_proxmox_storage())

        # ZFS pools (if any)
        result = self.ssh_connector.execute_command("zpool list 2>/dev/null", timeout=10, log_command=False)
        if result.success and result.output.strip():
            storage['zfs_pools'] = result.output

        # BTRFS filesystems (if any)
        result = self.ssh_connector.execute_command("btrfs filesystem show 2>/dev/null", timeout=10, log_command=False)
        if result.success and result.output.strip():
            storage['btrfs_filesystems'] = result.output

        return storage

    def _get_unraid_storage(self) -> Dict[str, Any]:
        """Get Unraid-specific storage information"""
        unraid_storage = {}

        # Array status
        result = self.ssh_connector.execute_command("cat /proc/mdstat", timeout=10, log_command=False)
        if result.success:
            unraid_storage['array_status'] = result.output

        # User shares
        result = self.ssh_connector.execute_command("ls -la /mnt/user/ 2>/dev/null", timeout=10, log_command=False)
        if result.success:
            unraid_storage['user_shares'] = result.output

        # Disk usage of shares (with timeout protection)
        result = self.ssh_connector.execute_command("timeout 30 du -sh /mnt/user/* 2>/dev/null | sort -hr | head -20",
                                                    timeout=35, log_command=False)
        if result.success:
            unraid_storage['share_usage'] = result.output
        elif 'timeout' in result.error.lower():
            self.logger.warning("Share usage calculation timed out - shares may be very large")
            unraid_storage['share_usage'] = "Calculation timed out - use 'du -sh /mnt/user/*' manually"

        return unraid_storage

    def _get_proxmox_storage(self) -> Dict[str, Any]:
        """Get Proxmox-specific storage information"""
        proxmox_storage = {}

        # Proxmox storage status
        result = self.ssh_connector.execute_command("pvesm status", timeout=15, log_command=False)
        if result.success:
            proxmox_storage['storage_status'] = result.output

        # LVM information
        result = self.ssh_connector.execute_command("pvdisplay 2>/dev/null", timeout=10, log_command=False)
        if result.success and result.output.strip():
            proxmox_storage['lvm_physical_volumes'] = result.output

        result = self.ssh_connector.execute_command("vgdisplay 2>/dev/null", timeout=10, log_command=False)
        if result.success and result.output.strip():
            proxmox_storage['lvm_volume_groups'] = result.output

        return proxmox_storage

    def _get_network_configuration(self) -> Dict[str, Any]:
        """Get network configuration"""
        self.logger.debug("Collecting network configuration...")
        network = {}

        # Network interfaces
        result = self.ssh_connector.execute_command("ip addr show", timeout=10, log_command=False)
        if result.success:
            network['interfaces'] = result.output

        # Routing table
        result = self.ssh_connector.execute_command("ip route show", timeout=10, log_command=False)
        if result.success:
            network['routes'] = result.output

        # Network statistics
        result = self.ssh_connector.execute_command("ss -tuln", timeout=10, log_command=False)
        if result.success:
            network['listening_ports'] = result.output

        # Network interface statistics
        result = self.ssh_connector.execute_command("cat /proc/net/dev", timeout=10, log_command=False)
        if result.success:
            network['interface_stats'] = result.output

        return network

    def _get_service_status(self, system_type: str) -> Dict[str, Any]:
        """Get service status information with system-specific handling"""
        self.logger.debug(f"Collecting service status for {system_type}...")
        services = {}

        # System services - handle different init systems
        if system_type == 'unraid':
            # Unraid uses a custom init system, try different approaches
            result = self.ssh_connector.execute_command_with_fallback(
                "ps aux | grep -E '(emhttpd|shfs|docker|nginx)' | grep -v grep",
                "ps aux | head -20",
                timeout=10,
                context="Unraid services"
            )
            if result.success:
                services['running_processes'] = result.output
        else:
            # Use systemctl for modern Linux distributions
            result = self.ssh_connector.execute_command_with_fallback(
                "systemctl list-units --type=service --state=running",
                "service --status-all 2>/dev/null | grep '+' || ps aux | head -20",
                timeout=15,
                context="system services"
            )
            if result.success:
                services['running_services'] = result.output

        # Check for common monitoring services with fallbacks
        monitoring_services = ['prometheus', 'grafana-server', 'node-exporter', 'loki']
        services['monitoring'] = {}

        for service in monitoring_services:
            # Try systemctl first, fallback to process check
            result = self.ssh_connector.execute_command_with_fallback(
                f"systemctl is-active {service} 2>/dev/null",
                f"pgrep -f {service} >/dev/null && echo 'active' || echo 'inactive'",
                timeout=5,
                context=f"monitoring service {service}"
            )
            if result.success:
                services['monitoring'][service] = result.output.strip()

        return services

    def _get_docker_configuration(self) -> Dict[str, Any]:
        """Get Docker configuration and status"""
        self.logger.debug("Collecting Docker configuration...")
        docker = {}

        # Docker version
        result = self.ssh_connector.execute_command("docker --version 2>/dev/null", timeout=10, log_command=False)
        if result.success:
            docker['version'] = result.output.strip()

        # Running containers (summary)
        result = self.ssh_connector.execute_command(
            "docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}' 2>/dev/null",
            timeout=15, log_command=False)
        if result.success:
            docker['running_containers'] = result.output

        # Docker system info
        result = self.ssh_connector.execute_command("docker system df 2>/dev/null", timeout=10, log_command=False)
        if result.success:
            docker['system_usage'] = result.output

        # Docker networks
        result = self.ssh_connector.execute_command("docker network ls 2>/dev/null", timeout=10, log_command=False)
        if result.success:
            docker['networks'] = result.output

        return docker

    def _get_resource_usage(self) -> Dict[str, Any]:
        """Get current resource usage"""
        self.logger.debug("Collecting resource usage...")
        resources = {}

        # System load
        result = self.ssh_connector.execute_command("cat /proc/loadavg", timeout=5, log_command=False)
        if result.success:
            resources['load_average'] = result.output.strip()

        # Top processes by CPU
        result = self.ssh_connector.execute_command("ps aux --sort=-%cpu | head -21", timeout=10, log_command=False)
        if result.success:
            resources['top_processes_cpu'] = result.output

        # Top processes by memory
        result = self.ssh_connector.execute_command("ps aux --sort=-%mem | head -21", timeout=10, log_command=False)
        if result.success:
            resources['top_processes_memory'] = result.output

        # Disk I/O (if iostat available)
        result = self.ssh_connector.execute_command("iostat -x 1 2 2>/dev/null | tail -n +4", timeout=15,
                                                    log_command=False)
        if result.success and result.output.strip():
            resources['disk_io'] = result.output

        return resources

    def _get_system_information(self) -> Dict[str, Any]:
        """Get additional system information"""
        self.logger.debug("Collecting additional system information...")
        system_info = {}

        # Kernel modules
        result = self.ssh_connector.execute_command("lsmod | head -20", timeout=10, log_command=False)
        if result.success:
            system_info['loaded_modules'] = result.output

        # System logs (recent) - try different log locations
        result = self.ssh_connector.execute_command_with_fallback(
            "journalctl --since '1 hour ago' --no-pager -n 50 2>/dev/null",
            "tail -n 50 /var/log/syslog 2>/dev/null || tail -n 50 /var/log/messages 2>/dev/null || echo 'No recent logs available'",
            timeout=15,
            context="recent logs"
        )
        if result.success:
            system_info['recent_logs'] = result.output

        # Cron jobs
        result = self.ssh_connector.execute_command("crontab -l 2>/dev/null", timeout=5, log_command=False)
        if result.success and result.output.strip():
            system_info['cron_jobs'] = result.output

        return system_info

    def _get_security_status(self) -> Dict[str, Any]:
        """Get security-related information"""
        self.logger.debug("Collecting security status...")
        security = {}

        # SSH configuration (non-sensitive parts)
        result = self.ssh_connector.execute_command(
            "grep -E '^(Port|PermitRootLogin|PasswordAuthentication|PubkeyAuthentication)' /etc/ssh/sshd_config 2>/dev/null",
            timeout=5, log_command=False)
        if result.success:
            security['ssh_config'] = result.output

        # Firewall status - try different firewall tools
        result = self.ssh_connector.execute_command_with_fallback(
            "ufw status 2>/dev/null",
            "iptables -L -n | head -20 2>/dev/null || echo 'No firewall info available'",
            timeout=10,
            context="firewall status"
        )
        if result.success and result.output.strip():
            security['firewall_status'] = result.output

        # Failed login attempts (last 50) - try different log locations
        result = self.ssh_connector.execute_command_with_fallback(
            "grep 'Failed password' /var/log/auth.log 2>/dev/null | tail -50 | wc -l",
            "grep 'Failed password' /var/log/secure 2>/dev/null | tail -50 | wc -l || echo '0'",
            timeout=10,
            context="failed login attempts"
        )
        if result.success:
            try:
                security['recent_failed_logins'] = int(result.output.strip())
            except:
                security['recent_failed_logins'] = 0

        return security

    def _parse_os_release(self, os_release_content: str) -> Dict[str, str]:
        """Parse /etc/os-release content to extract distribution info"""
        dist_info = {}

        for line in os_release_content.split('\n'):
            line = line.strip()
            if not line or '=' not in line:
                continue

            key, value = line.split('=', 1)
            # Remove quotes from value
            value = value.strip('"').strip("'")

            if key == 'NAME':
                dist_info['name'] = value
            elif key == 'VERSION':
                dist_info['version'] = value
            elif key == 'VERSION_ID':
                # Use VERSION_ID as fallback if VERSION is not available
                if 'version' not in dist_info:
                    dist_info['version'] = value
            elif key == 'PRETTY_NAME':
                # Store pretty name as alternative
                dist_info['pretty_name'] = value

        return dist_info

    def sanitize_data(self, data: Any) -> Any:
        """System documentation specific data sanitization"""
        if isinstance(data, dict):
            sanitized = {}
            for key, value in data.items():
                if any(sensitive in key.lower() for sensitive in ['serial', 'password', 'secret', 'token', 'key']):
                    if key.lower() in ['serial', 'baseboard-serial-number']:
                        sanitized[key] = 'REDACTED'
                    else:
                        sanitized[key] = self.sanitize_data(value)
                else:
                    sanitized[key] = self.sanitize_data(value)
            return sanitized
        elif isinstance(data, str):
            # Sanitize MAC addresses
            data = re.sub(r'([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})', 'XX:XX:XX:XX:XX:XX', data)
            # Sanitize serial numbers in text
            data = re.sub(r'Serial Number:\s*\S+', 'Serial Number: REDACTED', data)
            return data
        elif isinstance(data, list):
            return [self.sanitize_data(item) for item in data]
        else:
            return data