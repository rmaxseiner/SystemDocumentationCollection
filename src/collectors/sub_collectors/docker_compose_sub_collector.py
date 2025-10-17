# src/collectors/sub_collectors/docker_compose_sub_collector.py
"""
Docker Compose Sub-Collector
Collects docker-compose.yml files from HOST filesystem (not from inside containers).
This solves the issue where docker-compose files in /root/dockerhome/ were not being collected.
"""

from typing import Dict, Any, List
import yaml
from pathlib import Path
from .base_sub_collector import SubCollector


class DockerComposeSubCollector(SubCollector):
    """
    Collects docker-compose.yml files from host filesystem.

    Key difference from configuration collection in containers:
    - Uses direct SSH commands (cat) on host filesystem
    - Does NOT use 'docker exec' commands
    - Searches common docker-compose locations
    """

    def __init__(self, ssh_connector, system_name: str, compose_locations: List[str] = None):
        """
        Initialize Docker Compose sub-collector

        Args:
            ssh_connector: Connected SSH connector
            system_name: Name of system being collected
            compose_locations: Optional list of specific compose file paths to collect
        """
        super().__init__(ssh_connector, system_name)
        self.compose_locations = compose_locations or []

    def get_section_name(self) -> str:
        return "docker_compose"

    def collect(self) -> Dict[str, Any]:
        """
        Collect docker-compose files from host filesystem

        Returns:
            Dict with:
                - compose_files: List of compose file data
                - total_files: Count of files found
                - total_services: Count of services across all files
        """
        self.log_start()

        compose_files = []
        total_services = 0

        if not self.compose_locations:
            self.logger.warning("No docker-compose file locations provided")
            return {
                'compose_files': [],
                'total_files': 0,
                'total_services': 0
            }

        self.logger.info(f"Collecting {len(self.compose_locations)} docker-compose files")

        for file_path in self.compose_locations:
            try:
                compose_data = self._collect_compose_file(file_path)
                if compose_data:
                    compose_files.append(compose_data)
                    total_services += compose_data.get('service_count', 0)
            except Exception as e:
                self.logger.error(f"Failed to collect {file_path}: {e}")
                # Continue with other files even if one fails

        self.log_end(len(compose_files))

        return {
            'compose_files': compose_files,
            'total_files': len(compose_files),
            'total_services': total_services
        }

    def _collect_compose_file(self, file_path: str) -> Dict[str, Any]:
        """
        Collect a single docker-compose file from host filesystem

        Args:
            file_path: Path to docker-compose file on host

        Returns:
            Dict containing compose file data
        """
        self.logger.debug(f"Reading compose file: {file_path}")

        # Read file content directly from host (NOT via docker exec)
        result = self.ssh.execute_command(
            f"cat {file_path} 2>/dev/null",
            timeout=30,
            log_command=False
        )

        if not result.success:
            self.logger.warning(f"Failed to read {file_path}: {result.error}")
            return None

        if not result.output.strip():
            self.logger.warning(f"Empty file: {file_path}")
            return None

        content = result.output

        # Parse YAML to extract metadata
        services = []
        service_count = 0
        parse_error = None

        try:
            compose_config = yaml.safe_load(content)
            if compose_config and 'services' in compose_config:
                services = list(compose_config['services'].keys())
                service_count = len(services)
        except yaml.YAMLError as e:
            parse_error = str(e)
            self.logger.warning(f"Failed to parse YAML in {file_path}: {e}")

        # Get file metadata
        file_stat = self._get_file_stat(file_path)

        compose_data = {
            'path': file_path,
            'content': content,
            'services': services,
            'service_count': service_count,
            'file_size': len(content),
            'parse_error': parse_error,
            'directory': str(Path(file_path).parent),
            'filename': Path(file_path).name
        }

        # Add file stat if available
        if file_stat:
            compose_data.update(file_stat)

        self.logger.debug(f"Collected {file_path}: {service_count} services")
        return compose_data

    def _get_file_stat(self, file_path: str) -> Dict[str, Any]:
        """
        Get file statistics (modification time, permissions, etc.)

        Args:
            file_path: Path to file

        Returns:
            Dict with file statistics or None if stat fails
        """
        result = self.ssh.execute_command(
            f"stat -c '%Y|%U|%G|%a' {file_path} 2>/dev/null",
            timeout=5,
            log_command=False
        )

        if not result.success or not result.output.strip():
            return None

        try:
            parts = result.output.strip().split('|')
            if len(parts) >= 4:
                return {
                    'last_modified_timestamp': int(parts[0]),
                    'owner': parts[1],
                    'group': parts[2],
                    'permissions': parts[3]
                }
        except (ValueError, IndexError) as e:
            self.logger.debug(f"Failed to parse stat output for {file_path}: {e}")

        return None

    def search_compose_files(self, search_paths: List[str] = None) -> List[str]:
        """
        Search for docker-compose files in common locations.
        This is a helper method that can be called before collect() to discover files.

        Args:
            search_paths: Optional list of directories to search. Uses defaults if None.

        Returns:
            List of file paths found
        """
        if search_paths is None:
            search_paths = [
                '/root/dockerhome',
                '/home/*/dockerhome',
                '/opt/docker',
                '/docker',
                '/srv/docker'
            ]

        found_files = []

        for path in search_paths:
            result = self.ssh.execute_command(
                f"find {path} -type f \\( -name 'docker-compose.yml' -o -name 'docker-compose.yaml' \\) 2>/dev/null",
                timeout=30,
                log_command=False
            )

            if result.success and result.output.strip():
                files = [f.strip() for f in result.output.strip().split('\n') if f.strip()]
                found_files.extend(files)
                self.logger.debug(f"Found {len(files)} compose files in {path}")

        self.logger.info(f"Search complete: found {len(found_files)} docker-compose files")
        return found_files
