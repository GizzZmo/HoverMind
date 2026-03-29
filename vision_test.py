import argparse
import io
import os
import sys
from typing import Optional, Union

from google import genai
from PIL import Image

from hovermind import AI_PROMPT, GeminiAnalyzer


ImageSource = Union[str, os.PathLike, Image.Image, bytes, bytearray]


def _load_image(source: ImageSource) -> Image.Image:
    """Return a PIL Image from a path, bytes, or already-open image.

    When reading from disk/bytes we copy the image so the caller can safely use
    it after the underlying file/stream handle is closed.
    """
    if isinstance(source, Image.Image):
        return source
    if isinstance(source, (str, os.PathLike)):
        with Image.open(source) as img:
            return img.copy()
    if isinstance(source, (bytes, bytearray)):
        with Image.open(io.BytesIO(source)) as img:
            return img.copy()
    raise TypeError(
        "image must be a PIL.Image.Image, path-like, or bytes-like object"
    )


def analyze_image(
    image: ImageSource,
    *,
    model_name: Optional[str] = None,
    api_key: Optional[str] = None,
) -> str:
    """Send an image to the Gemini Vision API and return the analysis text.

    Model precedence: explicit ``model_name`` argument → ``AI_MODEL`` env var →
    :class:`hovermind.GeminiAnalyzer` default.
    """
    resolved_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not resolved_key:
        raise ValueError("GEMINI_API_KEY is not set.")

    model = model_name or os.environ.get("AI_MODEL") or GeminiAnalyzer.default_model
    client = genai.Client(api_key=resolved_key)
    img = _load_image(image)

    response = client.models.generate_content(
        model=model,
        contents=[img, AI_PROMPT],
    )
    return (response.text or "").strip()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send an image to Gemini Vision and print the analysis."
    )
    parser.add_argument(
        "image",
        help="Path to the image file to analyze.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Optional model override (defaults to AI_MODEL env or Gemini default).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    try:
        result = analyze_image(args.image, model_name=args.model)
        print("HoverMind AI Analysis:")
        print("-" * 30)
        print(result)
        print("-" * 30)
        return 0
    except FileNotFoundError:
        print(f"Error: Could not find the image file '{args.image}'.", file=sys.stderr)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
    except Exception as exc:  # pragma: no cover - demo helper
        print(f"An error occurred: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover - CLI helper
    sys.exit(main())
