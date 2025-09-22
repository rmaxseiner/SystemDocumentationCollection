# src/utils/chroma_utils.py
"""
ChromaDB integration utility for infrastructure documentation collection.
Based on patterns from InfrastructureDocumentationMCP project.
"""

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Dict, List, Any, Optional
import chromadb
from chromadb.config import Settings

logger = logging.getLogger('chroma_utils')

class ChromaDBManager:
    """Manages ChromaDB vector store for infrastructure documentation"""

    def __init__(self, chroma_db_path: str, collection_name: str = "infrastructure"):
        """
        Initialize ChromaDB manager

        Args:
            chroma_db_path: Path where ChromaDB database will be stored
            collection_name: Name of the collection to create/use
        """
        self.chroma_db_path = Path(chroma_db_path)
        self.collection_name = collection_name
        self.client = None
        self.collection = None
        self.embeddings_model = None

        logger.info(f"Initializing ChromaDB manager at {self.chroma_db_path}")

    def initialize(self, recreate: bool = True):
        """
        Initialize ChromaDB client and collection

        Args:
            recreate: If True, delete existing database and create fresh
        """
        try:
            # Import sentence transformers here to avoid import errors if not available
            from sentence_transformers import SentenceTransformer
            self.embeddings_model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("Loaded SentenceTransformer embeddings model")
        except ImportError:
            logger.error("sentence-transformers package not found. Install with: pip install sentence-transformers")
            raise

        # Remove existing database if recreate is requested
        if recreate and self.chroma_db_path.exists():
            logger.info(f"Removing existing ChromaDB at {self.chroma_db_path}")
            shutil.rmtree(self.chroma_db_path)

        # Ensure parent directory exists
        self.chroma_db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize ChromaDB client
        self.client = chromadb.PersistentClient(
            path=str(self.chroma_db_path),
            settings=Settings(allow_reset=True)
        )
        logger.info(f"Initialized ChromaDB persistent client at {self.chroma_db_path}")

        # Create or get collection
        try:
            if recreate:
                # Try to delete existing collection first
                try:
                    self.client.delete_collection(name=self.collection_name)
                    logger.info(f"Deleted existing collection: {self.collection_name}")
                except:
                    pass  # Collection might not exist

            # Create collection
            self.collection = self.client.create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"}
            )
            logger.info(f"Created new collection: {self.collection_name}")

        except Exception as e:
            if "already exists" in str(e).lower():
                # Get existing collection
                self.collection = self.client.get_collection(name=self.collection_name)
                logger.info(f"Using existing collection: {self.collection_name}")
            else:
                logger.error(f"Failed to create/get collection: {e}")
                raise

    def add_documents(self, documents: List[Dict[str, Any]], batch_size: int = 100):
        """
        Add documents to ChromaDB collection

        Args:
            documents: List of document dictionaries with id, title, content, metadata, etc.
            batch_size: Number of documents to process in each batch
        """
        if not self.collection or not self.embeddings_model:
            raise RuntimeError("ChromaDB manager not initialized. Call initialize() first.")

        if not documents:
            logger.warning("No documents provided to add to ChromaDB")
            return

        logger.info(f"Adding {len(documents)} documents to ChromaDB collection")

        # Process documents in batches
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i + batch_size]
            self._process_document_batch(batch)
            logger.info(f"Processed batch {i//batch_size + 1}/{(len(documents) + batch_size - 1)//batch_size}")

    def _process_document_batch(self, documents: List[Dict[str, Any]]):
        """Process a batch of documents for ChromaDB"""

        # Prepare data for embedding with deduplication
        texts = []
        metadatas = []
        ids = []
        seen_ids = set()

        for doc in documents:
            # Handle missing fields gracefully
            title = doc.get('title', 'Untitled')
            content = doc.get('content', '')
            text_content = f"{title}\n\n{content}"

            texts.append(text_content)

            # Clean metadata - convert lists to strings and handle None values
            cleaned_metadata = {
                'type': doc.get('type', 'unknown'),
                'title': title,
                'tags': ','.join(doc.get('tags', [])),
            }

            # Add other metadata, converting complex types to strings
            for key, value in doc.get('metadata', {}).items():
                if isinstance(value, list):
                    cleaned_metadata[key] = ','.join(str(item) for item in value)
                elif isinstance(value, dict):
                    # Convert dict to JSON string
                    cleaned_metadata[key] = json.dumps(value)
                elif value is not None:
                    cleaned_metadata[key] = str(value)

            # Check for duplicate IDs
            doc_id = str(doc.get('id', f'doc-{len(ids)}'))
            if doc_id in seen_ids:
                logger.warning(f"Skipping duplicate document ID: {doc_id}")
                continue

            seen_ids.add(doc_id)
            metadatas.append(cleaned_metadata)
            ids.append(doc_id)

        if not texts:
            logger.warning("No valid documents to add after deduplication")
            return

        try:
            # Generate embeddings
            logger.debug(f"Generating embeddings for {len(texts)} documents")
            embeddings = self.embeddings_model.encode(texts).tolist()

            # Add to collection
            self.collection.add(
                documents=texts,
                metadatas=metadatas,
                embeddings=embeddings,
                ids=ids
            )

            logger.debug(f"Added {len(documents)} documents to ChromaDB collection")

        except Exception as e:
            logger.error(f"Failed to add document batch to ChromaDB: {e}")
            raise

    def get_collection_stats(self) -> Dict[str, Any]:
        """Get statistics about the ChromaDB collection"""
        if not self.collection:
            return {"error": "Collection not initialized"}

        try:
            count = self.collection.count()
            return {
                "collection_name": self.collection_name,
                "document_count": count,
                "database_path": str(self.chroma_db_path)
            }
        except Exception as e:
            logger.error(f"Failed to get collection stats: {e}")
            return {"error": str(e)}

    def test_query(self, query: str = "test query", limit: int = 5) -> Dict[str, Any]:
        """
        Test the ChromaDB collection with a sample query

        Args:
            query: Test query string
            limit: Number of results to return

        Returns:
            Dictionary with query results or error information
        """
        if not self.collection or not self.embeddings_model:
            return {"error": "ChromaDB manager not initialized"}

        try:
            # Generate query embedding
            query_embedding = self.embeddings_model.encode([query]).tolist()

            # Query collection
            results = self.collection.query(
                query_embeddings=query_embedding,
                n_results=limit,
                include=['documents', 'metadatas', 'distances']
            )

            # Format results
            formatted_results = []
            for i in range(len(results['ids'][0])):
                formatted_results.append({
                    'id': results['ids'][0][i],
                    'relevance_score': 1 - results['distances'][0][i],  # Convert distance to similarity
                    'metadata': results['metadatas'][0][i],
                    'content_preview': results['documents'][0][i][:200] + "..." if len(results['documents'][0][i]) > 200 else results['documents'][0][i]
                })

            return {
                "query": query,
                "results_count": len(formatted_results),
                "results": formatted_results
            }

        except Exception as e:
            logger.error(f"Failed to test query ChromaDB: {e}")
            return {"error": str(e)}


def create_chromadb_from_rag_data(rag_data_path: str, chroma_db_path: str, recreate: bool = True) -> Dict[str, Any]:
    """
    Convenience function to create ChromaDB from existing rag_data.json

    Args:
        rag_data_path: Path to rag_data.json file
        chroma_db_path: Path where ChromaDB should be created
        recreate: Whether to recreate the database from scratch

    Returns:
        Dictionary with creation results and statistics
    """
    logger.info(f"Creating ChromaDB from RAG data: {rag_data_path} -> {chroma_db_path}")

    # Load RAG data
    rag_data_file = Path(rag_data_path)
    if not rag_data_file.exists():
        error_msg = f"RAG data file not found: {rag_data_path}"
        logger.error(error_msg)
        return {"error": error_msg}

    try:
        with open(rag_data_file, 'r') as f:
            rag_data = json.load(f)
    except Exception as e:
        error_msg = f"Failed to load RAG data: {e}"
        logger.error(error_msg)
        return {"error": error_msg}

    documents = rag_data.get('documents', [])
    if not documents:
        error_msg = "No documents found in RAG data"
        logger.warning(error_msg)
        return {"error": error_msg}

    # Initialize ChromaDB manager
    chroma_manager = ChromaDBManager(chroma_db_path)

    try:
        # Initialize and populate
        chroma_manager.initialize(recreate=recreate)
        chroma_manager.add_documents(documents)

        # Get final statistics
        stats = chroma_manager.get_collection_stats()

        # Test with a sample query
        test_result = chroma_manager.test_query("infrastructure system")

        logger.info(f"Successfully created ChromaDB with {stats.get('document_count', 0)} documents")

        return {
            "success": True,
            "documents_processed": len(documents),
            "chromadb_path": chroma_db_path,
            "collection_stats": stats,
            "test_query_result": test_result
        }

    except Exception as e:
        error_msg = f"Failed to create ChromaDB: {e}"
        logger.error(error_msg)
        return {"error": error_msg}