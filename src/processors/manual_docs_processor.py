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
            all_entities = {'systems': {}, 'services': {}, 'categories': {}, 'infrastructure': {}}
            all_relationships = []

            for file_path in manual_files:
                try:
                    doc_result = self._process_manual_file(file_path)
                    if doc_result:
                        # Collect documents
                        all_documents.extend(doc_result.get('documents', []))

                        # Collect entities
                        entities = doc_result.get('entities', {})
                        for category, entity_dict in entities.items():
                            if category in all_entities:
                                all_entities[category].update(entity_dict)
                            else:
                                all_entities[category] = entity_dict

                        # Collect relationships
                        all_relationships.extend(doc_result.get('relationships', []))

                except Exception as e:
                    self.logger.error(f"Failed to process {file_path}: {e}")
                    continue

            # Update rag_data.json
            rag_data_file = self._update_rag_data_json(all_documents, all_entities, all_relationships, output_path)

            self.logger.info(f"Manual docs processing completed: {len(all_documents)} documents, {sum(len(e) for e in all_entities.values())} entities, {len(all_relationships)} relationships")

            return ProcessingResult(
                success=True,
                data={
                    'rag_data_file': str(rag_data_file),
                    'files_processed': len(manual_files),
                    'documents_generated': len(all_documents),
                    'entities_generated': sum(len(e) for e in all_entities.values()),
                    'relationships_generated': len(all_relationships),
                    'output_directory': str(output_path)
                },
                metadata={
                    'processor_type': 'manual_docs',
                    'files_processed': len(manual_files),
                    'documents_generated': len(all_documents),
                    'entities_generated': sum(len(e) for e in all_entities.values()),
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
        """Process a single manual documentation JSON file with new structured format"""
        self.logger.debug(f"Processing manual file: {file_path}")

        try:
            # Load JSON content
            with open(file_path, 'r', encoding='utf-8') as f:
                manual_data = json.load(f)

            # Validate new structured format
            if not self._validate_structured_format(manual_data, file_path):
                return None

            # Add processing metadata to each document
            documents = manual_data.get('documents', [])
            for doc in documents:
                if 'metadata' not in doc:
                    doc['metadata'] = {}
                doc['metadata']['processed_at'] = datetime.now().isoformat()
                doc['metadata']['source_file'] = str(file_path.relative_to(self.manual_docs_dir))

                # Validate content length
                try:
                    self.content_validator.validate_document(doc)
                except Exception as e:
                    self.logger.warning(f"Content validation failed for document {doc.get('id', 'unknown')}: {e}")

            return {
                'documents': documents,
                'entities': manual_data.get('entities', {}),
                'relationships': manual_data.get('relationships', [])
            }

        except Exception as e:
            self.logger.error(f"Error processing {file_path}: {e}")
            return None

    def _validate_structured_format(self, manual_data: Dict[str, Any], file_path: Path) -> bool:
        """Validate that the manual doc has required structured format"""
        required_sections = ['documents', 'entities', 'relationships']

        for section in required_sections:
            if section not in manual_data:
                self.logger.error(f"Missing required section '{section}' in {file_path}")
                return False

        # Validate documents section
        documents = manual_data.get('documents', [])
        if not isinstance(documents, list):
            self.logger.error(f"'documents' must be a list in {file_path}")
            return False

        # Validate each document
        required_doc_fields = ['id', 'type', 'title', 'content', 'metadata', 'tags']
        for i, doc in enumerate(documents):
            for field in required_doc_fields:
                if field not in doc:
                    self.logger.error(f"Missing required field '{field}' in document {i} of {file_path}")
                    return False

        # Validate entities section
        entities = manual_data.get('entities', {})
        if not isinstance(entities, dict):
            self.logger.error(f"'entities' must be a dict in {file_path}")
            return False

        # Validate relationships section
        relationships = manual_data.get('relationships', [])
        if not isinstance(relationships, list):
            self.logger.error(f"'relationships' must be a list in {file_path}")
            return False

        self.logger.debug(f"Validated structured format for {file_path}: {len(documents)} docs, {sum(len(e) for e in entities.values())} entities, {len(relationships)} relationships")
        return True


    def _update_rag_data_json(self, documents: List[Dict[str, Any]], entities: Dict[str, Dict[str, Any]],
                              relationships: List[Dict[str, Any]], output_path: Path) -> Path:
        """Update rag_data.json with manual documentation including documents, entities, and relationships"""
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

        # Remove existing manual documents, entities, and relationships
        original_doc_count = len(rag_data.get('documents', []))
        rag_data['documents'] = [
            doc for doc in rag_data.get('documents', [])
            if not doc.get('id', '').startswith('manual_')
        ]
        removed_doc_count = original_doc_count - len(rag_data['documents'])
        if removed_doc_count > 0:
            self.logger.info(f"Removed {removed_doc_count} existing manual documents")

        # Remove existing manual relationships
        original_rel_count = len(rag_data.get('relationships', []))
        rag_data['relationships'] = [
            rel for rel in rag_data.get('relationships', [])
            if not rel.get('id', '').startswith('manual_') and
            not (rel.get('source_id', '').startswith('manual_') or
                 rel.get('target_id', '').startswith('manual_'))
        ]
        removed_rel_count = original_rel_count - len(rag_data['relationships'])
        if removed_rel_count > 0:
            self.logger.info(f"Removed {removed_rel_count} existing manual relationships")

        # Add new manual documents
        rag_data['documents'].extend(documents)
        self.logger.info(f"Added {len(documents)} new manual documents")

        # Update entities
        if entities:
            # Ensure entities structure exists
            if 'entities' not in rag_data:
                rag_data['entities'] = {'systems': {}, 'services': {}, 'categories': {}, 'infrastructure': {}}

            # Merge entities into each category
            for category, entity_dict in entities.items():
                if category not in rag_data['entities']:
                    rag_data['entities'][category] = {}

                # Remove existing manual entities from this category
                keys_to_remove = [
                    key for key in rag_data['entities'][category].keys()
                    if key.startswith('manual_') or
                       (isinstance(rag_data['entities'][category][key], dict) and
                        rag_data['entities'][category][key].get('source') == 'manual')
                ]
                for key in keys_to_remove:
                    del rag_data['entities'][category][key]

                # Add new entities
                rag_data['entities'][category].update(entity_dict)
                self.logger.info(f"Added {len(entity_dict)} entities to category '{category}'")

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

        self.logger.info(f"Updated rag_data.json with {len(documents)} documents, {sum(len(e) for e in entities.values())} entities, {len(relationships)} relationships")
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