import os
import math
from concurrent.futures import ThreadPoolExecutor
from langchain_community.document_loaders import PDFPlumberLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from langchain_community.vectorstores import FAISS

# Paths & embedding model
PDFS_DIR    = "pdfs"
FAISS_DIR   = "vectorstore/faiss"
EMBED_MODEL = OllamaEmbeddings(model="deepseek-r1:1.5b")

def load_pdf(path: str):
    """Load PDF pages into LangChain Document objects."""
    loader = PDFPlumberLoader(path)
    return loader.load()

def chunkify(docs):
    """Split documents into smaller chunks tuned for legal text."""
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    return splitter.split_documents(docs)

def embed_batch(texts):
    """Embed a list of strings in one batch call."""
    return EMBED_MODEL.embed_documents(texts)

def build_faiss_from_pdf(pdf_path: str, progress_callback=None):
    """
    Build a FAISS index:
      1. Load & chunk the PDF.
      2. Embed the first batch to bootstrap the index.
      3. Parallelize embedding of remaining batches.
      4. Save index locally.
    """
    # 1) Load and split
    docs   = load_pdf(pdf_path)
    chunks = chunkify(docs)

    # 2) Bootstrap with first non-empty batch
    batch_size    = 16
    total_batches = math.ceil(len(chunks) / batch_size)

    first_texts = [c.page_content for c in chunks[:batch_size]]
    first_embs  = embed_batch(first_texts)

    # Initialize FAISS index from these embeddings
    idx = FAISS.from_embeddings(
        zip(first_texts, first_embs),
        EMBED_MODEL
    )
    if progress_callback:
        progress_callback(1 / total_batches)

    # 3) Process remaining batches in parallel
    def process_batch(batch_idx):
        start = batch_idx * batch_size
        end   = min(start + batch_size, len(chunks))
        texts = [c.page_content for c in chunks[start:end]]
        embs  = embed_batch(texts)
        idx.add_documents(chunks[start:end], embs)
        if progress_callback:
            progress_callback((batch_idx + 1) / total_batches)

    with ThreadPoolExecutor(max_workers=4) as executor:
        # skip batch 0 since we already did it
        executor.map(process_batch, range(1, total_batches))

    # 4) Persist index
    os.makedirs(FAISS_DIR, exist_ok=True)
    idx.save_local(FAISS_DIR)
    return idx

def load_or_build_faiss(pdf_path: str, progress_callback=None):
    """
    Load an existing FAISS index if present, otherwise build from PDF.
    """
    if os.path.isdir(FAISS_DIR) and os.listdir(FAISS_DIR):
        return FAISS.load_local(
            FAISS_DIR,
            EMBED_MODEL,
            allow_dangerous_deserialization=True
        )
    else:
        return build_faiss_from_pdf(pdf_path, progress_callback=progress_callback)

def get_faiss_retriever():
    """
    Return a retriever configured for MMR (diverse results).
    """
    idx = FAISS.load_local(
        FAISS_DIR,
        EMBED_MODEL,
        allow_dangerous_deserialization=True
    )
    return idx.as_retriever(search_type="mmr", search_kwargs={"k": 10, "fetch_k": 20})
