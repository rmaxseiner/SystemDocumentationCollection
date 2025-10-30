#!/usr/bin/env python3
"""
Relationship Validation Test
Validates relationships in rag_data.json for correctness and consistency.
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Set, Any
from datetime import datetime


class RelationshipValidator:
    """Validates relationships in RAG data"""

    # Valid relationship types and their inverses
    BIDIRECTIONAL_TYPES = {
        'HOSTED_BY': 'HOSTS',
        'HOSTS': 'HOSTED_BY',
        'RUNS_ON': 'RUNS',
        'RUNS': 'RUNS_ON',
        'STORES_DATA_ON': 'PROVIDES_STORAGE_FOR',
        'PROVIDES_STORAGE_FOR': 'STORES_DATA_ON',
        'CONNECTS_TO': 'CONNECTS_TO',  # Symmetric
        'USES': 'USED_BY',
        'USED_BY': 'USES',
        'DEPENDS_ON': 'SUPPORTS',
        'SUPPORTS': 'DEPENDS_ON',
        'PART_OF': 'CONTAINS',
        'CONTAINS': 'PART_OF',
        'MANAGED_BY': 'MANAGES',
        'MANAGES': 'MANAGED_BY'
    }

    def __init__(self, rag_data_path: Path):
        """
        Initialize validator

        Args:
            rag_data_path: Path to rag_data.json
        """
        self.rag_data_path = rag_data_path
        self.errors = []
        self.warnings = []
        self.documents = {}
        self.relationships = []
        self.relationship_index = {}

    def load_data(self) -> bool:
        """Load rag_data.json"""
        if not self.rag_data_path.exists():
            self.errors.append(f"File not found: {self.rag_data_path}")
            return False

        try:
            with open(self.rag_data_path, 'r') as f:
                rag_data = json.load(f)

            # Index documents by ID
            for doc in rag_data.get('documents', []):
                doc_id = doc.get('id')
                if doc_id:
                    self.documents[doc_id] = doc

            # Load relationships
            self.relationships = rag_data.get('relationships', [])

            return True
        except Exception as e:
            self.errors.append(f"Failed to load data: {e}")
            return False

    def validate_all(self) -> bool:
        """Run all validation checks"""
        all_valid = True

        # Validate each relationship structure
        for i, rel in enumerate(self.relationships):
            rel_id = rel.get('id', f'relationship[{i}]')
            all_valid &= self._validate_relationship_structure(rel, rel_id)

        # Build relationship index for bidirectional checking
        self._build_relationship_index()

        # Validate bidirectional pairs
        all_valid &= self._validate_bidirectional_relationships()

        # Validate entity references
        all_valid &= self._validate_entity_references()

        # Check for orphaned relationships
        all_valid &= self._check_orphaned_relationships()

        return all_valid

    def _validate_relationship_structure(self, rel: Dict, rel_id: str) -> bool:
        """Validate relationship has correct structure"""
        is_valid = True

        # Required fields
        required_fields = ['id', 'type', 'source_id', 'source_type', 'target_id', 'target_type', 'metadata']
        for field in required_fields:
            if field not in rel:
                self.errors.append(f"{rel_id}: Missing required field '{field}'")
                is_valid = False

        # Validate field types
        if 'id' in rel and not isinstance(rel['id'], str):
            self.errors.append(f"{rel_id}: Field 'id' must be string")
            is_valid = False

        if 'type' in rel:
            if not isinstance(rel['type'], str):
                self.errors.append(f"{rel_id}: Field 'type' must be string")
                is_valid = False
            elif rel['type'] not in self.BIDIRECTIONAL_TYPES:
                self.warnings.append(f"{rel_id}: Relationship type '{rel['type']}' is not recognized")

        if 'source_id' in rel and not isinstance(rel['source_id'], str):
            self.errors.append(f"{rel_id}: Field 'source_id' must be string")
            is_valid = False

        if 'source_type' in rel and not isinstance(rel['source_type'], str):
            self.errors.append(f"{rel_id}: Field 'source_type' must be string")
            is_valid = False

        if 'target_id' in rel and not isinstance(rel['target_id'], str):
            self.errors.append(f"{rel_id}: Field 'target_id' must be string")
            is_valid = False

        if 'target_type' in rel and not isinstance(rel['target_type'], str):
            self.errors.append(f"{rel_id}: Field 'target_type' must be string")
            is_valid = False

        # Validate metadata
        if 'metadata' in rel:
            if not isinstance(rel['metadata'], dict):
                self.errors.append(f"{rel_id}: Field 'metadata' must be object")
                is_valid = False
            else:
                # Check for created_at
                if 'created_at' not in rel['metadata']:
                    self.errors.append(f"{rel_id}: Metadata missing required field 'created_at'")
                    is_valid = False
                else:
                    # Validate ISO 8601 timestamp
                    created_at = rel['metadata']['created_at']
                    if not isinstance(created_at, str):
                        self.errors.append(f"{rel_id}: metadata.created_at must be string")
                        is_valid = False
                    else:
                        try:
                            datetime.fromisoformat(created_at)
                        except ValueError:
                            self.errors.append(f"{rel_id}: metadata.created_at is not a valid ISO 8601 timestamp")
                            is_valid = False

        # Validate ID format
        if 'id' in rel and 'source_id' in rel and 'target_id' in rel:
            expected_pattern = f"{rel['source_id']}_"
            if not rel['id'].startswith(expected_pattern):
                self.warnings.append(
                    f"{rel_id}: Relationship ID should start with source_id. "
                    f"Expected pattern: '{expected_pattern}...'"
                )

        return is_valid

    def _build_relationship_index(self):
        """Build index of relationships for quick lookup"""
        for rel in self.relationships:
            source_id = rel.get('source_id')
            target_id = rel.get('target_id')
            rel_type = rel.get('type')

            if source_id and target_id and rel_type:
                key = (source_id, target_id, rel_type)
                self.relationship_index[key] = rel

    def _validate_bidirectional_relationships(self) -> bool:
        """Validate that bidirectional relationships have proper pairs"""
        is_valid = True
        checked_pairs = set()

        for rel in self.relationships:
            source_id = rel.get('source_id')
            target_id = rel.get('target_id')
            rel_type = rel.get('type')
            rel_id = rel.get('id', 'unknown')

            if not all([source_id, target_id, rel_type]):
                continue

            # Skip if already checked as reverse
            pair_key = (source_id, target_id, rel_type)
            if pair_key in checked_pairs:
                continue

            # Get expected reverse type
            reverse_type = self.BIDIRECTIONAL_TYPES.get(rel_type)
            if not reverse_type:
                # Not a bidirectional type we know about
                continue

            # Look for reverse relationship
            reverse_key = (target_id, source_id, reverse_type)
            reverse_rel = self.relationship_index.get(reverse_key)

            if not reverse_rel:
                self.errors.append(
                    f"{rel_id}: Missing bidirectional pair. "
                    f"Expected reverse relationship: {target_id} -{reverse_type}-> {source_id}"
                )
                is_valid = False
            else:
                # Mark both as checked
                checked_pairs.add(pair_key)
                checked_pairs.add(reverse_key)

                # Validate timestamps match
                created_at_1 = rel.get('metadata', {}).get('created_at')
                created_at_2 = reverse_rel.get('metadata', {}).get('created_at')

                if created_at_1 != created_at_2:
                    self.warnings.append(
                        f"{rel_id}: Bidirectional pair has mismatched created_at timestamps "
                        f"({created_at_1} vs {created_at_2})"
                    )

        return is_valid

    def _validate_entity_references(self) -> bool:
        """Validate that source and target entities exist"""
        is_valid = True

        for rel in self.relationships:
            source_id = rel.get('source_id')
            target_id = rel.get('target_id')
            source_type = rel.get('source_type')
            target_type = rel.get('target_type')
            rel_id = rel.get('id', 'unknown')

            # Check source exists
            if source_id and source_id not in self.documents:
                self.errors.append(
                    f"{rel_id}: Source entity '{source_id}' does not exist in documents"
                )
                is_valid = False
            elif source_id and source_type:
                # Validate source type matches
                doc_type = self.documents[source_id].get('type')
                if doc_type != source_type:
                    self.errors.append(
                        f"{rel_id}: Source type mismatch. "
                        f"Relationship says '{source_type}', document type is '{doc_type}'"
                    )
                    is_valid = False

            # Check target exists
            if target_id and target_id not in self.documents:
                self.errors.append(
                    f"{rel_id}: Target entity '{target_id}' does not exist in documents"
                )
                is_valid = False
            elif target_id and target_type:
                # Validate target type matches
                doc_type = self.documents[target_id].get('type')
                if doc_type != target_type:
                    self.errors.append(
                        f"{rel_id}: Target type mismatch. "
                        f"Relationship says '{target_type}', document type is '{doc_type}'"
                    )
                    is_valid = False

        return is_valid

    def _check_orphaned_relationships(self) -> bool:
        """Check for relationships pointing to non-existent entities"""
        # This is covered by _validate_entity_references, but we track it separately
        orphaned_sources = set()
        orphaned_targets = set()

        for rel in self.relationships:
            source_id = rel.get('source_id')
            target_id = rel.get('target_id')

            if source_id and source_id not in self.documents:
                orphaned_sources.add(source_id)

            if target_id and target_id not in self.documents:
                orphaned_targets.add(target_id)

        if orphaned_sources or orphaned_targets:
            if orphaned_sources:
                self.warnings.append(
                    f"Found {len(orphaned_sources)} orphaned source references: "
                    f"{', '.join(list(orphaned_sources)[:5])}"
                )
            if orphaned_targets:
                self.warnings.append(
                    f"Found {len(orphaned_targets)} orphaned target references: "
                    f"{', '.join(list(orphaned_targets)[:5])}"
                )
            return False

        return True

    def get_statistics(self) -> Dict[str, Any]:
        """Get relationship statistics"""
        stats = {
            'total_relationships': len(self.relationships),
            'total_documents': len(self.documents),
            'relationship_types': {},
            'bidirectional_pairs': 0
        }

        # Count relationship types
        for rel in self.relationships:
            rel_type = rel.get('type', 'unknown')
            stats['relationship_types'][rel_type] = stats['relationship_types'].get(rel_type, 0) + 1

        # Count bidirectional pairs
        checked = set()
        for rel in self.relationships:
            source_id = rel.get('source_id')
            target_id = rel.get('target_id')
            rel_type = rel.get('type')

            if not all([source_id, target_id, rel_type]):
                continue

            reverse_type = self.BIDIRECTIONAL_TYPES.get(rel_type, '')
            pair_key = tuple(sorted([f"{source_id}_{rel_type}", f"{target_id}_{reverse_type}"]))
            if pair_key not in checked:
                if reverse_type:
                    reverse_key = (target_id, source_id, reverse_type)
                    if reverse_key in self.relationship_index:
                        stats['bidirectional_pairs'] += 1
                        checked.add(pair_key)

        return stats

    def get_report(self) -> str:
        """Generate validation report"""
        report = []
        report.append("=" * 80)
        report.append("Relationship Validation Report")
        report.append("=" * 80)

        # Statistics
        stats = self.get_statistics()
        report.append(f"\nTotal relationships: {stats['total_relationships']}")
        report.append(f"Total documents: {stats['total_documents']}")
        report.append(f"Bidirectional pairs: {stats['bidirectional_pairs']}")

        report.append("\nRelationship types:")
        for rel_type, count in sorted(stats['relationship_types'].items()):
            report.append(f"  {rel_type}: {count}")

        # Validation results
        report.append("\n" + "-" * 80)

        if not self.errors and not self.warnings:
            report.append("\n✅ All relationship validations passed!")
        else:
            if self.errors:
                report.append(f"\n❌ Found {len(self.errors)} ERROR(S):")
                for error in self.errors[:20]:  # Limit to first 20
                    report.append(f"  - {error}")
                if len(self.errors) > 20:
                    report.append(f"  ... and {len(self.errors) - 20} more errors")

            if self.warnings:
                report.append(f"\n⚠️  Found {len(self.warnings)} WARNING(S):")
                for warning in self.warnings[:20]:  # Limit to first 20
                    report.append(f"  - {warning}")
                if len(self.warnings) > 20:
                    report.append(f"  ... and {len(self.warnings) - 20} more warnings")

        report.append("=" * 80)
        return "\n".join(report)


def main():
    """Main test function"""
    # Load rag_data.json
    rag_data_path = Path(__file__).parent.parent / 'rag_output' / 'rag_data.json'

    print(f"Loading relationships from: {rag_data_path}\n")

    # Initialize validator
    validator = RelationshipValidator(rag_data_path)

    # Load data
    if not validator.load_data():
        print("❌ ERROR: Failed to load data")
        print(validator.get_report())
        sys.exit(1)

    print(f"Loaded {len(validator.documents)} documents and {len(validator.relationships)} relationships\n")

    # Run validation
    print("Validating relationships...")
    is_valid = validator.validate_all()

    # Print report
    print("\n" + validator.get_report())

    # Exit with appropriate code
    if is_valid and not validator.errors:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
