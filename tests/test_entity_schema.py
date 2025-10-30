#!/usr/bin/env python3
"""
Generic Entity Schema Validator
Validates entity documents in rag_data.json against YAML schema definitions.

Usage:
    python3 test_entity_schema.py <schema_file.yml>
    python3 test_entity_schema.py schema/physical_server_entity.yml
"""

import json
import yaml
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
import sys


class EntitySchemaValidator:
    """Generic validator that reads schema from YAML"""

    def __init__(self, schema_path: Path):
        """
        Initialize validator with schema file

        Args:
            schema_path: Path to YAML schema file
        """
        self.schema_path = schema_path
        self.schema = self._load_schema()
        self.entity_type = self.schema.get('entity_type')
        self.errors = []
        self.warnings = []

    def _load_schema(self) -> Dict[str, Any]:
        """Load and parse YAML schema file"""
        if not self.schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {self.schema_path}")

        with open(self.schema_path, 'r') as f:
            schema = yaml.safe_load(f)

        return schema

    def validate_document(self, doc: Dict[str, Any], doc_index: int) -> bool:
        """
        Validate a document against the loaded schema

        Args:
            doc: Document to validate
            doc_index: Index in documents array

        Returns:
            True if valid, False otherwise
        """
        doc_id = doc.get('id', f'document[{doc_index}]')
        is_valid = True

        # Validate root level
        if 'root' in self.schema:
            is_valid &= self._validate_fields(doc, self.schema['root'], doc_id, '')

        # Validate tier1
        if 'tier1' in self.schema:
            is_valid &= self._validate_fields(doc, self.schema['tier1'], doc_id, '')

        # Validate tier2
        if 'tier2' in self.schema:
            is_valid &= self._validate_fields(doc, self.schema['tier2'], doc_id, '')

        # Validate tier3
        if 'tier3' in self.schema:
            is_valid &= self._validate_fields(doc, self.schema['tier3'], doc_id, '')

        return is_valid

    def _validate_fields(
        self,
        data: Dict[str, Any],
        schema: Dict[str, Any],
        doc_id: str,
        path: str
    ) -> bool:
        """
        Recursively validate fields against schema

        Args:
            data: Data to validate
            schema: Schema definition for this level
            doc_id: Document ID for error reporting
            path: Current path in document (for nested validation)

        Returns:
            True if valid, False otherwise
        """
        is_valid = True

        for field_name, field_schema in schema.items():
            current_path = f"{path}.{field_name}" if path else field_name
            full_path = f"{doc_id}.{current_path}" if current_path else doc_id

            # Check if field is required
            is_required = field_schema.get('required', False)
            field_value = data.get(field_name)

            if field_value is None:
                if is_required:
                    # Check if nullable
                    is_nullable = field_schema.get('nullable', False)
                    if not is_nullable:
                        self.errors.append(f"{full_path}: Missing required field")
                        is_valid = False
                continue

            # Validate field type
            is_valid &= self._validate_type(field_value, field_schema, full_path)

            # Validate nested fields if this is an object
            if field_schema.get('type') == 'object' and 'fields' in field_schema:
                if isinstance(field_value, dict):
                    is_valid &= self._validate_fields(
                        field_value,
                        field_schema['fields'],
                        doc_id,
                        current_path
                    )

            # Validate array items
            if field_schema.get('type') == 'array' and 'item_schema' in field_schema:
                if isinstance(field_value, list):
                    for i, item in enumerate(field_value):
                        item_path = f"{current_path}[{i}]"
                        item_full_path = f"{doc_id}.{item_path}"

                        item_schema = field_schema['item_schema']
                        if item_schema.get('type') == 'object' and 'fields' in item_schema:
                            if isinstance(item, dict):
                                is_valid &= self._validate_fields(
                                    item,
                                    item_schema['fields'],
                                    doc_id,
                                    item_path
                                )
                            else:
                                self.errors.append(f"{item_full_path}: Must be object")
                                is_valid = False

            # Additional validations
            is_valid &= self._validate_constraints(field_value, field_schema, full_path)

        return is_valid

    def _validate_type(
        self,
        value: Any,
        field_schema: Dict[str, Any],
        path: str
    ) -> bool:
        """Validate value type matches schema"""
        is_valid = True
        expected_type = field_schema.get('type')

        if expected_type is None:
            return True

        # Handle multiple allowed types
        if isinstance(expected_type, list):
            type_match = False
            for t in expected_type:
                if self._check_type(value, t):
                    type_match = True
                    break
            if not type_match:
                type_names = '/'.join(expected_type)
                self.errors.append(f"{path}: Must be {type_names}, got {type(value).__name__}")
                is_valid = False
        else:
            if not self._check_type(value, expected_type):
                self.errors.append(f"{path}: Must be {expected_type}, got {type(value).__name__}")
                is_valid = False

        return is_valid

    def _check_type(self, value: Any, type_name: str) -> bool:
        """Check if value matches type name"""
        type_map = {
            'string': str,
            'integer': int,
            'float': (int, float),
            'boolean': bool,
            'array': list,
            'object': dict
        }

        expected = type_map.get(type_name)
        if expected is None:
            return True

        return isinstance(value, expected)

    def _validate_constraints(
        self,
        value: Any,
        field_schema: Dict[str, Any],
        path: str
    ) -> bool:
        """Validate additional constraints (enum, pattern, min_length, etc.)"""
        is_valid = True

        # Enum validation
        if 'enum' in field_schema:
            if value not in field_schema['enum']:
                enum_values = ', '.join(str(v) for v in field_schema['enum'])
                self.errors.append(f"{path}: Must be one of [{enum_values}], got '{value}'")
                is_valid = False

        # Pattern validation (regex)
        if 'pattern' in field_schema and isinstance(value, str):
            pattern = field_schema['pattern']
            if not re.match(pattern, value):
                self.errors.append(f"{path}: Does not match pattern '{pattern}'")
                is_valid = False

        # Min length validation
        if 'min_length' in field_schema and isinstance(value, str):
            min_len = field_schema['min_length']
            if len(value) < min_len:
                self.warnings.append(f"{path}: Length {len(value)} is less than minimum {min_len}")

        # Format validation
        if 'format' in field_schema and isinstance(value, str):
            format_type = field_schema['format']
            if format_type == 'iso8601':
                # Basic ISO 8601 validation
                if not re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', value):
                    self.errors.append(f"{path}: Not a valid ISO 8601 timestamp")
                    is_valid = False

        return is_valid

    def get_report(self, validated_count: int) -> str:
        """Generate validation report"""
        report = []
        report.append("=" * 80)
        report.append(f"Entity Schema Validation Report: {self.entity_type}")
        report.append(f"Schema: {self.schema_path.name}")
        report.append("=" * 80)
        report.append(f"\nValidated {validated_count} document(s)")

        if not self.errors and not self.warnings:
            report.append("\n✅ All validations passed!")
        else:
            if self.errors:
                report.append(f"\n❌ Found {len(self.errors)} ERROR(S):")
                for error in self.errors:
                    report.append(f"  - {error}")

            if self.warnings:
                report.append(f"\n⚠️  Found {len(self.warnings)} WARNING(S):")
                for warning in self.warnings:
                    report.append(f"  - {warning}")

        report.append("=" * 80)
        return "\n".join(report)


def main():
    """Main test function"""
    if len(sys.argv) < 2:
        print("Usage: python3 test_entity_schema.py <schema_file.yml>")
        print("\nExample:")
        print("  python3 test_entity_schema.py schema/physical_server_entity.yml")
        sys.exit(1)

    # Get schema file path
    schema_path = Path(sys.argv[1])
    if not schema_path.is_absolute():
        # Relative to project root
        project_root = Path(__file__).parent.parent
        schema_path = project_root / schema_path

    print(f"Loading schema: {schema_path}")

    # Initialize validator
    try:
        validator = EntitySchemaValidator(schema_path)
    except FileNotFoundError as e:
        print(f"❌ ERROR: {e}")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"❌ ERROR: Invalid YAML in schema file: {e}")
        sys.exit(1)

    print(f"Entity type: {validator.entity_type}\n")

    # Load rag_data.json
    rag_data_path = Path(__file__).parent.parent / 'rag_output' / 'rag_data.json'

    if not rag_data_path.exists():
        print(f"❌ ERROR: rag_data.json not found at {rag_data_path}")
        sys.exit(1)

    with open(rag_data_path, 'r') as f:
        rag_data = json.load(f)

    # Filter documents by entity type
    matching_docs = [
        (i, doc) for i, doc in enumerate(rag_data.get('documents', []))
        if doc.get('type') == validator.entity_type
    ]

    if not matching_docs:
        print(f"⚠️  No documents found with type '{validator.entity_type}'")
        sys.exit(0)

    print(f"Found {len(matching_docs)} document(s) to validate\n")

    # Validate each document
    all_valid = True

    for doc_index, doc in matching_docs:
        doc_id = doc.get('id', f'document[{doc_index}]')
        print(f"Validating {doc_id}...", end=" ")

        is_valid = validator.validate_document(doc, doc_index)

        # Check if there are errors specific to this document
        doc_errors = [err for err in validator.errors if doc_id in err]

        if is_valid and not doc_errors:
            print("✅ PASSED")
        else:
            print("❌ FAILED")
            all_valid = False

    # Print report
    print("\n" + validator.get_report(len(matching_docs)))

    # Exit with appropriate code
    if all_valid:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
