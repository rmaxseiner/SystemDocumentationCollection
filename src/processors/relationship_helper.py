"""
Relationship Helper
Utilities for creating relationships between entities in the RAG data model.
"""

from datetime import datetime
from typing import Dict, List, Any, Optional


class RelationshipHelper:
    """Helper class for creating entity relationships"""

    # Relationship type mappings (forward -> reverse)
    BIDIRECTIONAL_TYPES = {
        'HOSTED_BY': 'HOSTS',
        'RUNS_ON': 'RUNS',
        'STORES_DATA_ON': 'PROVIDES_STORAGE_FOR',
        'CONNECTS_TO': 'CONNECTS_TO',  # Symmetric
        'USES': 'USED_BY',
        'DEPENDS_ON': 'SUPPORTS',
        'PART_OF': 'CONTAINS',
        'MANAGED_BY': 'MANAGES',
        'STORED_ON': 'STORES',
        'CONFIGURES': 'CONFIGURED_BY',
        'MONITORS': 'MONITORED_BY',
        'PROVIDES_SERVICE': 'PROVIDED_BY',
        'SPECIFIES': 'SPECIFIED_BY'
    }

    @staticmethod
    def create_relationship(
        source_id: str,
        source_type: str,
        target_id: str,
        target_type: str,
        relationship_type: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a single relationship

        Args:
            source_id: ID of source entity
            source_type: Type of source entity
            target_id: ID of target entity
            target_type: Type of target entity
            relationship_type: Type of relationship (e.g., 'HOSTED_BY', 'HOSTS')
            metadata: Optional metadata dict

        Returns:
            Relationship dict
        """
        # Create relationship ID
        rel_id = f"{source_id}_{relationship_type.lower()}_{target_id}"

        # Ensure metadata has created_at
        if metadata is None:
            metadata = {}
        if 'created_at' not in metadata:
            metadata['created_at'] = datetime.now().isoformat()

        return {
            'id': rel_id,
            'type': relationship_type,
            'source_id': source_id,
            'source_type': source_type,
            'target_id': target_id,
            'target_type': target_type,
            'metadata': metadata
        }

    @classmethod
    def create_bidirectional_relationship(
        cls,
        source_id: str,
        source_type: str,
        target_id: str,
        target_type: str,
        forward_type: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Create bidirectional relationship (both forward and reverse)

        Args:
            source_id: ID of source entity
            source_type: Type of source entity
            target_id: ID of target entity
            target_type: Type of target entity
            forward_type: Forward relationship type (e.g., 'HOSTED_BY')
            metadata: Optional metadata dict (shared by both relationships)

        Returns:
            List containing both forward and reverse relationships
        """
        relationships = []

        # Ensure metadata has created_at
        if metadata is None:
            metadata = {}
        if 'created_at' not in metadata:
            metadata['created_at'] = datetime.now().isoformat()

        # Create forward relationship
        forward_rel = cls.create_relationship(
            source_id=source_id,
            source_type=source_type,
            target_id=target_id,
            target_type=target_type,
            relationship_type=forward_type,
            metadata=metadata.copy()
        )
        relationships.append(forward_rel)

        # Create reverse relationship
        reverse_type = cls.BIDIRECTIONAL_TYPES.get(forward_type)
        if reverse_type:
            reverse_rel = cls.create_relationship(
                source_id=target_id,
                source_type=target_type,
                target_id=source_id,
                target_type=source_type,
                relationship_type=reverse_type,
                metadata=metadata.copy()
            )
            relationships.append(reverse_rel)

        return relationships

    @classmethod
    def create_hosted_by_relationship(
        cls,
        virtual_server_id: str,
        virtual_server_type: str,
        physical_server_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Convenience method for HOSTED_BY / HOSTS relationships

        Args:
            virtual_server_id: ID of virtual server/container
            virtual_server_type: Type (usually 'virtual_server')
            physical_server_id: ID of physical host
            metadata: Optional metadata

        Returns:
            List of bidirectional relationships
        """
        return cls.create_bidirectional_relationship(
            source_id=virtual_server_id,
            source_type=virtual_server_type,
            target_id=physical_server_id,
            target_type='physical_server',
            forward_type='HOSTED_BY',
            metadata=metadata
        )
