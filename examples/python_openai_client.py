"""Production Python example demonstrating standard OpenAI SDK integration with Viento Cloud.

Usage:
    python python_openai_client.py --key vnt_tmp_... --server https://viento.onrender.com
"""

import argparse
import sys
from openai import OpenAI


def main() -> None:
    parser = argparse.ArgumentParser(description="Viento OpenAI Client Example")
    parser.add_argument("--key", required=True, help="1-hour temporary API key (vnt_tmp_...)")
    parser.add_argument("--server", default="https://viento.onrender.com", help="Viento server base URL")
    parser.add_argument("--model", default="llama3.1:8b", help="Model name advertised by your Viento node")
    args = parser.parse_args()

    print(f"Connecting to Viento Cloud at {args.server}...")
    
    # Initialize standard OpenAI client pointing at Viento endpoint
    client = OpenAI(
        base_url=f"{args.server.rstrip('/')}/v1",
        api_key=args.key,
    )

    print("\n1. Listing Available Models:")
    models = client.models.list()
    for model in models.data:
        print(f" - Model ID: {model.id} (Owned by: {model.owned_by})")

    print(f"\n2. Submitting Streaming Chat Completion ({args.model}):\n")
    stream = client.chat.completions.create(
        model=args.model,
        messages=[
            {"role": "system", "content": "You are a helpful, concise AI assistant."},
            {"role": "user", "content": "Explain quantum computing in three clear bullet points."},
        ],
        stream=True,
        temperature=0.7,
    )

    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            sys.stdout.write(chunk.choices[0].delta.content)
            sys.stdout.flush()

    print("\n\nStream finished successfully.")


if __name__ == "__main__":
    main()
