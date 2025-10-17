# src/collectors/capability_detector.py
"""
System Capability Detection
Automatically detects what capabilities a system has (Docker, Proxmox, physical hardware, etc.)
"""

from typing import List, Tuple
from dataclasses import dataclass, asdict
import logging


@dataclass
class SystemCapabilities:
    """Data class holding detected system capabilities"""

    # Platform/OS detection
    is_unraid: bool = False
    is_proxmox: bool = False
    is_ubuntu: bool = False
    is_debian: bool = False
    os_type: str = "unknown"

    # Container/Virtualization
    has_docker: bool = False
    has_lxc: bool = False
    has_kvm: bool = False

    # Physical vs Virtual vs Container
    is_physical: bool = False
    is_vm: bool = False
    is_lxc: bool = False  # NEW: System is running IN an LXC container

    # Storage systems
    has_zfs: bool = False
    has_btrfs: bool = False
    has_lvm: bool = False

    # Docker-specific
    has_docker_compose_files: bool = False
    docker_compose_locations: List[str] = None

    def __post_init__(self):
        """Initialize mutable defaults"""
        if self.docker_compose_locations is None:
            self.docker_compose_locations = []

    def to_dict(self):
        """Convert to dictionary"""
        return asdict(self)


class CapabilityDetector:
    """
    Detects system capabilities via SSH commands.
    All detection methods are non-invasive and read-only.
    """

    def __init__(self, ssh_connector, docker_compose_search_paths=None):
        """
        Initialize capability detector

        Args:
            ssh_connector: Connected SSHConnector instance
            docker_compose_search_paths: Optional list of paths to search for docker-compose files
        """
        self.ssh = ssh_connector
        self.logger = logging.getLogger('capability_detector')
        self.docker_compose_search_paths = docker_compose_search_paths

    def detect_all(self) -> SystemCapabilities:
        """
        Run all detection checks and return comprehensive capabilities

        Returns:
            SystemCapabilities: Detected capabilities
        """
        self.logger.info("Starting system capability detection")
        caps = SystemCapabilities()

        # Platform detection (order matters - most specific first)
        caps.is_unraid = self._detect_unraid()
        caps.is_proxmox = self._detect_proxmox()
        caps.is_ubuntu = self._detect_ubuntu()
        caps.is_debian = self._detect_debian()

        # Determine primary OS type
        caps.os_type = self._determine_os_type(caps)

        # Container/Virtualization platforms
        caps.has_docker = self._detect_docker()
        caps.has_lxc = self._detect_lxc()
        caps.has_kvm = self._detect_kvm()

        # Physical vs Virtual vs Container
        caps.is_lxc = self._detect_is_lxc_container()
        caps.is_physical = self._detect_physical_hardware()
        caps.is_vm = not caps.is_physical and not caps.is_lxc

        # Storage systems
        caps.has_zfs = self._detect_zfs()
        caps.has_btrfs = self._detect_btrfs()
        caps.has_lvm = self._detect_lvm()

        # Docker-specific capabilities
        if caps.has_docker:
            caps.has_docker_compose_files, caps.docker_compose_locations = \
                self._detect_docker_compose()

        self._log_detection_summary(caps)
        return caps

    def _detect_unraid(self) -> bool:
        """Detect if system is Unraid"""
        result = self.ssh.execute_command("cat /etc/unraid-version 2>/dev/null", log_command=False)
        is_unraid = result.success and result.output.strip() != ""
        if is_unraid:
            self.logger.info("Detected Unraid system")
        return is_unraid

    def _detect_proxmox(self) -> bool:
        """Detect if system is Proxmox"""
        result = self.ssh.execute_command("pveversion 2>/dev/null", log_command=False)
        is_proxmox = result.success and 'pve-manager' in result.output
        if is_proxmox:
            self.logger.info("Detected Proxmox system")
        return is_proxmox

    def _detect_ubuntu(self) -> bool:
        """Detect if system is Ubuntu"""
        result = self.ssh.execute_command("lsb_release -i 2>/dev/null || cat /etc/os-release 2>/dev/null", log_command=False)
        is_ubuntu = result.success and 'Ubuntu' in result.output
        if is_ubuntu:
            self.logger.info("Detected Ubuntu system")
        return is_ubuntu

    def _detect_debian(self) -> bool:
        """Detect if system is Debian"""
        result = self.ssh.execute_command("lsb_release -i 2>/dev/null || cat /etc/os-release 2>/dev/null", log_command=False)
        is_debian = result.success and 'Debian' in result.output
        if is_debian:
            self.logger.info("Detected Debian system")
        return is_debian

    def _determine_os_type(self, caps: SystemCapabilities) -> str:
        """Determine primary OS type from capabilities"""
        if caps.is_unraid:
            return "unraid"
        elif caps.is_proxmox:
            return "proxmox"
        elif caps.is_ubuntu:
            return "ubuntu"
        elif caps.is_debian:
            return "debian"
        else:
            # Try generic Linux detection
            result = self.ssh.execute_command("uname -s 2>/dev/null", log_command=False)
            if result.success and 'Linux' in result.output:
                return "linux"
            return "unknown"

    def _detect_docker(self) -> bool:
        """Detect if Docker is installed and accessible"""
        result = self.ssh.execute_command("docker --version 2>/dev/null", log_command=False)
        has_docker = result.success and 'Docker version' in result.output

        if has_docker:
            # Verify we can actually access Docker
            ping_result = self.ssh.execute_command("docker info 2>/dev/null | head -1", log_command=False)
            has_docker = ping_result.success

        if has_docker:
            self.logger.info("Detected Docker installation")
        return has_docker

    def _detect_lxc(self) -> bool:
        """Detect if LXC tools are available (can run LXC containers)"""
        result = self.ssh.execute_command("which lxc-ls 2>/dev/null", log_command=False)
        has_lxc = result.success and result.output.strip() != ""
        if has_lxc:
            self.logger.info("Detected LXC support")
        return has_lxc

    def _detect_is_lxc_container(self) -> bool:
        """Detect if system is running INSIDE an LXC container"""
        # Check systemd-detect-virt for lxc
        result = self.ssh.execute_command("systemd-detect-virt 2>/dev/null", log_command=False)
        if result.success and result.output.strip() in ['lxc', 'lxc-libvirt']:
            self.logger.info("Detected system is running inside LXC container")
            return True

        # Alternative: Check for /.dockerenv (docker container)
        result = self.ssh.execute_command("test -f /.dockerenv && echo 'docker' || echo 'none'", log_command=False)
        if result.success and 'docker' in result.output.strip():
            self.logger.info("Detected system is running inside Docker container")
            return True  # Also treat Docker as containerized

        # Check /proc/1/environ for container indicators
        result = self.ssh.execute_command("grep -qa container=lxc /proc/1/environ 2>/dev/null && echo 'lxc' || echo 'none'", log_command=False)
        if result.success and 'lxc' in result.output.strip():
            self.logger.info("Detected LXC container via /proc/1/environ")
            return True

        return False

    def _detect_kvm(self) -> bool:
        """Detect if KVM is available"""
        result = self.ssh.execute_command("lsmod | grep kvm 2>/dev/null", log_command=False)
        has_kvm = result.success and 'kvm' in result.output
        if has_kvm:
            self.logger.info("Detected KVM support")
        return has_kvm

    def _detect_physical_hardware(self) -> bool:
        """Detect if system is physical hardware (vs VM or container)"""
        # Check systemd-detect-virt first (most reliable)
        result = self.ssh.execute_command("systemd-detect-virt 2>/dev/null", log_command=False)
        if result.success:
            virt_type = result.output.strip()

            # Container types
            if virt_type in ['lxc', 'lxc-libvirt', 'docker', 'container']:
                self.logger.info(f"Detected container type: {virt_type}")
                return False

            # VM types
            vm_keywords = ['vmware', 'kvm', 'qemu', 'xen', 'virtualbox', 'hyperv', 'parallels', 'bochs']
            if virt_type in vm_keywords:
                self.logger.info(f"Detected virtual machine type: {virt_type}")
                return False

            # Physical hardware
            if virt_type == 'none':
                self.logger.info("Detected physical hardware (systemd-detect-virt)")
                return True

        # Fallback: Check DMI info for VM indicators
        vm_indicators = [
            "cat /sys/class/dmi/id/product_name 2>/dev/null",
            "cat /sys/class/dmi/id/sys_vendor 2>/dev/null"
        ]

        vm_keywords = ['vmware', 'virtualbox', 'qemu', 'kvm', 'xen', 'hyperv', 'parallels', 'bochs']

        for cmd in vm_indicators:
            result = self.ssh.execute_command(cmd, log_command=False)
            if result.success:
                output_lower = result.output.lower()
                for keyword in vm_keywords:
                    if keyword in output_lower:
                        self.logger.info(f"Detected virtual machine (found '{keyword}' in DMI)")
                        return False

        # Default to physical if we can't determine
        self.logger.info("Assuming physical hardware (could not detect virtualization)")
        return True

    def _detect_zfs(self) -> bool:
        """Detect if ZFS is available"""
        result = self.ssh.execute_command("zpool list 2>/dev/null", log_command=False)
        has_zfs = result.success and result.output.strip() != ""
        if has_zfs:
            self.logger.info("Detected ZFS pools")
        return has_zfs

    def _detect_btrfs(self) -> bool:
        """Detect if Btrfs is in use"""
        result = self.ssh.execute_command("btrfs filesystem show 2>/dev/null", log_command=False)
        has_btrfs = result.success and result.output.strip() != ""
        if has_btrfs:
            self.logger.info("Detected Btrfs filesystems")
        return has_btrfs

    def _detect_lvm(self) -> bool:
        """Detect if LVM is in use"""
        result = self.ssh.execute_command("vgs 2>/dev/null", log_command=False)
        has_lvm = result.success and result.output.strip() != ""
        if has_lvm:
            self.logger.info("Detected LVM volume groups")
        return has_lvm

    def _detect_docker_compose(self) -> Tuple[bool, List[str]]:
        """
        Find docker-compose files on host filesystem

        Returns:
            Tuple of (has_compose_files: bool, locations: List[str])
        """
        self.logger.info("Searching for docker-compose files on host filesystem")

        # Use configured search paths if provided, otherwise use defaults
        if self.docker_compose_search_paths:
            search_paths = self.docker_compose_search_paths
            self.logger.info(f"Using configured search paths: {len(search_paths)} paths")
        else:
            # Default locations where docker-compose files are stored
            search_paths = [
                '/root/dockerhome',
                '/home/*/dockerhome',
                '/opt/docker',
                '/docker',
                '/srv/docker',
                '/boot/config/plugins/compose.manager/projects'
            ]
            self.logger.info("Using default search paths")

        found_files = []

        for path in search_paths:
            # Search for docker-compose.yml or docker-compose.yaml
            result = self.ssh.execute_command(
                f"find {path} -type f \\( -name 'docker-compose.yml' -o -name 'docker-compose.yaml' \\) 2>/dev/null",
                log_command=False,
                timeout=30
            )

            if result.success and result.output.strip():
                files = [f.strip() for f in result.output.strip().split('\n') if f.strip()]
                found_files.extend(files)
                self.logger.debug(f"Found {len(files)} docker-compose files in {path}")

        if found_files:
            self.logger.info(f"Found {len(found_files)} docker-compose files on host filesystem")
            return (True, found_files)
        else:
            self.logger.info("No docker-compose files found on host filesystem")
            return (False, [])

    def _log_detection_summary(self, caps: SystemCapabilities):
        """Log summary of detected capabilities"""
        self.logger.info("=" * 60)
        self.logger.info("Capability Detection Summary:")
        self.logger.info(f"  OS Type: {caps.os_type}")

        if caps.is_unraid:
            self.logger.info("  Platform: Unraid")
        elif caps.is_proxmox:
            self.logger.info("  Platform: Proxmox VE")
        elif caps.is_ubuntu:
            self.logger.info("  Platform: Ubuntu")
        elif caps.is_debian:
            self.logger.info("  Platform: Debian")

        self.logger.info(f"  Physical Hardware: {caps.is_physical}")
        self.logger.info(f"  Virtual Machine: {caps.is_vm}")
        self.logger.info(f"  LXC/Container: {caps.is_lxc}")

        capabilities_list = []
        if caps.has_docker:
            capabilities_list.append("Docker")
        if caps.has_lxc:
            capabilities_list.append("LXC")
        if caps.has_kvm:
            capabilities_list.append("KVM")
        if caps.has_zfs:
            capabilities_list.append("ZFS")
        if caps.has_btrfs:
            capabilities_list.append("Btrfs")
        if caps.has_lvm:
            capabilities_list.append("LVM")

        if capabilities_list:
            self.logger.info(f"  Capabilities: {', '.join(capabilities_list)}")

        if caps.has_docker_compose_files:
            self.logger.info(f"  Docker Compose Files: {len(caps.docker_compose_locations)} found")

        self.logger.info("=" * 60)
