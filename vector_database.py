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
EMBED_MODEL = OllamaEmbeddings(model="nomic-embed-text")

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
      2. Embed batches in parallel.
      3. Build the index from all chunks, keeping metadata.
      4. Save index locally.
    """
    # 1) Load and split
    docs   = load_pdf(pdf_path)
    chunks = chunkify(docs)

    if not chunks:
        raise ValueError(f"No extractable text found in {pdf_path}")

    # 2) Embed all batches in parallel (results kept in order)
    batch_size    = 16
    total_batches = math.ceil(len(chunks) / batch_size)
    done          = 0

    def process_batch(batch_idx):
        nonlocal done
        start = batch_idx * batch_size
        texts = [c.page_content for c in chunks[start:start + batch_size]]
        embs  = embed_batch(texts)
        done += 1
        if progress_callback:
            progress_callback(done / total_batches)
        return embs

    with ThreadPoolExecutor(max_workers=4) as executor:
        # list() consumes the iterator so worker exceptions are raised here
        batch_embs = list(executor.map(process_batch, range(total_batches)))

    all_embs = [e for batch in batch_embs for e in batch]

    # 3) Build the index with chunk text, embeddings and metadata (page, source)
    idx = FAISS.from_embeddings(
        [(c.page_content, e) for c, e in zip(chunks, all_embs)],
        EMBED_MODEL,
        metadatas=[c.metadata for c in chunks],
    )

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
