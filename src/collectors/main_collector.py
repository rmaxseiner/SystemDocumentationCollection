# src/collectors/main_collector.py
"""
Main Unified Collector
Orchestrates capability detection and runs appropriate sub-collectors.
Creates a single unified document per system with sections for each capability.
"""

from typing import Dict, Any
from datetime import datetime
from pathlib import Path

from .base_collector import SystemStateCollector, CollectionResult
from .capability_detector import CapabilityDetector, SystemCapabilities
from .sub_collectors import (
    DockerSubCollector,
    DockerComposeSubCollector,
    HardwareSubCollector,
    ProxmoxSubCollector,
    ConfigSubCollector,
    SystemInfoSubCollector,
    NetworkSubCollector,
    ResourceUsageSubCollector
)

try:
    from ..connectors.ssh_connector import SSHConnector
except ImportError:
    from src.connectors.ssh_connector import SSHConnector


class MainCollector(SystemStateCollector):
    """
    Unified collector that auto-detects system capabilities and runs
    appropriate sub-collectors.

    Benefits:
    - Single SSH connection per system
    - Auto-detection of capabilities
    - Unified document output
    - Extensible sub-collector architecture
    """

    def __init__(self, name: str, config: Dict):
        super().__init__(name, config)

        # Initialize SSH connector
        self.ssh_connector = SSHConnector(
            host=self.host,
            port=self.port,
            username=self.username,
            ssh_key_path=config.get('ssh_key_path'),
            timeout=self.timeout
        )

        # Store configuration for sub-collectors
        self.config = config

        # Extract docker compose search paths from config if provided
        self.docker_compose_search_paths = config.get('docker_compose_search_paths')

    def validate_config(self) -> bool:
        """Validate main collector configuration"""
        if not self.host:
            self.logger.error("Host required for main collector")
            return False
        return True

    def get_system_state(self) -> Dict[str, Any]:
        """
        Main collection orchestration:
        1. Connect to system
        2. Detect capabilities
        3. Run applicable sub-collectors
        4. Assemble unified document
        """
        try:
            # Step 1: Connect via SSH
            self.logger.info(f"Connecting to {self.host}...")
            if not self.ssh_connector.connect():
                raise Exception("Failed to establish SSH connection")

            # Step 2: Detect system capabilities
            self.logger.info(f"Detecting capabilities for {self.name}...")
            detector = CapabilityDetector(
                self.ssh_connector,
                docker_compose_search_paths=self.docker_compose_search_paths
            )
            capabilities = detector.detect_all()

            # Step 3: Run applicable sub-collectors
            self.logger.info(f"Running sub-collectors for {self.name}...")
            sections = self._run_sub_collectors(capabilities)

            # Step 4: Assemble unified document
            unified_document = self._assemble_unified_document(capabilities, sections)

            # Disconnect
            self.ssh_connector.disconnect()

            self.logger.info(f"Collection completed successfully for {self.name}")
            return unified_document

        except Exception as e:
            self.logger.error(f"Failed to collect system state: {e}")
            if self.ssh_connector:
                self.ssh_connector.disconnect()
            raise

    def _run_sub_collectors(self, capabilities: SystemCapabilities) -> Dict[str, Any]:
        """
        Run applicable sub-collectors based on detected capabilities

        Args:
            capabilities: Detected system capabilities

        Returns:
            Dict mapping section names to collected data
        """
        sections = {}

        # Always collect system info (OS, kernel, uptime, hostname)
        sections['system_overview'] = self._run_system_info_sub_collector()

        # Always collect network details (interfaces, routes, ports)
        sections['network_details'] = self._run_network_sub_collector()

        # Always collect resource usage (load, processes, disk I/O)
        sections['resource_usage'] = self._run_resource_usage_sub_collector()

        # Always collect hardware info (physical or allocation)
        # Pass virtualization status to hardware collector
        is_virtualized = capabilities.is_vm or capabilities.is_lxc
        sections[self._get_hardware_section_name(is_virtualized)] = self._run_hardware_sub_collector(is_virtualized)

        # Collect Docker data if Docker is present
        if capabilities.has_docker:
            sections['docker'] = self._run_docker_sub_collector()

            # Collect Docker Compose files if present on host
            if capabilities.has_docker_compose_files:
                sections['docker_compose'] = self._run_docker_compose_sub_collector(
                    capabilities.docker_compose_locations
                )

            # Collect service configuration files if service_definitions are configured
            if self.config.get('service_definitions'):
                self.logger.info(f"Collecting service configuration files for {self.name}...")
                sections['configuration_files'] = self._run_config_sub_collector(
                    sections['docker'].get('containers', [])
                )

        # Collect Proxmox data if Proxmox is present
        if capabilities.is_proxmox:
            sections['proxmox'] = self._run_proxmox_sub_collector()

        # Add more sub-collectors as needed
        # if capabilities.has_zfs:
        #     sections['zfs'] = self._run_zfs_sub_collector()

        return sections

    def _run_docker_sub_collector(self) -> Dict[str, Any]:
        """Run Docker sub-collector"""
        try:
            collector = DockerSubCollector(self.ssh_connector, self.name)
            return collector.collect()
        except Exception as e:
            self.logger.error(f"Docker sub-collector failed: {e}")
            return {'error': str(e)}

    def _run_docker_compose_sub_collector(self, compose_locations: list) -> Dict[str, Any]:
        """Run Docker Compose sub-collector"""
        try:
            collector = DockerComposeSubCollector(
                self.ssh_connector,
                self.name,
                compose_locations
            )
            return collector.collect()
        except Exception as e:
            self.logger.error(f"Docker Compose sub-collector failed: {e}")
            return {'error': str(e)}

    def _run_hardware_sub_collector(self, is_virtualized: bool = False) -> Dict[str, Any]:
        """Run Hardware sub-collector"""
        try:
            collector = HardwareSubCollector(self.ssh_connector, self.name, is_virtualized=is_virtualized)
            return collector.collect()
        except Exception as e:
            self.logger.error(f"Hardware sub-collector failed: {e}")
            return {'error': str(e)}

    def _get_hardware_section_name(self, is_virtualized: bool) -> str:
        """Get the appropriate hardware section name"""
        return "hardware_allocation" if is_virtualized else "hardware"

    def _run_proxmox_sub_collector(self) -> Dict[str, Any]:
        """Run Proxmox sub-collector"""
        try:
            collector = ProxmoxSubCollector(self.ssh_connector, self.name)
            return collector.collect()
        except Exception as e:
            self.logger.error(f"Proxmox sub-collector failed: {e}")
            return {'error': str(e)}

    def _run_config_sub_collector(self, containers: list) -> Dict[str, Any]:
        """Run Configuration sub-collector"""
        try:
            collector = ConfigSubCollector(
                self.ssh_connector,
                self.name,
                service_definitions=self.config.get('service_definitions'),
                services_output_dir=self.config.get('services_output_dir')
            )
            return collector.collect(containers)
        except Exception as e:
            self.logger.error(f"Config sub-collector failed: {e}")
            return {'error': str(e)}

    def _run_system_info_sub_collector(self) -> Dict[str, Any]:
        """Run System Info sub-collector"""
        try:
            collector = SystemInfoSubCollector(self.ssh_connector, self.name)
            return collector.collect()
        except Exception as e:
            self.logger.error(f"System Info sub-collector failed: {e}")
            return {'error': str(e)}

    def _run_network_sub_collector(self) -> Dict[str, Any]:
        """Run Network sub-collector"""
        try:
            collector = NetworkSubCollector(self.ssh_connector, self.name)
            return collector.collect()
        except Exception as e:
            self.logger.error(f"Network sub-collector failed: {e}")
            return {'error': str(e)}

    def _run_resource_usage_sub_collector(self) -> Dict[str, Any]:
        """Run Resource Usage sub-collector"""
        try:
            collector = ResourceUsageSubCollector(self.ssh_connector, self.name)
            return collector.collect()
        except Exception as e:
            self.logger.error(f"Resource Usage sub-collector failed: {e}")
            return {'error': str(e)}

    def _assemble_unified_document(
        self,
        capabilities: SystemCapabilities,
        sections: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Assemble unified system document

        Args:
            capabilities: Detected capabilities
            sections: Collected data sections

        Returns:
            Unified system document
        """
        # Determine primary system type
        primary_type = self._determine_primary_type(capabilities)

        # Build unified document
        document = {
            'system_name': self.name,
            'system_type': primary_type,
            'capabilities': capabilities.to_dict(),
            'sections': sections,
            'collection_timestamp': datetime.now().isoformat(),
            'collection_method': 'unified_collector',
            'collector_version': '1.0.0'
        }

        # Add summary statistics
        document['summary'] = self._generate_summary(sections)

        return document

    def _determine_primary_type(self, capabilities: SystemCapabilities) -> str:
        """
        Determine primary system type from capabilities

        Args:
            capabilities: Detected capabilities

        Returns:
            Primary system type string
        """
        # Priority order for type determination
        if capabilities.is_unraid:
            return "unraid"
        elif capabilities.is_proxmox:
            return "proxmox"
        elif capabilities.is_ubuntu:
            return "ubuntu"
        elif capabilities.is_debian:
            return "debian"
        elif capabilities.os_type != "unknown":
            return capabilities.os_type
        else:
            return "linux"

    def _generate_summary(self, sections: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate summary statistics from collected sections

        Args:
            sections: Collected data sections

        Returns:
            Summary statistics
        """
        summary = {
            'sections_collected': list(sections.keys()),
            'total_sections': len(sections)
        }

        # Add section-specific counts
        if 'docker' in sections and 'containers' in sections['docker']:
            summary['containers_count'] = len(sections['docker']['containers'])

        if 'docker' in sections and 'networks' in sections['docker']:
            summary['docker_networks_count'] = len(sections['docker']['networks'])

        if 'docker_compose' in sections and 'compose_files' in sections['docker_compose']:
            summary['compose_files_count'] = sections['docker_compose']['total_files']
            summary['compose_services_count'] = sections['docker_compose']['total_services']

        if 'configuration_files' in sections:
            summary['config_files_count'] = sections['configuration_files'].get('total_files', 0)
            if 'collection_summary' in sections['configuration_files']:
                summary['services_with_configs'] = sections['configuration_files']['collection_summary'].get('total_services', 0)

        if 'proxmox' in sections:
            summary['vms_count'] = len(sections['proxmox'].get('vms', []))
            summary['lxc_count'] = len(sections['proxmox'].get('lxc_containers', []))

        # Handle both hardware and hardware_allocation sections
        hw_section = sections.get('hardware') or sections.get('hardware_allocation')
        if hw_section:
            cpu = hw_section.get('cpu', {})
            if 'model_name' in cpu:
                summary['cpu_model'] = cpu['model_name']
            if 'threads' in cpu:
                summary['cpu_threads'] = cpu['threads']
            if 'allocated_vcpus' in cpu:
                summary['allocated_vcpus'] = cpu['allocated_vcpus']

            memory = hw_section.get('memory', {})
            if 'total_gb' in memory:
                summary['memory_gb'] = memory['total_gb']
            if 'allocated_gb' in memory:
                summary['memory_gb'] = memory['allocated_gb']

        return summary

    def sanitize_data(self, data: Any) -> Any:
        """
        Unified collector data sanitization.
        Sanitizes sensitive information from all sections.
        """
        if isinstance(data, dict):
            sanitized = {}
            for key, value in data.items():
                # Sanitize sensitive keys
                if any(sensitive in key.lower() for sensitive in [
                    'password', 'secret', 'token', 'key', 'credential'
                ]):
                    if key.lower() in ['ssh_key_path', 'pcie_generation', 'pcie_width']:
                        # These keys are not sensitive
                        sanitized[key] = self.sanitize_data(value)
                    else:
                        sanitized[key] = 'REDACTED'
                else:
                    sanitized[key] = self.sanitize_data(value)
            return sanitized
        elif isinstance(data, list):
            return [self.sanitize_data(item) for item in data]
        else:
            return super().sanitize_data(data)
