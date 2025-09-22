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
            documents = []
            entities = {}

            for file_path in manual_files:
                try:
                    doc_result = self._process_manual_file(file_path)
                    if doc_result:
                        documents.append(doc_result['document'])
                        if doc_result.get('entity'):
                            entity_key = doc_result['entity']['key']
                            entities[entity_key] = doc_result['entity']['data']

                except Exception as e:
                    self.logger.error(f"Failed to process {file_path}: {e}")
                    continue

            # Update rag_data.json
            rag_data_file = self._update_rag_data_json(documents, entities, output_path)

            self.logger.info(f"Manual docs processing completed: {len(documents)} documents generated")

            return ProcessingResult(
                success=True,
                data={
                    'rag_data_file': str(rag_data_file),
                    'files_processed': len(manual_files),
                    'documents_generated': len(documents),
                    'entities_generated': len(entities),
                    'output_directory': str(output_path)
                },
                metadata={
                    'processor_type': 'manual_docs',
                    'files_processed': len(manual_files),
                    'documents_generated': len(documents),
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

        # Recursively find JSON files
        manual_files = list(self.manual_docs_dir.glob("**/*.json"))

        self.logger.debug(f"Discovered {len(manual_files)} manual documentation files")
        return manual_files

    def _process_manual_file(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """Process a single manual documentation JSON file"""
        self.logger.debug(f"Processing manual file: {file_path}")

        try:
            # Load JSON content
            with open(file_path, 'r', encoding='utf-8') as f:
                doc_data = json.load(f)

            # Validate required fields
            if not self._validate_document_format(doc_data, file_path):
                return None

            # Add processing metadata
            doc_data['metadata']['processed_at'] = datetime.now().isoformat()
            doc_data['metadata']['source_file'] = str(file_path.relative_to(self.manual_docs_dir))

            # Validate content length
            self.content_validator.validate_document(doc_data)

            # Create entity if applicable
            entity = self._extract_entity_from_document(doc_data)

            result = {
                'document': doc_data
            }

            if entity:
                result['entity'] = entity

            return result

        except Exception as e:
            self.logger.error(f"Error processing {file_path}: {e}")
            return None

    def _validate_document_format(self, doc_data: Dict[str, Any], file_path: Path) -> bool:
        """Validate that the document has required fields"""
        required_fields = ['id', 'type', 'title', 'content', 'metadata', 'tags']

        for field in required_fields:
            if field not in doc_data:
                self.logger.error(f"Missing required field '{field}' in {file_path}")
                return False

        # Validate metadata has required subfields
        metadata = doc_data.get('metadata', {})
        required_metadata = ['document_type']

        for field in required_metadata:
            if field not in metadata:
                self.logger.warning(f"Missing recommended metadata field '{field}' in {file_path}")

        return True

    def _extract_entity_from_document(self, doc_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract entity information from document if applicable"""
        doc_type = doc_data.get('type', '')
        metadata = doc_data.get('metadata', {})

        # Create entities for certain document types
        if doc_type == 'hardware_specification':
            system_name = metadata.get('system_name')
            if system_name:
                return {
                    'key': system_name,
                    'data': {
                        'type': 'physical_system',
                        'hardware_documented': True,
                        'documentation_version': metadata.get('documentation_version'),
                        'last_hardware_update': metadata.get('last_updated'),
                        'status': 'documented'
                    }
                }

        elif doc_type == 'network_topology':
            network_name = metadata.get('network_name', 'global_network')
            return {
                'key': network_name.lower().replace(' ', '_'),
                'data': {
                    'type': 'network_infrastructure',
                    'topology_documented': True,
                    'total_vlans': metadata.get('total_vlans', 0),
                    'equipment_count': metadata.get('core_equipment_count', 0),
                    'documentation_version': metadata.get('documentation_version'),
                    'last_topology_update': metadata.get('last_updated'),
                    'status': 'documented'
                }
            }

        return None

    def _update_rag_data_json(self, documents: List[Dict[str, Any]], entities: Dict[str, Any],
                              output_path: Path) -> Path:
        """Update rag_data.json with manual documentation"""
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

        # Remove existing manual documents (same format we're inserting)
        original_count = len(rag_data.get('documents', []))
        rag_data['documents'] = [
            doc for doc in rag_data.get('documents', [])
            if not doc.get('id', '').startswith('manual_')
        ]
        removed_count = original_count - len(rag_data['documents'])
        if removed_count > 0:
            self.logger.info(f"Removed {removed_count} existing manual documents")

        # Add new manual documents
        rag_data['documents'].extend(documents)
        self.logger.info(f"Added {len(documents)} new manual documents")

        # Update entities
        if entities:
            # Ensure entities structure exists
            if 'entities' not in rag_data:
                rag_data['entities'] = {}
            if 'infrastructure' not in rag_data['entities']:
                rag_data['entities']['infrastructure'] = {}

            # Add/update infrastructure entities
            for entity_key, entity_data in entities.items():
                rag_data['entities']['infrastructure'][entity_key] = entity_data
                self.logger.debug(f"Added/updated infrastructure entity: {entity_key}")

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

        self.logger.info(f"Updated rag_data.json with {len(documents)} manual documents")
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