# src/processors/manual_docs_processor.py
"""
Manual Documentation Processor
Processes manually created infrastructure documentation files and integrates them into RAG data.
Reads JSON-formatted manual documentation files and updates rag_data.json incrementally.
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
import logging
from datetime import datetime

from .base_processor import BaseProcessor, ProcessingResult
from ..utils.content_validator import ContentValidator


class ManualDocsProcessor(BaseProcessor):
    """
    Processes manual documentation JSON files and updates rag_data.json incrementally.
    Handles hardware specifications, network topology, and other infrastructure docs.
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)

        # Configuration
        self.manual_docs_dir = Path(config.get('manual_docs_dir', 'infrastructure-docs/manual'))
        self.output_dir = Path(config.get('output_dir', 'rag_output'))

        # Track processed files to avoid duplicates
        self.processed_files = set()

        # Content validation
        self.content_validator = ContentValidator(
            config.get('max_word_count', 400),
            config.get('min_content_length', 10)
        )

    def validate_config(self) -> bool:
        """Validate processor configuration"""
        if not self.manual_docs_dir:
            self.logger.error("Manual docs directory not configured")
            return False

        self.logger.info("Manual docs processor configuration validated")
        return True

    def process(self, collected_data: Dict[str, Any] = None) -> ProcessingResult:
        """
        Process manual documentation files and update rag_data.json

        Args:
            collected_data: Not used for manual docs (optional for interface compatibility)

        Returns:
            ProcessingResult: Contains processed manual docs results
        """
        try:
            self.logger.info("Starting manual documentation processing")

            # Find manual documentation JSON files
            manual_files = self._discover_manual_files()

            if not manual_files:
                self.logger.warning("No manual documentation files found")
                return ProcessingResult(
                    success=True,
                    data={'files_processed': 0, 'message': 'No manual docs found'},
                    metadata={'processor_type': 'manual_docs'}
                )

            self.logger.info(f"Found {len(manual_files)} manual documentation files")

            # Create output directory
            output_path = self._create_output_directory(str(self.output_dir))

            # Process each manual file
            all_documents = []
            all_relationships = []

            for file_path in manual_files:
                try:
                    doc_result = self._process_manual_file(file_path)
                    if doc_result:
                        # Collect documents
                        all_documents.extend(doc_result.get('documents', []))

                        # Collect relationships
                        all_relationships.extend(doc_result.get('relationships', []))

                except Exception as e:
                    self.logger.error(f"Failed to process {file_path}: {e}")
                    continue

            # Update rag_data.json
            rag_data_file = self._update_rag_data_json(all_documents, all_relationships, output_path)

            self.logger.info(f"Manual docs processing completed: {len(all_documents)} documents, {len(all_relationships)} relationships")

            return ProcessingResult(
                success=True,
                data={
                    'rag_data_file': str(rag_data_file),
                    'files_processed': len(manual_files),
                    'documents_generated': len(all_documents),
                    'relationships_generated': len(all_relationships),
                    'output_directory': str(output_path)
                },
                metadata={
                    'processor_type': 'manual_docs',
                    'files_processed': len(manual_files),
                    'documents_generated': len(all_documents),
                    'relationships_generated': len(all_relationships),
                    'output_directory': str(output_path)
                }
            )

        except Exception as e:
            self.logger.exception("Manual docs processing failed")
            return ProcessingResult(
                success=False,
                error=str(e),
                metadata={'processor_type': 'manual_docs'}
            )

    def _discover_manual_files(self) -> List[Path]:
        """Discover manual documentation JSON files in the configured directory"""
        manual_files = []

        if not self.manual_docs_dir.exists():
            self.logger.warning(f"Manual docs directory does not exist: {self.manual_docs_dir}")
            return manual_files

        # Recursively find JSON files, excluding archive directory
        manual_files = [
            f for f in self.manual_docs_dir.glob("**/*.json")
            if 'archive' not in str(f)
        ]

        self.logger.debug(f"Discovered {len(manual_files)} manual documentation files")
        return manual_files

    def _process_manual_file(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """Process a single manual documentation JSON file with standardized format"""
        self.logger.debug(f"Processing manual file: {file_path}")

        try:
            # Load JSON content
            with open(file_path, 'r', encoding='utf-8') as f:
                manual_data = json.load(f)

            # Validate structured format
            if not self._validate_structured_format(manual_data, file_path):
                return None

            # Get documents and relationships
            documents = manual_data.get('documents', [])
            relationships = manual_data.get('relationships', [])

            # Add processing metadata to each document
            for doc in documents:
                if 'metadata' not in doc:
                    doc['metadata'] = {}
                doc['metadata']['processed_at'] = datetime.now().isoformat()
                doc['metadata']['source_file'] = str(file_path.relative_to(self.manual_docs_dir))
                doc['metadata']['source_type'] = 'manual'

                # Validate content length
                try:
                    self.content_validator.validate_document(doc)
                except Exception as e:
                    self.logger.warning(f"Content validation failed for document {doc.get('id', 'unknown')}: {e}")

            # Add processing metadata to relationships
            for rel in relationships:
                if 'metadata' not in rel:
                    rel['metadata'] = {}
                rel['metadata']['processed_at'] = datetime.now().isoformat()
                rel['metadata']['source_file'] = str(file_path.relative_to(self.manual_docs_dir))
                rel['metadata']['source_type'] = 'manual'

            return {
                'documents': documents,
                'relationships': relationships
            }

        except Exception as e:
            self.logger.error(f"Error processing {file_path}: {e}")
            return None

    def _validate_structured_format(self, manual_data: Dict[str, Any], file_path: Path) -> bool:
        """
        Validate that the manual doc has required structured format.

        Required structure:
        - Root: Only 'documents' and 'relationships' keys allowed
        - Documents: id, type, title, content, metadata, details (no extra fields)
        - Relationships: id, type, source_id, source_type, target_id, target_type (optional: metadata)
        """

        # Validate root keys - only documents and relationships allowed
        allowed_root_keys = {'documents', 'relationships'}
        actual_root_keys = set(manual_data.keys())
        extra_keys = actual_root_keys - allowed_root_keys

        if extra_keys:
            self.logger.error(f"Invalid root keys in {file_path}: {extra_keys}. Only 'documents' and 'relationships' allowed.")
            return False

        # Validate documents section (required)
        if 'documents' not in manual_data:
            self.logger.error(f"Missing required section 'documents' in {file_path}")
            return False

        documents = manual_data['documents']
        if not isinstance(documents, list):
            self.logger.error(f"'documents' must be a list in {file_path}")
            return False

        # Validate each document structure
        required_doc_fields = {'id', 'type', 'title', 'content', 'metadata', 'details'}

        for i, doc in enumerate(documents):
            if not isinstance(doc, dict):
                self.logger.error(f"Document {i} must be a dict in {file_path}")
                return False

            actual_doc_fields = set(doc.keys())

            # Check for missing required fields
            missing_fields = required_doc_fields - actual_doc_fields
            if missing_fields:
                self.logger.error(f"Document {i} in {file_path} missing required fields: {missing_fields}")
                return False

            # Check for extra fields
            extra_fields = actual_doc_fields - required_doc_fields
            if extra_fields:
                self.logger.error(f"Document {i} in {file_path} has invalid extra fields: {extra_fields}")
                return False

        # Validate relationships section (optional)
        if 'relationships' in manual_data:
            relationships = manual_data['relationships']
            if not isinstance(relationships, list):
                self.logger.error(f"'relationships' must be a list in {file_path}")
                return False

            # Validate each relationship structure
            required_rel_fields = {'id', 'type', 'source_id', 'source_type', 'target_id', 'target_type'}
            optional_rel_fields = {'metadata'}
            allowed_rel_fields = required_rel_fields | optional_rel_fields

            for i, rel in enumerate(relationships):
                if not isinstance(rel, dict):
                    self.logger.error(f"Relationship {i} must be a dict in {file_path}")
                    return False

                actual_rel_fields = set(rel.keys())

                # Check for missing required fields
                missing_fields = required_rel_fields - actual_rel_fields
                if missing_fields:
                    self.logger.error(f"Relationship {i} in {file_path} missing required fields: {missing_fields}")
                    return False

                # Check for extra fields
                extra_fields = actual_rel_fields - allowed_rel_fields
                if extra_fields:
                    self.logger.error(f"Relationship {i} in {file_path} has invalid extra fields: {extra_fields}")
                    return False

        self.logger.debug(f"Validation passed for {file_path.name}")
        return True


    def _update_rag_data_json(self, documents: List[Dict[str, Any]],
                              relationships: List[Dict[str, Any]], output_path: Path) -> Path:
        """Update rag_data.json with manual documentation including documents and relationships"""
        rag_data_file = output_path / 'rag_data.json'

        # Load existing rag_data.json or create new structure
        if rag_data_file.exists():
            try:
                with open(rag_data_file, 'r') as f:
                    rag_data = json.load(f)
                self.logger.info("Loaded existing rag_data.json")
            except Exception as e:
                self.logger.warning(f"Failed to load existing rag_data.json: {e}, creating new")
                rag_data = self._create_empty_rag_data()
        else:
            self.logger.info("Creating new rag_data.json")
            rag_data = self._create_empty_rag_data()

        # Remove existing manual documents and relationships
        # Filter by metadata.source_type == 'manual'
        original_doc_count = len(rag_data.get('documents', []))
        rag_data['documents'] = [
            doc for doc in rag_data.get('documents', [])
            if doc.get('metadata', {}).get('source_type') != 'manual'
        ]
        removed_doc_count = original_doc_count - len(rag_data['documents'])
        if removed_doc_count > 0:
            self.logger.info(f"Removed {removed_doc_count} existing manual documents")

        # Remove existing manual relationships (identified by metadata source_type)
        original_rel_count = len(rag_data.get('relationships', []))
        rag_data['relationships'] = [
            rel for rel in rag_data.get('relationships', [])
            if rel.get('metadata', {}).get('source_type') != 'manual'
        ]
        removed_rel_count = original_rel_count - len(rag_data['relationships'])
        if removed_rel_count > 0:
            self.logger.info(f"Removed {removed_rel_count} existing manual relationships")

        # Add new manual documents
        rag_data['documents'].extend(documents)
        self.logger.info(f"Added {len(documents)} new manual documents")

        # Add new relationships
        rag_data['relationships'].extend(relationships)
        self.logger.info(f"Added {len(relationships)} new manual relationships")

        # Update metadata
        rag_data['metadata']['export_timestamp'] = datetime.now().isoformat()

        # Count manual documents
        manual_doc_count = len([
            doc for doc in rag_data['documents']
            if doc.get('id', '').startswith('manual_')
        ])
        rag_data['metadata']['total_manual_documents'] = manual_doc_count

        # Save updated rag_data.json
        with open(rag_data_file, 'w') as f:
            json.dump(rag_data, f, indent=2, default=str)

        self.logger.info(f"Updated rag_data.json with {len(documents)} documents and {len(relationships)} relationships")
        return rag_data_file

    def _create_empty_rag_data(self) -> Dict[str, Any]:
        """Create empty rag_data.json structure"""
        return {
            "metadata": {
                "export_timestamp": datetime.now().isoformat(),
                "total_systems": 0,
                "total_containers": 0,
                "total_vms": 0,
                "total_manual_documents": 0
            },
            "documents": [],
            "entities": {
                "systems": {},
                "services": {},
                "categories": {},
                "infrastructure": {}
            },
            "relationships": []
        }