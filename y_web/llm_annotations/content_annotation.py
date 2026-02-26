"""Content annotation helpers (LLM-disabled build)."""

import re


class ContentAnnotator(object):
    """No-op annotator preserving API compatibility."""

    def __init__(self, llm=None, llm_url=None):
        self.annotator = None
        self.handler = None
        self.config_list = None

    def annotate_emotions(self, text):
        """
        Annotate emotions in text using GoEmotions taxonomy.

        Analyzes text to identify emotions from the GoEmotions taxonomy,
        which includes 28 emotion categories.

        Args:
            text: Text content to analyze

        Returns:
            List of emotion labels found in the text (e.g., ['joy', 'excitement'])
        """
        return []

    def annotate_topics(self, text):
        """
        Extract main topics discussed in text.

        Uses LLM to identify up to 3 general topics in the text,
        each described in 2 words.

        Args:
            text: Text content to analyze

        Returns:
            List of topic strings (e.g., ['climate change', 'renewable energy'])
        """
        return []

    def __clean_emotion(self, text):
        """
        Parse and validate emotion labels from LLM response.

        Extracts valid GoEmotions taxonomy labels from potentially
        noisy LLM output text.

        Args:
            text: Raw LLM response text

        Returns:
            List of validated emotion label strings
        """
        emotions = {
            "admiration": None,
            "amusement": None,
            "anger": None,
            "annoyance": None,
            "approval": None,
            "caring": None,
            "confusion": None,
            "curiosity": None,
            "desire": None,
            "disappointment": None,
            "disapproval": None,
            "disgust": None,
            "embarrassment": None,
            "excitement": None,
            "fear": None,
            "gratitude": None,
            "grief": None,
            "joy": None,
            "love": None,
            "nervousness": None,
            "optimism": None,
            "pride": None,
            "realization": None,
            "relief": None,
            "remorse": None,
            "sadness": None,
            "surprise": None,
            "trust": None,
        }
        try:
            emotion_eval = [
                e.strip()
                for e in text.replace("'", " ")
                .replace('"', " ")
                .replace("*", "")
                .replace(":", " ")
                .replace("[", " ")
                .replace("]", " ")
                .replace(",", " ")
                .split(" ")
                if e.strip() in emotions
            ]
        except:
            emotion_eval = []
        return emotion_eval

    def extract_components(self, text, c_type="hashtags"):
        """
        Extract hashtags or mentions from text using regex.

        Args:
            text: Text to extract components from
            c_type: Component type - "hashtags" for #tags or "mentions" for @users

        Returns:
            List of extracted components (including # or @ prefix)
        """
        # Define the regex pattern
        if c_type == "hashtags":
            pattern = re.compile(r"#\w+")
        elif c_type == "mentions":
            pattern = re.compile(r"@\w+")
        else:
            return []
        # Find all matches in the input text
        hashtags = pattern.findall(text)
        return hashtags
