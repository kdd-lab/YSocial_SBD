"""Image annotation helpers (LLM-disabled build)."""


class Annotator(object):
    """No-op image annotator preserving API compatibility."""

    def __init__(self, llmv, llm_url=None):
        self.config_list = None
        self.image_agent = None
        self.user_proxy = None

    def annotate(self, image):
        """
        Generate a natural language description of an image.

        Args:
            image: Image path or URL to describe

        Returns:
            String description of the image content, or None if description
            generation fails (e.g., model refuses, error occurs)
        """
        return None
