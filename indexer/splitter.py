from langchain_text_splitters import RecursiveCharacterTextSplitter

def get_splitter(chunk_size=512, overlap=64):
    # 中文友好的递归分块：优先按段落，再按句号、空格
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", "。", "；", " ", ""],
    )
