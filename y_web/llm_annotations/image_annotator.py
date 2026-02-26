"""LLM-free image annotator shim."""


class Annotator:
    def __init__(self, llm=None, llm_url=None):
        self.llm = llm
        self.llm_url = llm_url

    def annotate(self, image_url):
        return "Image"
