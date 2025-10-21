#!/usr/bin/env python3
"""
Reusable embedding model class for both ingestion and query processes.

This module provides a unified interface for creating embeddings using
SentenceTransformers, with automatic device detection and configuration.
"""

import os
import logging
from typing import List, Union, Optional
import numpy as np

# Default configuration - Using BGE-M3 for multilingual retrieval
DEFAULT_MODEL_NAME = "BAAI/bge-m3"
DEFAULT_USE_CUDA = "auto"  # "true", "false", "auto"


class EmbeddingModel:
    """
    A reusable embedding model class that handles device detection,
    model loading, and embedding creation for both ingestion and queries.
    """
    
    def __init__(
        self,
        model_name: Optional[str] = None,
        use_cuda: Optional[str] = None,
        hf_token: Optional[str] = None
    ):
        """
        Initialize the embedding model.
        
        Args:
            model_name: Name of the SentenceTransformer model
            use_cuda: CUDA usage preference ("true", "false", "auto")
            hf_token: Hugging Face authentication token if needed
        """
        self.model_name = model_name or os.environ.get("EMBED_MODEL", DEFAULT_MODEL_NAME)
        self.use_cuda = use_cuda or os.environ.get("USE_CUDA", DEFAULT_USE_CUDA).lower()
        self.hf_token = hf_token or os.environ.get("HF_TOKEN")
        
        self._model = None
        self._device = None
        self._vector_dim = None
        
    @property
    def model(self):
        """Lazy-load the SentenceTransformer model."""
        if self._model is None:
            self._load_model()
        return self._model
    
    @property
    def device(self) -> str:
        """Get the device being used by the model."""
        if self._device is None:
            self._determine_device()
        return self._device
    
    @property
    def vector_dim(self) -> int:
        """Get the vector dimensions of the model."""
        if self._vector_dim is None:
            # Set vector dimensions based on model type
            model_lower = self.model_name.lower()

            if "bge-m3" in model_lower:
                self._vector_dim = 1024  # BGE-M3 uses 1024 dimensions
            elif "qwen3-embedding-0.6b" in model_lower:
                self._vector_dim = 1024  # Qwen3 0.6B uses 1024 dimensions
            elif "gte-multilingual-base" in model_lower:
                self._vector_dim = 768   # GTE-multilingual-base uses 768 dimensions
            elif "jina-embeddings-v3" in model_lower:
                self._vector_dim = 1024  # Jina Embeddings v3 uses 1024 dimensions
            elif "embeddinggemma-300m" in model_lower:
                self._vector_dim = 768   # Google EmbeddingGemma 300M uses 768 dimensions
            elif "bert" in model_lower:
                self._vector_dim = 768   # BERT-based models use 768
            else:
                # For other models, we'd need to load and check
                # This is a fallback that requires model loading
                logging.info(f"Unknown model dimension for {self.model_name}, detecting...")
                test_embedding = self.encode(["test"], show_progress_bar=False, prefix=None)
                self._vector_dim = len(test_embedding[0])
                logging.info(f"Detected dimension: {self._vector_dim}")
        return self._vector_dim
    
    def _determine_device(self):
        """Determine which device to use for the model."""
        try:
            import torch
            
            if self.use_cuda == "false":
                self._device = "cpu"
            elif self.use_cuda == "auto":
                self._device = "cuda" if torch.cuda.is_available() else "cpu"
            else:  # "true" (default)
                if torch.cuda.is_available():
                    self._device = "cuda"
                else:
                    logging.warning("CUDA requested but not available, falling back to CPU")
                    self._device = "cpu"
        except ImportError:
            logging.warning("PyTorch not available, using CPU")
            self._device = "cpu"
    
    def _load_model(self):
        """Load the SentenceTransformer model."""
        try:
            from sentence_transformers import SentenceTransformer
            import torch
            
            # Determine device
            if self._device is None:
                self._determine_device()
            
            logging.info(f"Loading embedding model: {self.model_name} on device: {self._device}")
            
            # Handle Hugging Face authentication if needed
            if self.hf_token:
                logging.info("Using Hugging Face authentication token")
                self._model = SentenceTransformer(
                    self.model_name, 
                    device=self._device, 
                    token=self.hf_token,
                    trust_remote_code=True,
                )
            else:
                self._model = SentenceTransformer(self.model_name, device=self._device)
            
            # Log GPU info if using CUDA
            if self._device == "cuda" and torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0)
                gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1e9
                logging.info(f"Using GPU: {gpu_name} ({gpu_memory:.1f} GB)")
                
        except ImportError as e:
            if "torch" in str(e):
                raise ImportError("PyTorch not installed. Install with: pip install torch")
            else:
                raise ImportError("sentence-transformers not installed. Install with: pip install sentence-transformers")
        except Exception as e:
            raise RuntimeError(f"Failed to load embedding model {self.model_name}: {e}")
    
    def encode(
        self,
        texts: Union[str, List[str]], 
        normalize_embeddings: bool = True,
        batch_size: int = 64,
        convert_to_numpy: bool = True,
        show_progress_bar: bool = True,
        prefix: str = "passage"
    ) -> np.ndarray:
        """
        Create embeddings for the given texts.
        
        Args:
            texts: Single text or list of texts to embed
            normalize_embeddings: Whether to normalize the embeddings
            batch_size: Batch size for processing
            convert_to_numpy: Whether to convert to numpy array
            show_progress_bar: Whether to show progress bar
            prefix: Prefix to add to texts (e.g., "passage", "query")
            
        Returns:
            Numpy array of embeddings
        """
        # Ensure texts is a list
        if isinstance(texts, str):
            texts = [texts]
        
        # Add prefix if specified
        if prefix:
            prefixed_texts = [f"{prefix}: {text}" for text in texts]
        else:
            prefixed_texts = texts
        
        # Create embeddings
        embeddings = self.model.encode(
            prefixed_texts,
            normalize_embeddings=normalize_embeddings,
            batch_size=batch_size,
            convert_to_numpy=convert_to_numpy,
            show_progress_bar=show_progress_bar
        )
        
        return embeddings
    
    def encode_query(self, query: str, **kwargs) -> np.ndarray:
        """
        Create embeddings for a query text.
        
        Args:
            query: Query text to embed
            **kwargs: Additional arguments passed to encode()
            
        Returns:
            Numpy array of embeddings (1D vector)
        """
        # Set query-specific defaults
        kwargs.setdefault('prefix', 'query')
        kwargs.setdefault('show_progress_bar', False)
        
        result = self.encode(query, **kwargs)
        
        # If result is 2D (batch of 1), flatten to 1D
        if len(result.shape) == 2 and result.shape[0] == 1:
            result = result.flatten()
        
        return result
    
    def encode_passages(self, passages: List[str], **kwargs) -> np.ndarray:
        """
        Create embeddings for passage texts (for ingestion).
        
        Args:
            passages: List of passage texts to embed
            **kwargs: Additional arguments passed to encode()
            
        Returns:
            Numpy array of embeddings
        """
        # Set passage-specific defaults
        kwargs.setdefault('prefix', 'passage')
        kwargs.setdefault('show_progress_bar', True)
        
        return self.encode(passages, **kwargs)


# Global cache for embedding models (one per model)
_embedder_cache = {}


def get_embedder(
    model_name: Optional[str] = None,
    use_cuda: Optional[str] = None,
    hf_token: Optional[str] = None
) -> EmbeddingModel:
    """
    Get an embedding model instance (cached per model).

    Args:
        model_name: Model name
        use_cuda: CUDA preference
        hf_token: HF token

    Returns:
        EmbeddingModel instance
    """
    global _embedder_cache

    # Use model name as cache key
    cache_key = model_name or "default"

    if cache_key not in _embedder_cache:
        _embedder_cache[cache_key] = EmbeddingModel(
            model_name=model_name,
            use_cuda=use_cuda,
            hf_token=hf_token
        )

    return _embedder_cache[cache_key]


def reset_embedder(model_name: Optional[str] = None):
    """Reset embedder instance(s)."""
    global _embedder_cache
    if model_name:
        _embedder_cache.pop(model_name, None)
    else:
        _embedder_cache.clear()


if __name__ == "__main__":
    embedder = get_embedder()
    # Test encoding
    test_text = "Hello, world!"
    embedding = embedder.encode(test_text)
    print("Embedding:", embedding)