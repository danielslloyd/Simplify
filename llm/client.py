"""
client.py — Thin wrapper around ollama.chat().
"""

import ollama


def query(model: str, prompt: str) -> str:
    """
    Send a prompt to the Ollama model and return the response text.

    Raises:
        ConnectionError: if Ollama is not running
        ValueError: if the model is not found
    """
    try:
        response = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response["message"]["content"]
    except Exception as e:
        err = str(e).lower()
        if "connection" in err or "refused" in err or "connect" in err:
            raise ConnectionError(
                "Could not connect to Ollama. Make sure Ollama is running: https://ollama.ai"
            ) from e
        if "not found" in err or "pull" in err or "404" in err:
            raise ValueError(
                f"Model '{model}' not found. Run: ollama pull {model}"
            ) from e
        raise
