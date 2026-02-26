"""Lightweight local text annotation utilities (LLM-free)."""

import re


class ContentAnnotator:
    def __init__(self, llm=None, llm_url=None):
        self.llm = llm
        self.llm_url = llm_url

    def annotate_emotions(self, text):
        return []

    def annotate_topics(self, text):
        words = re.findall(r"[A-Za-z][A-Za-z0-9_\-]{3,}", text or "")
        unique = []
        for word in words:
            low = word.lower()
            if low not in unique:
                unique.append(low)
        return unique[:5]

    def extract_components(self, text, c_type="hashtags"):
        text = text or ""
        if c_type == "hashtags":
            return [f"#{tag}" for tag in re.findall(r"#([A-Za-z0-9_]+)", text)]
        if c_type == "mentions":
            return [f"@{name}" for name in re.findall(r"@([A-Za-z0-9_\.]+)", text)]
        return []
