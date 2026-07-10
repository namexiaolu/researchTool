from pathlib import Path
from langchain_community.document_loaders import PyPDFLoader, UnstructuredMarkdownLoader

def load(path: Path):
    ext = path.suffix.lower()
    if ext == ".pdf":
        return PyPDFLoader(str(path)).load()
    if ext in (".md", ".txt"):
        return UnstructuredMarkdownLoader(str(path)).load()
    return []