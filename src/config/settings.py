# src/config/settings.py
"""
Enhanced configuration management with service collection support.
"""

import os
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, field
import logging


@dataclass
class TemporalCleaningConfig:
    """Temporal data cleaning configuration"""
    default_temporal_fields: List[str] = field(default_factory=list)
    entity_temporal_fields: Dict[str, List[str]] = field(default_factory=dict)
    temporal_patterns: List[str] = field(default_factory=list)
    entity_aliases: Dict[str, List[str]] = field(default_factory=dict)

    def get_fields_for_entity(self, entity_type: str) -> Set[str]:
        """Get all temporal fields for a specific entity type"""
        # Start with default fields
        fields = set(self.default_temporal_fields)

        # Normalize entity type (lowercase)
        entity_type_lower = entity_type.lower()

        # Check for direct match
        if entity_type_lower in self.entity_temporal_fields:
            fields.update(self.entity_temporal_fields[entity_type_lower])
            return fields

        # Check aliases
        for canonical_type, aliases in self.entity_aliases.items():
            if entity_type_lower in [alias.lower() for alias in aliases]:
                if canonical_type in self.entity_temporal_fields:
                    fields.update(self.entity_temporal_fields[canonical_type])
                return fields

        # If no specific fields found, return just defaults
        return fields


@dataclass
class SystemConfig:
    """Configuration for a target system"""
    name: str
    type: str  # 'docker', 'proxmox', 'prometheus', 'grafana', 'system_documentation'
    host: str
    port: int = 22
    username: str = 'root'
    ssh_key_path: Optional[str] = None
    api_endpoint: Optional[str] = None
    api_token_env: Optional[str] = None
    docker_socket: Optional[str] = None
    enabled: bool = True
    timeout: int = 30

    # Service collection settings for Docker hosts
    collect_services: bool = False
    service_definitions: Optional[Dict] = None
    services_output_dir: Optional[str] = None

    # Prometheus/Grafana specific fields
    container_name: Optional[str] = None
    use_container: bool = True
    config_path: Optional[str] = None
    api_token: Optional[str] = None
    api_user: Optional[str] = None
    api_password: Optional[str] = None

    # System documentation specific fields
    system_type: Optional[str] = 'auto'  # 'unraid', 'proxmox', 'ubuntu', 'auto'

    def __post_init__(self):
        """Validate configuration after initialization"""
        if self.type == 'api' and not self.api_endpoint:
            raise ValueError(f"API endpoint required for system {self.name}")

        if self.type in ['docker', 'proxmox', 'unraid', 'system_documentation'] and not self.host:
            raise ValueError(f"Host required for system {self.name}")

        if self.type in ['prometheus', 'grafana'] and not self.container_name and self.use_container:
            raise ValueError(f"Container name required for containerized {self.type} collection")


@dataclass
class ServiceCollectionConfig:
    """Service collection configuration"""
    enabled: bool = True
    output_directory: str = "infrastructure-docs/services"
    service_definitions: Dict[str, Dict] = None

    def __post_init__(self):
        if self.service_definitions is None:
            self.service_definitions = {}


@dataclass
class RAGProcessingConfig:
    """RAG data extraction and processing configuration"""
    enabled: bool = True
    output_directory: str = "rag_output"
    save_intermediate: bool = True
    parallel_processing: bool = True
    max_workers: int = 4
    
    # LLM Configuration
    llm: Dict[str, Any] = field(default_factory=lambda: {
        'type': 'local',  # 'openai', 'local'
        'model': 'llama3.2',
        'batch_size': 5,
        'max_tokens': 150,
        'temperature': 0.1,
        'timeout': 30
    })
    
    # Processor-specific configurations
    container_processor: Dict[str, Any] = field(default_factory=lambda: {
        'enabled': True,
        'enable_llm_tagging': True,
        'cleaning_rules': {
            'container': {'custom_temporal_field_1', 'custom_temporal_field_2'}
        },
        'metadata_config': {},
        'assembly_config': {}
    })
    
    host_processor: Dict[str, Any] = field(default_factory=lambda: {
        'enabled': True,
        'enable_llm_tagging': True,
        'cleaning_rules': {
            'host': {'custom_host_field_1', 'custom_host_field_2'}
        }
    })
    
    service_processor: Dict[str, Any] = field(default_factory=lambda: {
        'enabled': True,
        'enable_llm_tagging': True,
        'cleaning_rules': {
            'service': {'custom_service_field_1', 'custom_service_field_2'}
        }
    })


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
    """Enhanced configuration manager with service collection support"""

    def __init__(self, config_file: str = None):
        self.logger = logging.getLogger('config_manager')

        # Determine config file path
        if config_file:
            self.config_file = Path(config_file)
        else:
            self.config_file = self._find_config_file()

        self.systems: List[SystemConfig] = []
        self.service_collection = ServiceCollectionConfig()
        self.git_config = GitConfig()
        self.collection_config = CollectionConfig()
        self.rag_processing = RAGProcessingConfig()
        self.temporal_cleaning = TemporalCleaningConfig()  # Add this line

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
        """Create a default configuration file with service collection"""
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
                    'collect_services': True,
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
            'service_collection': {
                'enabled': True,
                'output_directory': 'infrastructure-docs/services',
                'service_definitions': {
                    'homepage': {
                        'config_paths': [
                            '/app/config/settings.yaml',
                            '/app/config/services.yaml',
                            '/app/config/widgets.yaml'
                        ],
                        'output_dir': 'homepage'
                    },
                    'grafana': {
                        'config_paths': [
                            '/etc/grafana/grafana.ini',
                            '/etc/grafana/provisioning/dashboards/*.yaml'
                        ],
                        'api_export': True,
                        'output_dir': 'grafana'
                    }
                }
            },
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

            # Load service collection configuration FIRST
            service_data = config_data.get('service_collection', {})
            self.service_collection = ServiceCollectionConfig(**service_data)

            # Load git configuration
            git_data = config_data.get('git', {})
            self.git_config = GitConfig(**git_data)

            # Load collection configuration
            collection_data = config_data.get('collection', {})
            self.collection_config = CollectionConfig(**collection_data)

            # Load RAG processing configuration
            rag_data = config_data.get('rag_processing', {})
            self.rag_processing = RAGProcessingConfig(**rag_data)

            # Load temporal cleaning configuration
            self._load_temporal_cleaning_config()  # Add this line

            # NOW load systems configuration (which depends on service_collection)
            self._load_systems_config(config_data.get('systems', []))

            # Store sanitization rules
            self.sanitization_rules = config_data.get('sanitization', {})

            self.logger.info(f"Loaded configuration for {len(self.systems)} systems")

        except Exception as e:
            self.logger.error(f"Failed to load configuration: {e}")
            raise

    def _load_temporal_cleaning_config(self):
        """Load temporal cleaning configuration from separate file"""
        try:
            # Look for temporal_cleaning.yml in same directory as main config
            temporal_config_file = self.config_file.parent / 'temporal_cleaning.yml'

            # Fallback locations
            if not temporal_config_file.exists():
                fallback_locations = [
                    Path('src/config/temporal_cleaning.yml'),
                    Path('config/temporal_cleaning.yml'),
                    Path('temporal_cleaning.yml')
                ]

                for location in fallback_locations:
                    if location.exists():
                        temporal_config_file = location
                        break
                else:
                    self.logger.warning("Temporal cleaning config not found, using defaults")
                    return

            with open(temporal_config_file, 'r') as f:
                temporal_data = yaml.safe_load(f)

            self.temporal_cleaning = TemporalCleaningConfig(
                default_temporal_fields=temporal_data.get('default_temporal_fields', []),
                entity_temporal_fields=temporal_data.get('entity_temporal_fields', {}),
                temporal_patterns=temporal_data.get('temporal_patterns', []),
                entity_aliases=temporal_data.get('entity_aliases', {})
            )

            self.logger.info(f"Loaded temporal cleaning config from {temporal_config_file}")

        except Exception as e:
            self.logger.warning(f"Failed to load temporal cleaning config: {e}, using defaults")
            self.temporal_cleaning = TemporalCleaningConfig()


    def _load_systems_config(self, systems_data: List[Dict]):
        """Load systems configuration with service collection support"""
        self.systems = []

        for system_data in systems_data:
            try:
                # Handle environment variable substitution for API tokens
                if 'api_token_env' in system_data:
                    env_var = system_data['api_token_env']
                    system_data['api_token'] = os.getenv(env_var)

                # Add service collection settings to Docker systems BEFORE creating SystemConfig
                if system_data.get('type') == 'docker' and system_data.get('collect_services', False):
                    system_data['service_definitions'] = self.service_collection.service_definitions
                    system_data['services_output_dir'] = self.service_collection.output_directory

                # NOW create the SystemConfig object with the updated system_data
                system_config = SystemConfig(**system_data)

                if system_config.enabled:
                    self.systems.append(system_config)

            except Exception as e:
                self.logger.error(f"Invalid system configuration: {e}")
                continue

    def get_systems_by_type(self, system_type: str) -> List[SystemConfig]:
        """Get all systems of a specific type"""
        return [system for system in self.systems if system.type == system_type]

    def get_docker_systems_with_service_collection(self) -> List[SystemConfig]:
        """Get Docker systems that have service collection enabled"""
        return [system for system in self.systems
                if system.type == 'docker' and system.collect_services]

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

            # Validate service collection configuration
            if self.service_collection.enabled:
                if not self.service_collection.service_definitions:
                    self.logger.warning("Service collection enabled but no service definitions provided")

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

        # Validate service collection settings for Docker systems
        if system.type == 'docker' and system.collect_services:
            if not self.service_collection.enabled:
                self.logger.warning(f"Service collection disabled globally but enabled for {system.name}")

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