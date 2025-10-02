#!/usr/bin/env python3
"""
Build RAG assets from project_docs/ and save to RAG/ folder.

This script processes documents in project_docs/, generates embeddings,
builds a FAISS index, and saves all artifacts to the RAG/ folder for
the API to use at runtime.

Usage:
    python scripts/build_rag.py
"""

import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Any

import numpy as np
from openai import OpenAI

# Try to import FAISS - if not available, provide instructions
try:
    import faiss
except ImportError:
    print("FAISS not installed. Install with: pip install faiss-cpu")
    print("Or for GPU support: pip install faiss-gpu")
    exit(1)

# Setup logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECT_DOCS_DIR = PROJECT_ROOT / "web" / "project_docs"
RAG_DIR = PROJECT_ROOT / "RAG"

# Ensure RAG directory exists
RAG_DIR.mkdir(exist_ok=True)

# OpenAI client for embeddings
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))

def load_documents(docs_dir: Path) -> List[Dict[str, Any]]:
    """Load and chunk documents from project_docs/."""
    documents = []

    if not docs_dir.exists():
        log.warning(f"project_docs directory not found at {docs_dir}")
        return documents

    # Process markdown and text files
    for file_path in docs_dir.rglob("*.md"):
        try:
            content = file_path.read_text(encoding="utf-8")
            # Simple chunking: split by headers or paragraphs
            chunks = chunk_text(content, max_length=1000)
            for i, chunk in enumerate(chunks):
                documents.append({
                    "id": f"{file_path.stem}_chunk_{i}",
                    "content": chunk.strip(),
                    "source": str(file_path.relative_to(PROJECT_ROOT)),
                    "file_path": str(file_path)
                })
        except Exception as e:
            log.warning(f"Failed to process {file_path}: {e}")

    log.info(f"Loaded {len(documents)} document chunks")
    return documents

def chunk_text(text: str, max_length: int = 1000) -> List[str]:
    """Simple text chunking by splitting on double newlines or length."""
    # First split by headers (markdown style)
    sections = []
    current_section = []

    for line in text.split('\n'):
        if line.startswith('#') and current_section:
            sections.append('\n'.join(current_section))
            current_section = [line]
        else:
            current_section.append(line)

    if current_section:
        sections.append('\n'.join(current_section))

    # Further chunk long sections
    chunks = []
    for section in sections:
        if len(section) <= max_length:
            chunks.append(section)
        else:
            # Split long sections into smaller chunks
            words = section.split()
            for i in range(0, len(words), max_length // 6):  # Rough estimate
                chunk_words = words[i:i + max_length // 6]
                chunks.append(' '.join(chunk_words))

    return chunks

def generate_embeddings(texts: List[str]) -> np.ndarray:
    """Generate embeddings for a list of texts using OpenAI."""
    if not client.api_key:
        raise ValueError("OPENAI_API_KEY environment variable not set")

    embeddings = []

    # Process in batches to avoid rate limits
    batch_size = 100
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        log.info(f"Generating embeddings for batch {i//batch_size + 1}/{(len(texts)-1)//batch_size + 1}")

        try:
            response = client.embeddings.create(
                input=batch,
                model="text-embedding-3-small"  # or text-embedding-ada-002
            )
            batch_embeddings = [data.embedding for data in response.data]
            embeddings.extend(batch_embeddings)
        except Exception as e:
            log.error(f"Failed to generate embeddings for batch: {e}")
            # Return zero embeddings for failed batch
            batch_embeddings = [[0.0] * 1536 for _ in batch]  # 1536 is the dimension for text-embedding-3-small
            embeddings.extend(batch_embeddings)

    return np.array(embeddings, dtype=np.float32)

def build_faiss_index(embeddings: np.ndarray) -> faiss.IndexFlatIP:
    """Build FAISS index from embeddings."""
    # Normalize embeddings for cosine similarity
    faiss.normalize_L2(embeddings)

    # Create index - using Inner Product (cosine similarity after normalization)
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)

    # Add embeddings to index
    index.add(embeddings)

    log.info(f"Built FAISS index with {index.ntotal} vectors of dimension {dimension}")
    return index

def save_rag_assets(documents: List[Dict], embeddings: np.ndarray, index: faiss.IndexFlatIP):
    """Save all RAG assets to RAG/ folder."""

    # Save FAISS index
    index_path = RAG_DIR / "rag_index.faiss"
    faiss.write_index(index, str(index_path))
    log.info(f"Saved FAISS index to {index_path}")

    # Save embeddings
    embeddings_path = RAG_DIR / "rag_embeddings.npy"
    np.save(str(embeddings_path), embeddings)
    log.info(f"Saved embeddings to {embeddings_path}")

    # Save metadata (mapping of chunk IDs to content and source)
    metadata_path = RAG_DIR / "rag_metadata.json"
    metadata = {
        doc["id"]: {
            "content": doc["content"],
            "source": doc["source"],
            "file_path": doc["file_path"]
        }
        for doc in documents
    }

    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    log.info(f"Saved metadata to {metadata_path}")

    # Save documents as JSONL (optional, for debugging)
    docs_path = RAG_DIR / "rag_docs.jsonl"
    with open(docs_path, 'w', encoding='utf-8') as f:
        for doc in documents:
            json.dump(doc, f, ensure_ascii=False)
            f.write('\n')
    log.info(f"Saved documents to {docs_path}")

def main():
    """Main build process."""
    log.info("Starting RAG build process...")

    # Load documents
    documents = load_documents(PROJECT_DOCS_DIR)
    if not documents:
        log.error("No documents found to process")
        return

    # Generate embeddings
    texts = [doc["content"] for doc in documents]
    embeddings = generate_embeddings(texts)

    # Build FAISS index
    index = build_faiss_index(embeddings)

    # Save all assets
    save_rag_assets(documents, embeddings, index)

    log.info("RAG build completed successfully!")
    log.info(f"Assets saved to {RAG_DIR}")
    log.info(f"Index contains {len(documents)} document chunks")

if __name__ == "__main__":
    main()