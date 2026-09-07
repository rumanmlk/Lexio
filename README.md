# Lexio

Document-grounded legal Q&A. Upload a PDF, index it locally, then ask questions that are answered only from retrieved chunks.

This is a personal prototype, not legal advice.

## What it does

1. Upload a PDF in Streamlit (`frontend.py`).
2. Split the text (chunk size 500, overlap 50) and embed with Ollama (`deepseek-r1:1.5b`).
3. Store vectors in a local FAISS index (`vectorstore/faiss`).
4. Retrieve with MMR (`k=10`) and answer with Groq (`deepseek-r1-distill-llama-70b`) via LangChain.

## Stack

Python · Streamlit · LangChain · FAISS · pdfplumber · Ollama · Groq

## Setup

**Needs:** Python 3.11+, [Ollama](https://ollama.com) running locally, and a [Groq API key](https://console.groq.com).

```bash
ollama pull deepseek-r1:1.5b
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

```

Set `GROQ_API_KEY` in your environment (or a `.env` file in the repo root).

```bash
streamlit run frontend.py
```

Upload a PDF, wait for indexing, then ask questions in the chat box.

## Layout

| File | Role |
| --- | --- |
| `frontend.py` | Streamlit UI, upload, chat |
| `vector_database.py` | PDF load, chunk, embed, FAISS |
| `rag_pipeline.py` | Retriever + Groq QA prompt |

MIT.
