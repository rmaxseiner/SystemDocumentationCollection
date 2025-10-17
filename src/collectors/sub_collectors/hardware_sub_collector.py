# src/collectors/sub_collectors/hardware_sub_collector.py
"""
Hardware Sub-Collector
Collects physical hardware information: CPU, memory, motherboard, storage devices, GPUs.
Extracted from SystemDocumentationCollector for use in unified collector system.
"""

import json
import re
from typing import Dict, Any, List
from .base_sub_collector import SubCollector


class HardwareSubCollector(SubCollector):
    """
    Collects physical hardware information from system.
    Uses dmidecode, lspci, lscpu, and other system commands.
    For VMs/LXC: collects hardware_allocation instead of physical hardware.
    """

    def __init__(self, ssh_connector, system_name: str, is_virtualized: bool = False):
        """
        Initialize hardware collector

        Args:
            ssh_connector: SSH connector
            system_name: System name
            is_virtualized: True if system is VM or LXC container
        """
        super().__init__(ssh_connector, system_name)
        self.is_virtualized = is_virtualized

    def get_section_name(self) -> str:
        return "hardware_allocation" if self.is_virtualized else "hardware"

    def collect(self) -> Dict[str, Any]:
        """
        Collect hardware information

        Returns:
            Dict with CPU, memory, motherboard, storage, PCI/USB devices, GPUs, temperatures
            OR hardware_allocation for VMs/LXC
        """
        self.log_start()

        if self.is_virtualized:
            # Collect allocation info for VMs/LXC
            hardware = self._collect_hardware_allocation()
        else:
            # Collect physical hardware for bare metal
            hardware = self._collect_physical_hardware()

        self.log_end()
        return hardware

    def _collect_physical_hardware(self) -> Dict[str, Any]:
        """Collect physical hardware information for bare metal systems"""
        hardware = {}

        # CPU information
        cpu_info = self._get_cpu_information()
        if cpu_info:
            hardware['cpu'] = cpu_info

        # Memory information
        memory_info = self._get_memory_information()
        if memory_info:
            hardware['memory'] = memory_info

        # Motherboard information
        motherboard_info = self._get_motherboard_information()
        if motherboard_info:
            hardware['motherboard'] = motherboard_info

        # Storage devices
        storage_devices = self._get_storage_devices()
        if storage_devices:
            hardware['storage_devices'] = storage_devices

        # PCI devices
        pci_devices = self._get_pci_devices()
        if pci_devices:
            hardware['pci_devices'] = pci_devices

        # USB devices
        usb_devices = self._get_usb_devices()
        if usb_devices:
            hardware['usb_devices'] = usb_devices

        # Temperature sensors
        temperatures = self._get_temperature_sensors()
        if temperatures:
            hardware['temperatures'] = temperatures

        # GPU information (discrete GPUs)
        gpus = self._get_gpu_information()
        if gpus:
            hardware['gpus'] = gpus

        return hardware

    def _collect_hardware_allocation(self) -> Dict[str, Any]:
        """Collect hardware allocation info for VMs and LXC containers"""
        allocation = {}

        # CPU allocation
        cpu_alloc = self._get_cpu_allocation()
        if cpu_alloc:
            allocation['cpu'] = cpu_alloc

        # Memory allocation
        memory_alloc = self._get_memory_allocation()
        if memory_alloc:
            allocation['memory'] = memory_alloc

        # Storage allocation (mounted filesystems and their sizes)
        storage_alloc = self._get_storage_allocation()
        if storage_alloc:
            allocation['storage'] = storage_alloc

        # Network interfaces (virtual)
        network_alloc = self._get_network_allocation()
        if network_alloc:
            allocation['network'] = network_alloc

        # Container/VM specific metadata
        virtualization_info = self._get_virtualization_metadata()
        if virtualization_info:
            allocation['virtualization'] = virtualization_info

        return allocation

    def _get_cpu_allocation(self) -> Dict[str, Any]:
        """Get allocated CPU information for VM/LXC"""
        cpu_info = {}

        # Number of allocated vCPUs/cores
        result = self.ssh.execute_command("nproc", log_command=False)
        if result.success:
            try:
                cpu_info['allocated_vcpus'] = int(result.output.strip())
            except:
                pass

        # CPU model (what the host is providing)
        result = self.ssh.execute_command("grep 'model name' /proc/cpuinfo | head -1", log_command=False)
        if result.success and ':' in result.output:
            cpu_info['model_name'] = result.output.split(':', 1)[1].strip()

        # CPU limits (if available from cgroups)
        result = self.ssh.execute_command("cat /sys/fs/cgroup/cpu/cpu.shares 2>/dev/null", log_command=False)
        if result.success and result.output.strip():
            try:
                cpu_info['cpu_shares'] = int(result.output.strip())
            except:
                pass

        # CPU quota (cgroups v1)
        result = self.ssh.execute_command("cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us 2>/dev/null", log_command=False)
        if result.success and result.output.strip() and result.output.strip() != '-1':
            try:
                cpu_info['cpu_quota_us'] = int(result.output.strip())
            except:
                pass

        return cpu_info

    def _get_memory_allocation(self) -> Dict[str, Any]:
        """Get allocated memory information for VM/LXC"""
        memory_info = {}

        # Total allocated memory
        result = self.ssh.execute_command("cat /proc/meminfo | grep MemTotal", log_command=False)
        if result.success:
            try:
                kb = int(result.output.split()[1])
                memory_info['allocated_kb'] = kb
                memory_info['allocated_gb'] = round(kb / 1024 / 1024, 2)
            except:
                pass

        # Current memory usage
        result = self.ssh.execute_command("free -b | grep Mem", log_command=False)
        if result.success:
            try:
                parts = result.output.split()
                if len(parts) >= 3:
                    total = int(parts[1])
                    used = int(parts[2])
                    memory_info['used_bytes'] = used
                    memory_info['used_gb'] = round(used / 1024 / 1024 / 1024, 2)
                    memory_info['used_percentage'] = round((used / total) * 100, 2) if total > 0 else 0
            except:
                pass

        # Memory limit (cgroups)
        result = self.ssh.execute_command("cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null", log_command=False)
        if result.success and result.output.strip():
            try:
                limit = int(result.output.strip())
                # Very large values mean unlimited
                if limit < 9223372036854771712:  # Not unlimited
                    memory_info['limit_bytes'] = limit
                    memory_info['limit_gb'] = round(limit / 1024 / 1024 / 1024, 2)
            except:
                pass

        return memory_info

    def _get_storage_allocation(self) -> List[Dict[str, Any]]:
        """Get storage allocation (mounted filesystems) for VM/LXC"""
        storage = []

        # Get all mounted filesystems with sizes
        result = self.ssh.execute_command("df -h --output=source,fstype,size,used,avail,pcent,target | grep -v tmpfs | grep -v devtmpfs", log_command=False)
        if result.success:
            lines = result.output.strip().split('\n')
            # Skip header
            for line in lines[1:]:
                try:
                    parts = line.split()
                    if len(parts) >= 7:
                        mount_info = {
                            'device': parts[0],
                            'filesystem_type': parts[1],
                            'size': parts[2],
                            'used': parts[3],
                            'available': parts[4],
                            'use_percentage': parts[5],
                            'mount_point': ' '.join(parts[6:])  # Handle mount points with spaces
                        }
                        storage.append(mount_info)
                except:
                    pass

        return storage

    def _get_network_allocation(self) -> List[Dict[str, Any]]:
        """Get network interface allocation for VM/LXC"""
        interfaces = []

        # Get network interfaces (excluding loopback)
        result = self.ssh.execute_command("ip -j addr show 2>/dev/null", log_command=False)
        if result.success:
            try:
                import json
                ifaces = json.loads(result.output)
                for iface in ifaces:
                    if iface.get('ifname') != 'lo':  # Skip loopback
                        iface_info = {
                            'name': iface.get('ifname'),
                            'state': iface.get('operstate'),
                            'mtu': iface.get('mtu'),
                            'mac_address': iface.get('address'),
                            'addresses': []
                        }

                        # Extract IP addresses
                        for addr_info in iface.get('addr_info', []):
                            iface_info['addresses'].append({
                                'family': addr_info.get('family'),
                                'address': addr_info.get('local'),
                                'prefix_len': addr_info.get('prefixlen')
                            })

                        interfaces.append(iface_info)
            except:
                # Fallback to text output
                pass

        # Fallback: simple text output
        if not interfaces:
            result = self.ssh.execute_command("ip addr show | grep -E '^[0-9]+:|inet ' | head -20", log_command=False)
            if result.success and result.output.strip():
                interfaces = [{'ip_addr_output': result.output}]

        return interfaces

    def _get_virtualization_metadata(self) -> Dict[str, Any]:
        """Get container/VM specific metadata"""
        virt_info = {}

        # Detect virtualization type
        result = self.ssh.execute_command("systemd-detect-virt 2>/dev/null", log_command=False)
        if result.success and result.output.strip():
            virt_info['type'] = result.output.strip()

        # LXC specific: container name
        result = self.ssh.execute_command("cat /proc/1/environ 2>/dev/null | tr '\\0' '\\n' | grep -E 'container=|HOSTNAME='", log_command=False)
        if result.success and result.output.strip():
            for line in result.output.strip().split('\n'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    if key == 'container':
                        virt_info['container_type'] = value
                    elif key == 'HOSTNAME':
                        virt_info['container_hostname'] = value

        # Check for Proxmox LXC ID
        result = self.ssh.execute_command("cat /etc/hostname", log_command=False)
        if result.success:
            virt_info['hostname'] = result.output.strip()

        return virt_info

    def _get_cpu_information(self) -> Dict[str, Any]:
        """Get detailed CPU information"""
        cpu_info = {}

        # Get CPU model and details from /proc/cpuinfo
        result = self.ssh.execute_command("cat /proc/cpuinfo", timeout=10, log_command=False)
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
        result = self.ssh.execute_command("nproc", log_command=False)
        if result.success:
            try:
                cpu_info['threads'] = int(result.output.strip())
            except:
                pass

        # Get logical core count
        result = self.ssh.execute_command("grep -c processor /proc/cpuinfo", log_command=False)
        if result.success:
            try:
                cpu_info['logical_cores'] = int(result.output.strip())
            except:
                pass

        # Try to get physical cores
        result = self.ssh.execute_command("grep 'cpu cores' /proc/cpuinfo | head -1", log_command=False)
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
        result = self.ssh.execute_command("cat /proc/meminfo", timeout=10, log_command=False)
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
        result = self.ssh.execute_command("free -h", log_command=False)
        if result.success:
            memory_info['free_summary'] = result.output

        # Try to get detailed memory module info with dmidecode
        result = self.ssh.execute_command(
            "dmidecode -t memory 2>/dev/null | grep -E 'Size:|Speed:|Type:|Manufacturer:' | head -20",
            timeout=15,
            log_command=False
        )
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
            'version': 'dmidecode -s baseboard-version 2>/dev/null'
        }

        for key, cmd in commands.items():
            result = self.ssh.execute_command(cmd, timeout=10, log_command=False)
            if result.success and result.output.strip():
                motherboard[key] = result.output.strip()

        return motherboard

    def _get_storage_devices(self) -> List[Dict]:
        """Get storage device information (hardware devices only, excludes loop/virtual devices)"""
        devices = []

        # Use lsblk for storage devices - exclude loop devices
        result = self.ssh.execute_command(
            "lsblk -d -e7 -o NAME,SIZE,TYPE,MODEL,SERIAL,ROTA,TRAN -J 2>/dev/null",
            timeout=15,
            log_command=False
        )

        if result.success:
            try:
                data = json.loads(result.output)
                raw_devices = data.get('blockdevices', [])

                # Filter out virtual/non-hardware devices by type
                for device in raw_devices:
                    device_type = device.get('type', '').lower()
                    # Only include physical disk types
                    if device_type in ['disk', 'part', 'raid']:
                        devices.append(device)

            except json.JSONDecodeError:
                # If JSON parsing fails, try text format
                text_result = self.ssh.execute_command(
                    "lsblk -d -e7 -o NAME,SIZE,TYPE,MODEL,SERIAL,ROTA,TRAN",
                    timeout=15,
                    log_command=False
                )
                if text_result.success:
                    devices = [{'lsblk_output': text_result.output}]

        return devices

    def _get_pci_devices(self) -> List[str]:
        """Get PCI device information"""
        result = self.ssh.execute_command("lspci", timeout=10, log_command=False)
        if result.success:
            return result.output.strip().split('\n')
        return []

    def _get_usb_devices(self) -> List[str]:
        """Get USB device information"""
        result = self.ssh.execute_command("lsusb", timeout=10, log_command=False)
        if result.success:
            return result.output.strip().split('\n')
        return []

    def _get_temperature_sensors(self) -> Dict[str, Any]:
        """Get temperature sensor data"""
        temperatures = {}

        # Try sensors command
        result = self.ssh.execute_command("sensors 2>/dev/null", timeout=15, log_command=False)
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
        result = self.ssh.execute_command(
            "nvidia-smi --query-gpu=index,name,driver_version,memory.total,pcie.link.gen.current,pcie.link.width.current --format=csv,noheader,nounits 2>/dev/null",
            timeout=15,
            log_command=False
        )

        if result.success and result.output.strip():
            # Parse NVIDIA GPU information
            for line in result.output.strip().split('\n'):
                try:
                    parts = [p.strip() for p in line.split(',')]
                    if len(parts) >= 4:
                        gpu_info = {
                            'vendor': 'NVIDIA',
                            'index': int(parts[0]),
                            'model': parts[1],
                            'driver_version': parts[2],
                            'memory_total_mb': int(parts[3]) if parts[3] else None,
                            'is_discrete': True
                        }

                        # Add optional fields if available
                        if len(parts) > 4 and parts[4]:
                            gpu_info['pcie_generation'] = int(parts[4])
                        if len(parts) > 5 and parts[5]:
                            gpu_info['pcie_width'] = int(parts[5])

                        gpus.append(gpu_info)
                except (ValueError, IndexError) as e:
                    self.logger.debug(f"Failed to parse NVIDIA GPU line: {line}, error: {e}")

        # Try AMD GPUs using rocm-smi
        result = self.ssh.execute_command(
            "rocm-smi --showproductname --showmeminfo vram 2>/dev/null",
            timeout=15,
            log_command=False
        )

        if result.success and result.output.strip() and 'not found' not in result.output.lower():
            # Parse AMD GPU information
            current_gpu = None
            for line in result.output.strip().split('\n'):
                if 'GPU' in line and '[' in line:
                    # Start of new GPU section
                    if current_gpu:
                        gpus.append(current_gpu)
                    current_gpu = {
                        'vendor': 'AMD',
                        'is_discrete': True,
                        'rocm_smi_output': []
                    }

                if current_gpu:
                    current_gpu['rocm_smi_output'].append(line)

                    # Try to extract specific fields
                    if 'Card series:' in line or 'Card model:' in line:
                        current_gpu['model'] = line.split(':', 1)[1].strip()
                    elif 'VRAM Total Memory' in line:
                        try:
                            mem_match = re.search(r'(\d+)', line)
                            if mem_match:
                                current_gpu['memory_total_mb'] = int(mem_match.group(1))
                        except:
                            pass

            if current_gpu:
                gpus.append(current_gpu)

        # Fallback: Use lspci to find any discrete GPUs
        if not gpus:
            result = self.ssh.execute_command(
                "lspci | grep -i 'vga\\|3d\\|display' | grep -iv 'audio'",
                timeout=10,
                log_command=False
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

                    # Check if discrete based on bus ID
                    bus_match = re.match(r'^(\d+):(\d+)\.\d+', line)
                    if bus_match:
                        bus_num = int(bus_match.group(1))
                        device_num = int(bus_match.group(2))
                        # Integrated GPUs typically on bus 00:02.0
                        gpu_info['is_discrete'] = not (bus_num == 0 and device_num == 2)

                    gpus.append(gpu_info)

        return gpus
