import os

from google import genai
from PIL import Image


# 1. Initialize the client (picks up GEMINI_API_KEY from the environment)
client = genai.Client()


def analyze_image(image_path: str) -> None:
    """Send an image to the Gemini Vision API and print a short analysis."""
    print(f"Loading image from: {image_path}...")

    try:
        # 2. Open the image using Pillow
        # In the app, the screen grabber can pass a PIL Image directly.
        img = Image.open(image_path)

        # 3. The HoverMind system prompt
        prompt = (
            "Briefly explain what is the main subject of this image. "
            "If it's code, explain it. If it's an image, describe it. "
            "If it's a UI element, state its function. Keep it under 3 sentences."
        )

        print("Sending to Gemini Vision API... 🧠\n")

        # 4. Call the model (using the stable 2.5-flash)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[img, prompt],
        )

        # 5. Output the result
        print("HoverMind AI Analysis:")
        print("-" * 30)
        print(response.text)
        print("-" * 30)

    except FileNotFoundError:
        print(f"Error: Could not find the image file '{image_path}'.")
    except Exception as exc:  # pragma: no cover - demo helper
        print(f"An error occurred: {exc}")


if __name__ == "__main__":
    # Replace this with the actual name of your screenshot file
    target_image = "Skjermbilde 2026-03-29 000623.png"

    # Ensure API key is present before running
    if not os.environ.get("GEMINI_API_KEY"):
        print("Warning: GEMINI_API_KEY environment variable is not set!")
    else:
        analyze_image(target_image)
