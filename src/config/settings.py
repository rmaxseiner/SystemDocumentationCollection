# src/config/settings.py
"""
Configuration management for the infrastructure documentation collection system.
"""

import os
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import logging


@dataclass
class SystemConfig:
    """Configuration for a target system"""
    name: str
    type: str  # 'docker', 'proxmox', 'unraid', 'api'
    host: str
    port: int = 22
    username: str = 'root'
    ssh_key_path: Optional[str] = None
    api_endpoint: Optional[str] = None
    api_token_env: Optional[str] = None
    docker_socket: Optional[str] = None
    enabled: bool = True
    timeout: int = 30

    def __post_init__(self):
        """Validate configuration after initialization"""
        if self.type == 'api' and not self.api_endpoint:
            raise ValueError(f"API endpoint required for system {self.name}")

        if self.type in ['docker', 'proxmox', 'unraid'] and not self.host:
            raise ValueError(f"Host required for system {self.name}")


@dataclass
class GitConfig:
    """Git repository configuration"""
    local_remote_name: str = 'gitea'
    local_remote_url: str = ''
    offsite_remote_name: str = 'github'
    offsite_remote_url: str = ''
    commit_author_name: str = 'Infrastructure Bot'
    commit_author_email: str = 'infra-bot@home.lab'
    sanitize_for_offsite: bool = True


@dataclass
class CollectionConfig:
    """Collection behavior configuration"""
    parallel_collections: bool = False
    max_workers: int = 3
    retry_attempts: int = 3
    retry_delay: int = 5
    output_format: str = 'json'  # 'json', 'yaml'


class ConfigManager:
    """Manages configuration loading and validation"""

    def __init__(self, config_file: str = None):
        self.logger = logging.getLogger('config_manager')

        # Determine config file path
        if config_file:
            self.config_file = Path(config_file)
        else:
            self.config_file = self._find_config_file()

        self.systems: List[SystemConfig] = []
        self.git_config = GitConfig()
        self.collection_config = CollectionConfig()

        self._load_config()

    def _find_config_file(self) -> Path:
        """Find configuration file in standard locations"""
        possible_locations = [
            Path('config/systems.yml'),
            Path('src/config/systems.yml'),
            Path('/app/config/systems.yml'),
            Path.home() / '.config' / 'infrastructure-docs' / 'systems.yml'
        ]

        for location in possible_locations:
            if location.exists():
                self.logger.info(f"Found config file at {location}")
                return location

        # Create default config if none found
        default_location = Path('config/systems.yml')
        self._create_default_config(default_location)
        return default_location

    def _create_default_config(self, config_path: Path):
        """Create a default configuration file"""
        config_path.parent.mkdir(parents=True, exist_ok=True)

        default_config = {
            'systems': [
                {
                    'name': 'unraid-server',
                    'type': 'docker',
                    'host': '10.0.0.100',
                    'port': 22,
                    'username': 'root',
                    'ssh_key_path': '/app/.ssh/unraid_key',
                    'docker_socket': 'unix:///var/run/docker.sock',
                    'enabled': True
                },
                {
                    'name': 'pve-nuc',
                    'type': 'proxmox',
                    'host': '10.0.0.101',
                    'port': 22,
                    'username': 'root',
                    'ssh_key_path': '/app/.ssh/proxmox_key',
                    'enabled': True
                }
            ],
            'git': {
                'local_remote_name': 'gitea',
                'local_remote_url': 'http://10.20.0.4:3001/ron-maxseiner/SystemDocumentation.git',
                'offsite_remote_name': 'github',
                'offsite_remote_url': 'git@github.com:rmaxseiner/SystemDocumentation.git',
                'commit_author_name': 'Infrastructure Bot',
                'commit_author_email': 'infra-bot@home.lab',
                'sanitize_for_offsite': True
            },
            'collection': {
                'parallel_collections': False,
                'max_workers': 3,
                'retry_attempts': 3,
                'retry_delay': 5,
                'output_format': 'json'
            },
            'sanitization': {
                'ip_addresses': [
                    {'pattern': '10\\.0\\.0\\.\\d+', 'replacement': '10.0.0.XXX'},
                    {'pattern': '192\\.168\\.\\d+\\.\\d+', 'replacement': '192.168.X.XXX'}
                ],
                'credentials': [
                    {'pattern': 'token:\\s*[a-zA-Z0-9_-]+', 'replacement': 'token: REDACTED'},
                    {'pattern': 'password:\\s*\\S+', 'replacement': 'password: REDACTED'}
                ]
            }
        }

        with open(config_path, 'w') as f:
            yaml.dump(default_config, f, default_flow_style=False, indent=2)

        self.logger.info(f"Created default configuration at {config_path}")

    def _load_config(self):
        """Load configuration from file"""
        try:
            with open(self.config_file, 'r') as f:
                config_data = yaml.safe_load(f)

            # Load systems configuration
            self._load_systems_config(config_data.get('systems', []))

            # Load git configuration
            git_data = config_data.get('git', {})
            self.git_config = GitConfig(**git_data)

            # Load collection configuration
            collection_data = config_data.get('collection', {})
            self.collection_config = CollectionConfig(**collection_data)

            # Store sanitization rules
            self.sanitization_rules = config_data.get('sanitization', {})

            self.logger.info(f"Loaded configuration for {len(self.systems)} systems")

        except Exception as e:
            self.logger.error(f"Failed to load configuration: {e}")
            raise

    def _load_systems_config(self, systems_data: List[Dict]):
        """Load systems configuration"""
        self.systems = []

        for system_data in systems_data:
            try:
                # Handle environment variable substitution for API tokens
                if 'api_token_env' in system_data:
                    env_var = system_data['api_token_env']
                    system_data['api_token'] = os.getenv(env_var)

                system_config = SystemConfig(**system_data)
                if system_config.enabled:
                    self.systems.append(system_config)

            except Exception as e:
                self.logger.error(f"Invalid system configuration: {e}")
                continue

    def get_systems_by_type(self, system_type: str) -> List[SystemConfig]:
        """Get all systems of a specific type"""
        return [system for system in self.systems if system.type == system_type]

    def get_system_by_name(self, name: str) -> Optional[SystemConfig]:
        """Get system configuration by name"""
        for system in self.systems:
            if system.name == name:
                return system
        return None

    def get_enabled_systems(self) -> List[SystemConfig]:
        """Get all enabled systems"""
        return [system for system in self.systems if system.enabled]

    def validate_configuration(self) -> bool:
        """Validate the entire configuration"""
        try:
            # Check that we have at least one system
            if not self.systems:
                self.logger.error("No systems configured")
                return False

            # Validate each system configuration
            for system in self.systems:
                if not self._validate_system_config(system):
                    return False

            # Validate git configuration
            if not self.git_config.local_remote_url:
                self.logger.warning("No local git remote configured")

            return True

        except Exception as e:
            self.logger.error(f"Configuration validation failed: {e}")
            return False

    def _validate_system_config(self, system: SystemConfig) -> bool:
        """Validate individual system configuration"""
        # Check SSH key exists for SSH-based systems
        if system.ssh_key_path and not Path(system.ssh_key_path).exists():
            self.logger.warning(f"SSH key not found for {system.name}: {system.ssh_key_path}")

        # Check API token for API-based systems
        if system.type == 'api' and not system.api_token_env:
            self.logger.warning(f"No API token configured for {system.name}")

        return True

    def reload_config(self):
        """Reload configuration from file"""
        self.logger.info("Reloading configuration")
        self._load_config()


# Global configuration instance
config_manager = None


def get_config() -> ConfigManager:
    """Get global configuration manager instance"""
    global config_manager
    if config_manager is None:
        config_manager = ConfigManager()
    return config_manager


def initialize_config(config_file: str = None) -> ConfigManager:
    """Initialize configuration manager with specific config file"""
    global config_manager
    config_manager = ConfigManager(config_file)
    return config_manager