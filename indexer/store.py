from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

VSTORE_DIR = "knowledge/vector_store"

def get_embeddings():
    return HuggingFaceEmbeddings(model_name="BAAI/bge-small-zh-v1.5")

def build(docs):
    vs = Chroma.from_documents(docs, get_embeddings(), persist_directory=VSTORE_DIR)
    return vs

def get_retriever(top_k=5):
    vs = Chroma(persist_directory=VSTORE_DIR, embedding_function=get_embeddings())
    return vs.as_retriever(search_kwargs={"k": top_k})