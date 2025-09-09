# src/utils/rag_utils.py
"""
Shared utility functions for RAG data extraction processors.
Provides common functionality for cleaning, metadata extraction, and data assembly.
"""

import re
from typing import Dict, List, Any, Optional, Set, Union
from datetime import datetime
import logging


class TemporalDataCleaner:
    """Utility class for removing temporal and ephemeral data"""
    
    # Default fields to remove across all data types
    DEFAULT_TEMPORAL_FIELDS = {
        'timestamps', 'created_at', 'updated_at', 'last_seen', 'timestamp',
        'status', 'state', 'running', 'stopped', 'health', 'uptime',
        'pid', 'process_id', 'memory_usage', 'cpu_usage', 'disk_usage',
        'logs', 'events', 'metrics', 'stats', 'statistics'
    }
    
    # Container-specific temporal fields
    CONTAINER_TEMPORAL_FIELDS = set() # all fields are in Default_temporal_fields state and created_at
    
    # Host-specific temporal fields  
    HOST_TEMPORAL_FIELDS = {
        'uptime', 'load_average', 'memory.available', 'memory.used', 'memory.free',
        'cpu.usage_percent', 'disk.*.usage_percent', 'disk.*.available',
        'network.*.bytes_sent', 'network.*.bytes_recv', 'network.*.packets_sent',
        'process_list', 'active_connections', 'logged_in_users',
        'system_metrics', 'performance_counters', 'temperature_sensors'
    }
    
    # Service-specific temporal fields
    SERVICE_TEMPORAL_FIELDS = {
        'status', 'active', 'running', 'enabled', 'loaded',
        'main_pid', 'control_pid', 'memory_current', 'cpu_usage_ns',
        'last_trigger', 'next_elapse', 'last_trigger_us', 'passed_us',
        'unit_file_state', 'sub_state', 'load_state', 'active_state',
        'result', 'exec_main_start_timestamp', 'active_enter_timestamp'
    }

    def __init__(self, temporal_config=None, custom_rules: Dict[str, Set[str]] = None):
        """
        Initialize with temporal cleaning configuration

        Args:
            temporal_config: TemporalCleaningConfig instance
            custom_rules: Additional custom cleaning rules by entity type
        """
        self.temporal_config = temporal_config
        self.custom_rules = custom_rules or {}
        self.logger = logging.getLogger('rag_utils.cleaner')

        # Fallback to hardcoded defaults if no config provided
        if not self.temporal_config:
            self.logger.warning("No temporal cleaning config provided, using hardcoded defaults")
            self._use_fallback_config()

    def _use_fallback_config(self):
        """Use hardcoded configuration as fallback"""
        from src.config.settings import TemporalCleaningConfig

        self.temporal_config = TemporalCleaningConfig(
            default_temporal_fields=[
                'timestamps', 'created_at', 'updated_at', 'last_seen', 'timestamp',
                'status', 'state', 'running', 'stopped', 'health', 'uptime',
                'pid', 'process_id', 'memory_usage', 'cpu_usage', 'disk_usage',
                'logs', 'events', 'metrics', 'stats', 'statistics'
            ],
            entity_temporal_fields={
                'container': [],  # Keep container config
                'host': [
                    'uptime', 'load_average', 'memory.available', 'memory.used', 'memory.free',
                    'cpu.usage_percent', 'disk.*.usage_percent', 'disk.*.available',
                    'network.*.bytes_sent', 'network.*.bytes_recv', 'network.*.packets_sent',
                    'process_list', 'active_connections', 'logged_in_users',
                    'system_metrics', 'performance_counters', 'temperature_sensors'
                ],
                'service': [
                    'active', 'enabled', 'loaded', 'main_pid', 'control_pid',
                    'memory_current', 'cpu_usage_ns', 'last_trigger', 'next_elapse',
                    'last_trigger_us', 'passed_us', 'unit_file_state', 'sub_state',
                    'load_state', 'active_state', 'result', 'exec_main_start_timestamp',
                    'active_enter_timestamp'
                ]
            },
            temporal_patterns=[
                '_at$', '_timestamp$', '_time$', '_date$',
                '^last_', '^current_', '^active_', '^running_',
                '_usage$', '_percent$', '_bytes$', '_count$'
            ],
            entity_aliases={
                'container': ['docker_container', 'docker', 'containers'],
                'host': ['server', 'system', 'machine', 'node'],
                'service': ['systemd_service', 'daemon', 'process']
            }
        )

    def clean_data(self, data: Dict[str, Any], data_type: str) -> Dict[str, Any]:
        """Clean temporal data based on data type using configuration"""
        if not isinstance(data, dict):
            return data

        # Get fields to remove for this data type
        fields_to_remove = self._get_removal_fields(data_type)

        # Create cleaned copy
        cleaned = self._recursive_clean(data.copy(), fields_to_remove)

        removed_count = len(data) - len(cleaned)
        self.logger.debug(f"Cleaned {data_type} data: removed {removed_count} top-level fields")

        return cleaned

    def _get_removal_fields(self, data_type: str) -> Set[str]:
        """Get set of fields to remove for given data type using configuration"""
        # Get configured fields for this entity type
        fields = self.temporal_config.get_fields_for_entity(data_type)

        # Add custom rules
        if data_type in self.custom_rules:
            fields.update(self.custom_rules[data_type])

        self.logger.debug(f"Temporal fields for {data_type}: {len(fields)} total")
        return fields

    def _recursive_clean(self, obj: Any, fields_to_remove: Set[str]) -> Any:
        """Recursively clean object, removing specified fields"""
        if isinstance(obj, dict):
            cleaned = {}
            for key, value in obj.items():
                # Skip if key matches removal patterns
                if self._should_remove_field(key, fields_to_remove):
                    self.logger.debug(f"Removing field: {key}")
                    continue

                # Recursively clean the value
                cleaned[key] = self._recursive_clean(value, fields_to_remove)

            return cleaned

        elif isinstance(obj, list):
            return [self._recursive_clean(item, fields_to_remove) for item in obj]

        else:
            return obj

    def _should_remove_field(self, field_name: str, fields_to_remove: Set[str]) -> bool:
        """Check if field should be removed based on configured patterns"""
        field_lower = field_name.lower()

        # Direct match
        if field_lower in fields_to_remove:
            return True

        # Pattern matching for nested fields (e.g., "network_settings.ports")
        for pattern in fields_to_remove:
            if '*' in pattern:
                # Convert pattern to regex
                regex_pattern = pattern.replace('*', '[^.]*')
                if re.match(regex_pattern, field_lower):
                    return True
            elif '.' in pattern and '.' in field_name:
                # Nested field matching
                if field_lower.startswith(pattern.split('.')[0]):
                    return True

        # Check configured temporal patterns
        for pattern in self.temporal_config.temporal_patterns:
            if re.search(pattern, field_lower):
                return True

        return False

class MetadataExtractor:
    """Utility class for extracting structured metadata and relationships"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.logger = logging.getLogger('rag_utils.metadata')
    
    def extract_metadata(self, data: Dict[str, Any], data_type: str, entity_id: str) -> Dict[str, Any]:
        """Extract structured metadata from cleaned data"""
        metadata = {
            'entity_id': entity_id,
            'entity_type': data_type,
            'extraction_timestamp': datetime.now().isoformat(),
            'properties': {},
            'relationships': {}
        }
        
        # Extract type-specific metadata
        if data_type == 'container':
            metadata.update(self._extract_container_metadata(data, entity_id))
        elif data_type == 'host':
            metadata.update(self._extract_host_metadata(data, entity_id))
        elif data_type == 'service':
            metadata.update(self._extract_service_metadata(data, entity_id))
        
        return metadata

    def _extract_container_metadata(self, data: Dict[str, Any], entity_id: str) -> Dict[str, Any]:
        """Extract metadata specific to containers"""
        properties = {}
        relationships = {
            'runs_on': [],
            'depends_on': [],
            'provides_to': [],
            'config_files': [],
            'networks': [],
            'volumes': []
        }

        # Basic container properties
        properties.update({
            'name': data.get('name', entity_id),
            'image': data.get('image'),
            'command': data.get('command'),
            'working_dir': data.get('working_dir'),
            'user': data.get('user'),
            'hostname': data.get('hostname')
        })

        # Environment variables (handle list format from Docker)
        env_data = data.get('environment', [])
        env_vars = {}
        env_keys = []

        if env_data and isinstance(env_data, list):
            # Convert Docker's list format ["KEY=value"] to dict for processing
            for env_item in env_data:
                if isinstance(env_item, str) and '=' in env_item:
                    key, value = env_item.split('=', 1)
                    env_vars[key] = value
                    env_keys.append(key)
                elif isinstance(env_item, str):
                    # Handle case where there's no = (shouldn't happen but be safe)
                    env_keys.append(env_item)

            properties['environment_keys'] = env_keys

            # Look for service references in env vars
            relationships['depends_on'].extend(self._extract_service_references_from_env(env_vars))

        elif env_data and isinstance(env_data, dict):
            # Handle dict format (if it ever comes in that way)
            env_vars = env_data
            properties['environment_keys'] = list(env_vars.keys())
            relationships['depends_on'].extend(self._extract_service_references_from_env(env_vars))

        # Rest of the method stays the same...
        # Labels and annotations
        labels = data.get('labels', {})
        if labels:
            properties['labels'] = labels
            # Extract compose project info
            if 'com.docker.compose.project' in labels:
                relationships['system_component'] = labels['com.docker.compose.project']
            # Extract service dependencies from labels
            relationships['depends_on'].extend(self._extract_dependencies_from_labels(labels))

        # Network information
        networks = data.get('networks', [])
        if networks:
            if isinstance(networks, list):
                relationships['networks'] = networks
            elif isinstance(networks, dict):
                relationships['networks'] = list(networks.keys())
            properties['network_mode'] = data.get('network_mode')

        # Port mappings (configuration, not runtime)
        ports = data.get('ports', {})
        if ports:
            exposed_ports = [port for port in ports.keys() if port]
            properties['exposed_ports'] = exposed_ports

        # Volume mounts (persistent configuration)
        mounts = data.get('mounts', [])
        if mounts:
            bind_mounts = []
            volumes = []
            for mount in mounts:
                if mount.get('type') == 'bind':
                    bind_mounts.append(mount.get('destination'))
                elif mount.get('type') == 'volume':
                    volumes.append(mount.get('source'))

            if bind_mounts:
                properties['bind_mounts'] = bind_mounts
            if volumes:
                relationships['volumes'] = volumes

        # Host relationship (inferred from system context)
        if '_system' in data:
            relationships['runs_on'] = [data['_system']]

        return {
            'properties': {k: v for k, v in properties.items() if v is not None},
            'relationships': {k: v for k, v in relationships.items() if v}
        }
    
    def _extract_host_metadata(self, data: Dict[str, Any], entity_id: str) -> Dict[str, Any]:
        """Extract metadata specific to hosts"""
        properties = {}
        relationships = {
            'hosts': [],  # What this host runs
            'networks': [],
            'storage': []
        }
        
        # System information
        system_info = data.get('system_overview', {})
        if system_info:
            properties.update({
                'hostname': system_info.get('hostname'),
                'os': system_info.get('os'),
                'architecture': system_info.get('architecture'),
                'kernel': system_info.get('kernel')
            })
        
        # Hardware profile (static specs, not current usage)
        hardware = data.get('hardware_profile', {})
        if hardware:
            cpu_info = hardware.get('cpu', {})
            memory_info = hardware.get('memory', {})
            
            properties.update({
                'cpu_model': cpu_info.get('model_name'),
                'cpu_cores': cpu_info.get('cores'),
                'memory_total_gb': memory_info.get('total_gb'),
                'memory_type': memory_info.get('type')
            })
        
        # Network configuration (static config, not current usage)
        network_config = data.get('network_configuration', {})
        if network_config:
            interfaces = network_config.get('interfaces', {})
            relationships['networks'] = list(interfaces.keys())
            properties['network_interfaces'] = len(interfaces)
        
        # Storage configuration
        storage_config = data.get('storage_configuration', {})
        if storage_config:
            filesystems = storage_config.get('filesystems', {})
            relationships['storage'] = list(filesystems.keys())
            properties['storage_devices'] = len(filesystems)
        
        return {
            'properties': {k: v for k, v in properties.items() if v is not None},
            'relationships': {k: v for k, v in relationships.items() if v}
        }
    
    def _extract_service_metadata(self, data: Dict[str, Any], entity_id: str) -> Dict[str, Any]:
        """Extract metadata specific to services"""
        properties = {}
        relationships = {
            'runs_on': [],
            'depends_on': [],
            'config_files': []
        }
        
        # Basic service properties
        properties.update({
            'name': data.get('name', entity_id),
            'type': data.get('type'),
            'description': data.get('description'),
            'exec_start': data.get('exec_start')
        })
        
        # Service dependencies
        if 'wants' in data:
            relationships['depends_on'].extend(data['wants'])
        if 'requires' in data:
            relationships['depends_on'].extend(data['requires'])
        if 'after' in data:
            relationships['depends_on'].extend(data['after'])
        
        # Configuration files
        if 'unit_file_path' in data:
            relationships['config_files'].append(data['unit_file_path'])
        
        return {
            'properties': {k: v for k, v in properties.items() if v is not None},
            'relationships': {k: v for k, v in relationships.items() if v}
        }
    
    def _extract_service_references_from_env(self, env_vars: Dict[str, str]) -> List[str]:
        """Extract service references from environment variables"""
        references = []
        
        for key, value in env_vars.items():
            # Look for service hostnames or references
            if isinstance(value, str):
                # Common patterns: SERVICE_HOST, SERVICE_URL, etc.
                if '_HOST' in key or '_URL' in key or '_ENDPOINT' in key:
                    # Extract hostname from URL or direct reference
                    hostname = self._extract_hostname_from_value(value)
                    if hostname and hostname not in references:
                        references.append(hostname)
        
        return references
    
    def _extract_dependencies_from_labels(self, labels: Dict[str, str]) -> List[str]:
        """Extract service dependencies from Docker labels"""
        dependencies = []
        
        # Docker Compose dependencies
        if 'com.docker.compose.depends_on' in labels:
            deps = labels['com.docker.compose.depends_on'].split(',')
            dependencies.extend([dep.strip() for dep in deps if dep.strip()])
        
        # Traefik backend references
        for label, value in labels.items():
            if 'traefik' in label.lower() and 'backend' in label.lower():
                if value not in dependencies:
                    dependencies.append(value)
        
        return dependencies
    
    def _extract_hostname_from_value(self, value: str) -> Optional[str]:
        """Extract hostname from URL or connection string"""
        if not value:
            return None
        
        # Handle URLs
        if '://' in value:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(value)
                return parsed.hostname
            except:
                return None
        
        # Handle direct hostname references
        if '.' in value and not value.startswith('/'):
            parts = value.split(':')[0]  # Remove port
            if parts and not parts.startswith('/'):
                return parts
        
        return None


class RAGDataAssembler:
    """Utility class for assembling final RAG data structure"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.logger = logging.getLogger('rag_utils.assembler')

    def assemble_rag_entity(self,
                            entity_id: str,
                            entity_type: str,
                            cleaned_data: Dict[str, Any],
                            metadata: Dict[str, Any],
                            tags: Union[Dict[str, str], List[str]]) -> Dict[str, Any]:
        """Assemble final RAG entity structure"""

        # Generate human-readable title
        title = self._generate_title(entity_id, entity_type, metadata, tags)

        # Generate detailed content description
        content = self._generate_content(entity_id, entity_type, cleaned_data, metadata, tags)

        # Prepare final tags (combination of semantic tags and metadata)
        final_tags = self._prepare_tags(tags, metadata)

        rag_entity = {
            'id': entity_id,
            'type': entity_type,
            'title': title,
            'content': content,
            'metadata': {
                'entity_properties': metadata.get('properties', {}),
                'relationships': metadata.get('relationships', {}),
                'extraction_timestamp': metadata.get('extraction_timestamp'),
                'raw_data_summary': self._summarize_raw_data(cleaned_data)
            },
            'tags': final_tags
        }

        return rag_entity
    
    def _generate_title(self, entity_id: str, entity_type: str, metadata: Dict, tags: Dict) -> str:
        """Generate human-readable title for the entity"""
        properties = metadata.get('properties', {})
        
        # Try to create a descriptive title
        if entity_type == 'container':
            name = properties.get('name', entity_id)
            image = properties.get('image', '')
            if image:
                service_name = image.split('/')[-1].split(':')[0]
                return f"{name} ({service_name} container)"
            return f"{name} (container)"
        
        elif entity_type == 'host':
            hostname = properties.get('hostname', entity_id)
            os_info = properties.get('os', '')
            if os_info:
                return f"{hostname} ({os_info} host)"
            return f"{hostname} (host)"
        
        elif entity_type == 'service':
            name = properties.get('name', entity_id)
            service_type = properties.get('type', '')
            if service_type:
                return f"{name} ({service_type} service)"
            return f"{name} (service)"
        
        return f"{entity_id} ({entity_type})"
    
    def _generate_content(self, entity_id: str, entity_type: str, 
                         cleaned_data: Dict, metadata: Dict, tags: Dict) -> str:
        """Generate detailed content description"""
        properties = metadata.get('properties', {})
        relationships = metadata.get('relationships', {})
        
        content_parts = []
        
        # Add entity description
        if entity_type == 'container':
            content_parts.append(self._describe_container(entity_id, properties, relationships, tags))
        elif entity_type == 'host':
            content_parts.append(self._describe_host(entity_id, properties, relationships, tags))
        elif entity_type == 'service':
            content_parts.append(self._describe_service(entity_id, properties, relationships, tags))
        
        # Add relationship information
        if relationships:
            content_parts.append("\\nRelationships:")
            for rel_type, rel_values in relationships.items():
                if rel_values:
                    content_parts.append(f"- {rel_type.replace('_', ' ')}: {', '.join(rel_values)}")
        
        # Add configuration summary
        config_summary = self._summarize_configuration(cleaned_data, entity_type)
        if config_summary:
            content_parts.append(f"\\nConfiguration: {config_summary}")
        
        return "\\n".join(content_parts)
    
    def _describe_container(self, entity_id: str, properties: Dict, relationships: Dict, tags: Dict) -> str:
        """Generate container description"""
        name = properties.get('name', entity_id)
        image = properties.get('image', 'unknown')
        
        description = f"{name} is a containerized service running the {image} image."
        
        # Add purpose from tags
        if 'problem_solved' in tags:
            description += f" It provides {tags['problem_solved']} functionality"
        if 'infrastructure_role' in tags:
            description += f" and serves as {tags['infrastructure_role']} in the infrastructure"
        
        description += "."
        
        # Add system context
        if 'system_component' in tags:
            description += f" It is part of the {tags['system_component']} system."
        
        return description
    
    def _describe_host(self, entity_id: str, properties: Dict, relationships: Dict, tags: Dict) -> str:
        """Generate host description"""
        hostname = properties.get('hostname', entity_id)
        os_info = properties.get('os', 'unknown OS')
        
        description = f"{hostname} is a {os_info} host system."
        
        # Add hardware info
        cpu_model = properties.get('cpu_model', '')
        memory_gb = properties.get('memory_total_gb', '')
        if cpu_model:
            description += f" It runs on {cpu_model}"
        if memory_gb:
            description += f" with {memory_gb}GB of memory"
        
        description += "."
        
        return description
    
    def _describe_service(self, entity_id: str, properties: Dict, relationships: Dict, tags: Dict) -> str:
        """Generate service description"""
        name = properties.get('name', entity_id)
        service_type = properties.get('type', 'system service')
        
        description = f"{name} is a {service_type}"
        
        # Add purpose from tags
        if 'problem_solved' in tags:
            description += f" that handles {tags['problem_solved']}"
        
        description += "."
        
        return description
    
    def _summarize_configuration(self, data: Dict, entity_type: str) -> str:
        """Create a brief configuration summary"""
        if not data:
            return ""
        
        summary_parts = []
        
        if entity_type == 'container':
            if 'environment' in data and data['environment']:
                summary_parts.append(f"{len(data['environment'])} environment variables")
            if 'ports' in data and data['ports']:
                summary_parts.append(f"exposes {len(data['ports'])} ports")
            if 'volumes' in data and data['volumes']:
                summary_parts.append(f"uses {len(data['volumes'])} volumes")
        
        return ", ".join(summary_parts) if summary_parts else "minimal configuration"

    def _prepare_tags(self, llm_tags: Union[Dict[str, str], List[str]], metadata: Dict) -> List[str]:
        """Combine LLM tags with metadata-derived tags"""
        all_tags = []

        # Add LLM semantic tags (handle both dict and list formats)
        if isinstance(llm_tags, dict):
            for category, tag in llm_tags.items():
                if tag and tag.lower() != 'none':
                    all_tags.append(tag.lower())
        elif isinstance(llm_tags, list):
            for tag in llm_tags:
                if tag and tag.lower() != 'none':
                    all_tags.append(tag.lower())

        # Add entity type
        entity_type = metadata.get('entity_type')
        if entity_type:
            all_tags.append(entity_type)

        # Add technology tags from properties
        properties = metadata.get('properties', {})
        if 'image' in properties:
            # Extract technology from image name
            image = properties['image']
            if '/' in image:
                tech = image.split('/')[-1].split(':')[0]
                all_tags.append(tech.lower())

        # Remove duplicates and return
        return list(set(all_tags))
    
    def _summarize_raw_data(self, data: Dict) -> Dict[str, Any]:
        """Create summary of raw data for metadata"""
        if not data:
            return {}
        
        return {
            'field_count': len(data),
            'has_nested_data': any(isinstance(v, dict) for v in data.values()),
            'has_arrays': any(isinstance(v, list) for v in data.values()),
            'top_level_keys': list(data.keys())[:10]  # First 10 keys as sample
        }