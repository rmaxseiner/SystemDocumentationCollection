# src/processors/main_processor.py
"""
Main Unified Processor
Orchestrates processing of unified collector output files.
Runs sub-processors for each section and aggregates results into rag_data.json.
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

from .base_processor import BaseProcessor, ProcessingResult


class MainProcessor(BaseProcessor):
    """
    Main processor that coordinates sub-processors for unified collector output.

    Architecture:
    1. Loops through *_unified.json files in collected_data/
    2. For each system, runs applicable sub-processors based on sections present
    3. Aggregates all documents into rag_data.json
    4. Runs post-processing (service grouping) after all systems are processed
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)

        # Configuration
        self.collected_data_dir = Path(config.get('collected_data_dir', 'collected_data'))
        self.output_dir = Path(config.get('output_dir', 'rag_output'))
        self.enable_llm_tagging = config.get('enable_llm_tagging', True)

        # Sub-processor classes will be registered here
        # Maps section_name -> SubProcessor class
        self.sub_processor_classes = {}

        # Store configuration to pass to sub-processors
        self.sub_processor_config = config

        # Store all documents for aggregation
        self.all_documents = []

        # Track which systems we're processing (for de-duplication)
        self.processed_systems = set()

    def validate_config(self) -> bool:
        """Validate processor configuration"""
        try:
            if not self.collected_data_dir.exists():
                self.logger.error(f"Collected data directory does not exist: {self.collected_data_dir}")
                return False

            if not self.output_dir:
                self.logger.error("Output directory not configured")
                return False

            self.logger.info("Main processor configuration validated")
            return True

        except Exception as e:
            self.logger.error(f"Configuration validation failed: {e}")
            return False

    def register_sub_processor_class(self, section_name: str, sub_processor_class, append: bool = False):
        """
        Register a sub-processor class for a specific section.
        Class will be instantiated per-system with the appropriate system_name.

        Args:
            section_name: Name of the section (e.g., 'docker', 'hardware')
            sub_processor_class: SubProcessor class (not instance)
            append: If True, append to existing processors for this section (allows multiple processors per section)
        """
        if append and section_name in self.sub_processor_classes:
            # Ensure it's a list
            if not isinstance(self.sub_processor_classes[section_name], list):
                self.sub_processor_classes[section_name] = [self.sub_processor_classes[section_name]]
            # Append new processor
            self.sub_processor_classes[section_name].append(sub_processor_class)
            self.logger.info(f"Appended sub-processor class {sub_processor_class.__name__} for section: {section_name}")
        else:
            self.sub_processor_classes[section_name] = sub_processor_class
            self.logger.info(f"Registered sub-processor class {sub_processor_class.__name__} for section: {section_name}")

    def process(self, collected_data: Dict[str, Any]) -> ProcessingResult:
        """
        Process all unified collector output files

        Args:
            collected_data: Not used - MainProcessor reads from files directly

        Returns:
            ProcessingResult with aggregated documents
        """
        try:
            self.logger.info("Starting unified processing pipeline")

            # Create output directory
            output_path = self._create_output_directory(str(self.output_dir))

            # Find all unified collection files
            unified_files = self._find_unified_files()

            if not unified_files:
                self.logger.warning("No unified collection files found")
                return ProcessingResult(
                    success=True,
                    data={'systems_processed': 0, 'message': 'No unified files to process'},
                    metadata={'processor_type': 'main_unified'}
                )

            self.logger.info(f"Found {len(unified_files)} unified collection files")

            # Reset document aggregation
            self.all_documents = []
            self.processed_systems = set()

            # Process each system and track system names
            systems_processed = 0
            for unified_file in unified_files:
                try:
                    system_name, system_documents = self._process_system_file(unified_file)
                    self.all_documents.extend(system_documents)
                    self.processed_systems.add(system_name)
                    systems_processed += 1
                except Exception as e:
                    self.logger.error(f"Failed to process {unified_file.name}: {e}")
                    continue

            # Post-processing: Service grouping (will be implemented later)
            # self._run_service_grouping()

            # Save aggregated results
            rag_data_file = self._save_rag_data_json(output_path)

            self.logger.info(f"Processing completed: {systems_processed} systems, {len(self.all_documents)} documents")

            return ProcessingResult(
                success=True,
                data={
                    'rag_data_file': str(rag_data_file),
                    'systems_processed': systems_processed,
                    'documents_generated': len(self.all_documents),
                    'output_directory': str(output_path)
                },
                metadata={
                    'processor_type': 'main_unified',
                    'systems_processed': systems_processed,
                    'documents_generated': len(self.all_documents)
                }
            )

        except Exception as e:
            self.logger.exception("Main processor failed")
            return ProcessingResult(
                success=False,
                error=str(e),
                metadata={'processor_type': 'main_unified'}
            )

    def _find_unified_files(self) -> List[Path]:
        """Find all *_unified.json files in collected_data directory"""
        unified_files = list(self.collected_data_dir.glob('*_unified.json'))
        self.logger.info(f"Found {len(unified_files)} unified files in {self.collected_data_dir}")
        return unified_files

    def _process_system_file(self, unified_file: Path) -> tuple[str, List[Dict[str, Any]]]:
        """
        Process a single unified collection file

        Args:
            unified_file: Path to *_unified.json file

        Returns:
            Tuple of (system_name, list of RAG documents)
        """
        self.logger.info(f"Processing unified file: {unified_file.name}")

        # Load unified data
        with open(unified_file, 'r') as f:
            unified_data = json.load(f)

        # Extract system info
        if 'data' in unified_data:
            # Wrapped in collection result format
            system_data = unified_data['data']
        else:
            # Direct unified format
            system_data = unified_data

        system_name = system_data.get('system_name', unified_file.stem.replace('_unified', ''))
        sections = system_data.get('sections', {})

        self.logger.info(f"Processing system '{system_name}' with {len(sections)} sections")

        # Process each section with registered sub-processors
        system_documents = []

        for section_name, section_data in sections.items():
            # Get list of sub-processors for this section (may be multiple)
            sub_processor_classes = self.sub_processor_classes.get(section_name, [])

            # Handle both single class and list of classes
            if not isinstance(sub_processor_classes, list):
                sub_processor_classes = [sub_processor_classes]

            if sub_processor_classes:
                self.logger.info(f"Processing section '{section_name}' for {system_name} with {len(sub_processor_classes)} sub-processor(s)")

                for sub_processor_class in sub_processor_classes:
                    try:
                        # Instantiate sub-processor with system-specific name
                        sub_processor = sub_processor_class(system_name, self.sub_processor_config)

                        # Special handling for HardwareSubProcessor - pass ALL sections
                        if sub_processor_class.__name__ == 'HardwareSubProcessor':
                            # Pass all sections so it can create comprehensive server documents
                            documents = sub_processor.process_with_all_sections(sections)
                        else:
                            # Regular sub-processors get their specific section
                            documents = sub_processor.process(section_data)

                        system_documents.extend(documents)
                        self.logger.info(f"  Generated {len(documents)} documents from {section_name} using {sub_processor_class.__name__}")
                    except Exception as e:
                        self.logger.error(f"Sub-processor {sub_processor_class.__name__} failed for section '{section_name}': {e}")
            else:
                self.logger.debug(f"No sub-processor registered for section '{section_name}'")

        self.logger.info(f"Completed processing {system_name}: {len(system_documents)} documents generated")
        return system_name, system_documents

    def _save_rag_data_json(self, output_path: Path) -> Path:
        """
        Save aggregated documents to rag_data.json

        Args:
            output_path: Output directory path

        Returns:
            Path to saved rag_data.json file
        """
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

        # Remove existing documents from systems we're re-processing
        original_count = len(rag_data.get('documents', []))

        if self.processed_systems:
            # Remove documents from systems being reprocessed
            # Keep documents from other systems (legacy processors, other systems)
            filtered_documents = []
            removed_count = 0

            for doc in rag_data.get('documents', []):
                # Get system name from document metadata
                doc_system = doc.get('metadata', {}).get('system_name') or doc.get('metadata', {}).get('hosted_by')

                # Keep document if it's not from a system we're reprocessing
                if doc_system not in self.processed_systems:
                    filtered_documents.append(doc)
                else:
                    removed_count += 1

            rag_data['documents'] = filtered_documents
            self.logger.info(f"Removed {removed_count} existing documents from {len(self.processed_systems)} reprocessed systems")

        # Add new documents
        rag_data['documents'].extend(self.all_documents)
        self.logger.info(f"Added {len(self.all_documents)} new documents")

        # Update metadata
        rag_data['metadata']['export_timestamp'] = datetime.now().isoformat()
        rag_data['metadata']['total_documents'] = len(rag_data['documents'])

        # Count document types
        doc_type_counts = {}
        for doc in rag_data['documents']:
            doc_type = doc.get('type', 'unknown')
            doc_type_counts[doc_type] = doc_type_counts.get(doc_type, 0) + 1

        for doc_type, count in doc_type_counts.items():
            rag_data['metadata'][f'total_{doc_type}s'] = count

        # Save updated rag_data.json
        with open(rag_data_file, 'w') as f:
            json.dump(rag_data, f, indent=2, default=str)

        self.logger.info(f"Saved rag_data.json with {len(rag_data['documents'])} total documents")
        return rag_data_file

    def _create_empty_rag_data(self) -> Dict[str, Any]:
        """Create empty rag_data.json structure"""
        return {
            "metadata": {
                "export_timestamp": datetime.now().isoformat(),
                "total_documents": 0,
                "total_systems": 0,
                "processing_method": "unified_processor"
            },
            "documents": [],
            "entities": {
                "systems": {},
                "services": {},
                "categories": {}
            },
            "relationships": []
        }
