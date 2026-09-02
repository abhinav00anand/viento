"""Production async Python example using AsyncVientoClient SDK.

Usage:
    python async_chat_stream.py --key vnt_tmp_... --server https://viento.onrender.com
"""

import argparse
import asyncio
import sys
from viento.client import AsyncVientoClient


async def main() -> None:
    parser = argparse.ArgumentParser(description="Viento Async Client Example")
    parser.add_argument("--key", required=True, help="1-hour temporary API key (vnt_tmp_...)")
    parser.add_argument("--server", default="https://viento.onrender.com", help="Viento server base URL")
    parser.add_argument("--model", default="llama3.1:8b", help="Model name advertised by node")
    args = parser.parse_args()

    print(f"Connecting AsyncVientoClient to {args.server}...")

    async with AsyncVientoClient(base_url=args.server, api_key=args.key) as client:
        print("\nChecking node status:")
        status = await client.get_node_status()
        print(f" - Active Session: {status.get('session_id')}")
        print(f" - Key Expires In: {status.get('ttl_seconds')} seconds")

        print(f"\nStreaming response for model '{args.model}':\n")
        response_stream = await client.chat_completions(
            model=args.model,
            messages=[{"role": "user", "content": "Write a python function to compute fibonacci numbers efficiently."}],
            stream=True,
            temperature=0.3,
        )

        async for chunk in response_stream:
            content = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
            if content:
                sys.stdout.write(content)
                sys.stdout.flush()

        print("\n\nAsync stream complete.")


if __name__ == "__main__":
    asyncio.run(main())
