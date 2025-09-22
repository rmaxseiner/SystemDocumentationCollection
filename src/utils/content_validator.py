# src/utils/content_validator.py
"""
Content validation utilities for RAG document processing.
Provides functions to validate document content before processing.
"""

import logging
from typing import Dict, Any, Optional, List
import re


class ContentValidator:
    """Content validation utility for RAG documents"""

    def __init__(self, max_word_count: int = 400, min_content_length: int = 10):
        """
        Initialize content validator

        Args:
            max_word_count: Maximum allowed word count for content (default: 400)
            min_content_length: Minimum allowed content length in characters (default: 10)
        """
        self.max_word_count = max_word_count
        self.min_content_length = min_content_length
        self.logger = logging.getLogger('content_validator')

    def count_words(self, text: str) -> int:
        """
        Count words in text using simple whitespace-based splitting

        Args:
            text: Text to count words in

        Returns:
            Word count
        """
        if not text or not isinstance(text, str):
            return 0

        # Remove extra whitespace and split on whitespace
        words = text.strip().split()
        return len(words)

    def validate_content_length(self, content: str, document_id: str = None,
                              document_title: str = None) -> bool:
        """
        Validate content length (both minimum and maximum)

        Args:
            content: Content text to validate
            document_id: Optional document ID for logging context
            document_title: Optional document title for logging context

        Returns:
            True if content is valid (within limits), False otherwise
        """
        if not content or not isinstance(content, str):
            # Create context string for logging
            context_parts = []
            if document_id:
                context_parts.append(f"ID: {document_id}")
            if document_title:
                context_parts.append(f"Title: {document_title}")
            context = f" ({', '.join(context_parts)})" if context_parts else ""

            warning_msg = f"Content is empty or not a string{context}"
            self.logger.warning(warning_msg)
            print(f"⚠️ WARNING: {warning_msg}")
            return False

        content_length = len(content.strip())
        word_count = self.count_words(content)
        is_valid = True

        # Create context string for logging
        context_parts = []
        if document_id:
            context_parts.append(f"ID: {document_id}")
        if document_title:
            context_parts.append(f"Title: {document_title}")
        context = f" ({', '.join(context_parts)})" if context_parts else ""

        # Check minimum content length
        if content_length < self.min_content_length:
            warning_msg = f"Content too short: {content_length} characters (minimum: {self.min_content_length}){context}"
            self.logger.warning(warning_msg)
            print(f"⚠️ WARNING: {warning_msg}")
            is_valid = False

        # Check maximum word count
        if word_count > self.max_word_count:
            warning_msg = f"Content exceeds {self.max_word_count} words: {word_count} words{context}"
            self.logger.warning(warning_msg)
            print(f"⚠️ WARNING: {warning_msg}")
            is_valid = False

        return is_valid

    def validate_document(self, document: Dict[str, Any]) -> bool:
        """
        Validate a complete RAG document structure

        Args:
            document: Document dictionary with 'content', 'id', 'title' fields

        Returns:
            True if document is valid, False otherwise
        """
        if not isinstance(document, dict):
            self.logger.error("Document must be a dictionary")
            return False

        content = document.get('content', '')
        document_id = document.get('id')
        document_title = document.get('title')

        return self.validate_content_length(content, document_id, document_title)

    def validate_document_batch(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validate a batch of documents and return summary statistics

        Args:
            documents: List of document dictionaries

        Returns:
            Dictionary with validation statistics
        """
        if not documents:
            return {
                'total_documents': 0,
                'valid_documents': 0,
                'invalid_documents': 0,
                'validation_rate': 1.0
            }

        total = len(documents)
        valid = 0
        invalid = 0

        for doc in documents:
            if self.validate_document(doc):
                valid += 1
            else:
                invalid += 1

        validation_rate = valid / total if total > 0 else 1.0

        stats = {
            'total_documents': total,
            'valid_documents': valid,
            'invalid_documents': invalid,
            'validation_rate': validation_rate
        }

        if invalid > 0:
            self.logger.warning(f"Content validation summary: {invalid}/{total} documents exceed word limit")
            print(f"📊 Content validation: {invalid}/{total} documents exceeded {self.max_word_count} word limit")

        return stats


# Convenience functions for easy import and use
def create_content_validator(max_word_count: int = 400, min_content_length: int = 10) -> ContentValidator:
    """Create a ContentValidator instance with specified limits"""
    return ContentValidator(max_word_count, min_content_length)


def validate_document_content(document: Dict[str, Any], max_word_count: int = 400, min_content_length: int = 10) -> bool:
    """
    Quick validation function for a single document

    Args:
        document: Document dictionary to validate
        max_word_count: Maximum allowed word count (default: 400)
        min_content_length: Minimum allowed content length in characters (default: 10)

    Returns:
        True if content is valid, False otherwise
    """
    validator = ContentValidator(max_word_count, min_content_length)
    return validator.validate_document(document)


def validate_content_text(content: str, document_id: str = None,
                         document_title: str = None, max_word_count: int = 400, min_content_length: int = 10) -> bool:
    """
    Quick validation function for content text only

    Args:
        content: Content text to validate
        document_id: Optional document ID for context
        document_title: Optional document title for context
        max_word_count: Maximum allowed word count (default: 400)
        min_content_length: Minimum allowed content length in characters (default: 10)

    Returns:
        True if content is valid, False otherwise
    """
    validator = ContentValidator(max_word_count, min_content_length)
    return validator.validate_content_length(content, document_id, document_title)