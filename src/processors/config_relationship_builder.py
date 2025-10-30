# src/processors/config_relationship_builder.py
"""
Configuration Relationship Builder
Helper class for creating configuration file relationships.
"""

from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path

from .relationship_helper import RelationshipHelper


class ConfigRelationshipBuilder:
    """
    Builds relationships for configuration files.
    """

    def __init__(self):
        self.rel_helper = RelationshipHelper()

    def create_storage_relationships(
        self,
        config_id: str,
        host: str,
        file_path: str
    ) -> List[Dict[str, Any]]:
        """
        Create STORED_ON / STORES relationships for configuration file.

        Args:
            config_id: Configuration file entity ID
            host: Hostname where file is stored
            file_path: Full path to file on host

        Returns:
            List of bidirectional relationships
        """
        # Determine host entity ID and type
        # Try virtual_server first, then physical_server
        # The validator will catch if entity doesn't exist
        host_id = f"virtual_server_{host}"
        host_type = "virtual_server"

        # Create bidirectional relationships
        relationships = self.rel_helper.create_bidirectional_relationship(
            source_id=config_id,
            source_type='configuration_file',
            target_id=host_id,
            target_type=host_type,
            forward_type='STORED_ON',
            metadata={
                'file_path': file_path,
                'storage_type': 'local-filesystem'
            }
        )

        return relationships

    def create_configuration_relationships(
        self,
        config_id: str,
        target_id: str,
        target_type: str,
        config_type: str,
        mount_path: Optional[str] = None,
        mount_type: Optional[str] = None,
        readonly: Optional[bool] = None,
        required: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Create CONFIGURES / CONFIGURED_BY relationships.

        Args:
            config_id: Configuration file entity ID
            target_id: Target entity ID (container, service, physical_server, etc.)
            target_type: Target entity type
            config_type: Type of configuration (application_settings, firewall_rules, etc.)
            mount_path: Mount path in container (if applicable)
            mount_type: Mount type (bind, volume, etc.)
            readonly: Whether mount is readonly
            required: Whether config is required

        Returns:
            List of bidirectional relationships
        """
        # Build metadata
        metadata = {
            'config_type': config_type,
            'required': required
        }

        if mount_path:
            metadata['mount_path'] = mount_path
        if mount_type:
            metadata['mount_type'] = mount_type
        if readonly is not None:
            metadata['readonly'] = readonly

        # Create bidirectional relationships
        relationships = self.rel_helper.create_bidirectional_relationship(
            source_id=config_id,
            source_type='configuration_file',
            target_id=target_id,
            target_type=target_type,
            forward_type='CONFIGURES',
            metadata=metadata
        )

        return relationships

    def create_docker_compose_relationships(
        self,
        config_id: str,
        container_names: List[str],
        host: str
    ) -> List[Dict[str, Any]]:
        """
        Create CONFIGURES relationships for docker-compose file to all containers it defines.

        Args:
            config_id: Docker compose file entity ID
            container_names: List of container names defined in compose file
            host: Hostname where containers run

        Returns:
            List of relationships
        """
        relationships = []

        for container_name in container_names:
            container_id = f"container_{host}_{container_name}"

            rels = self.create_configuration_relationships(
                config_id=config_id,
                target_id=container_id,
                target_type='container',
                config_type='docker_compose',
                required=True
            )
            relationships.extend(rels)

        return relationships

    def create_prometheus_monitoring_relationships(
        self,
        config_id: str,
        scrape_targets: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Create MONITORS / MONITORED_BY relationships for prometheus configuration.

        Args:
            config_id: Prometheus config file entity ID
            scrape_targets: List of scrape target information
                [
                    {
                        'job_name': 'node-exporter',
                        'targets': ['host1:9100', 'host2:9100'],
                        'type': 'container' or 'physical_server' or 'virtual_server'
                    }
                ]

        Returns:
            List of relationships
        """
        relationships = []

        # TODO: Parse scrape targets and create MONITORS relationships
        # This needs to map targets to actual entity IDs
        # Placeholder for now

        return relationships

    def create_authentik_relationships(
        self,
        config_id: str,
        config_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Create relationships for Authentik configuration files.

        Args:
            config_id: Authentik config file entity ID
            config_data: Parsed Authentik configuration

        Returns:
            List of relationships
        """
        relationships = []

        # TODO: Parse Authentik config and create appropriate relationships
        # May include AUTHENTICATES, AUTHORIZES, etc.
        # Placeholder for now

        return relationships
