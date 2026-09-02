"""
Viento SDK — Distributed AI Inference Runtime

Connect your local LLMs (Ollama, llama.cpp, vLLM) to the Viento Cloud
mesh and serve distributed inference jobs via the OpenAI-compatible API.

Quick Start:
    >>> from viento.client.client import VientoClient
    >>> client = VientoClient(api_key="vnt_tmp_...")
    >>> response = client.chat.completions.create(
    ...     model="llama3:latest",
    ...     messages=[{"role": "user", "content": "Hello!"}],
    ... )

Run as a node:
    $ viento run

Documentation: https://github.com/abhinav00anand/viento
"""

__version__ = "0.3.1"
__author__ = "Viento Cloud Team"
__email__ = "indrohelpdesk@gmail.com"
__license__ = "MIT"
__url__ = "https://github.com/abhinav00anand/viento"

from viento.client.client import AsyncVientoClient, VientoClient

__all__ = [
    "__version__",
    "__author__",
    "VientoClient",
    "AsyncVientoClient",
]
