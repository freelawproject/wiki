import environ

env = environ.FileAwareEnv()

# API key for the Anthropic API, used to generate alt text for image
# uploads. When unset, uploads skip the AI call and fall back to the
# filename as alt text.
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")

# Vision-capable model used to describe uploaded images.
ANTHROPIC_OCR_MODEL = env("ANTHROPIC_OCR_MODEL", default="claude-opus-4-8")
