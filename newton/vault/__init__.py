"""Newton vault layer (Block 3).

Houses the Qdrant client wrapper, parser, scanner, RAG search, and the
vault tools. Step 3.1 ships only the Qdrant wrapper.
"""

from newton.vault.qdrant_client import QdrantError, QdrantHealth, get_client

__all__ = ["QdrantError", "QdrantHealth", "get_client"]
