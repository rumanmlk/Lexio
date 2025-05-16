import os
import streamlit as st
from rag_pipeline import retrieve_docs, answer_query, llm_model, build_or_load_faiss, get_retriever

# — Streamlit config —
st.set_page_config(page_title="Lexio – AI Lawyer Assistant", layout="wide")

# — Session state init —
if "pdf_path" not in st.session_state:
    st.session_state.pdf_path = None
if "faiss_indexed" not in st.session_state:
    st.session_state.faiss_indexed = False
# Reset chat history when a new file is uploaded
if "last_uploaded" not in st.session_state:
    st.session_state.last_uploaded = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

st.title("Lexio – AI Lawyer Assistant")

# — 1) Upload PDF —
uploaded_file = st.file_uploader("Upload your PDF", type="pdf")
if uploaded_file:
    os.makedirs("pdfs", exist_ok=True)
    dest = os.path.join("pdfs", uploaded_file.name)
    if st.session_state.pdf_path != dest:
        # New file: delete previous vectorstore so we re-index cleanly
        import shutil
        shutil.rmtree("vectorstore/faiss", ignore_errors=True)

        # Reset chat history & indexing state
        st.session_state.chat_history = []
        st.session_state.pdf_path = dest
        st.session_state.faiss_indexed = False
        st.session_state.last_uploaded = uploaded_file.name
        with open(dest, "wb") as f:
            f.write(uploaded_file.getbuffer())

# — 2) Index on first upload — on first upload —
if st.session_state.pdf_path and not st.session_state.faiss_indexed:
    with st.spinner("Indexing document…"):
        build_or_load_faiss(st.session_state.pdf_path)
    st.session_state.faiss_indexed = True

# — 3) Render chat history —
for msg in st.session_state.chat_history:
    st.chat_message(msg["role"]).write(msg["content"])

# — 4) User input & RAG call —
query = st.chat_input("Ask your legal question…")
if query:
    if not st.session_state.faiss_indexed:
        st.error("Please upload and index a PDF first.")
    else:
        # show user
        st.session_state.chat_history.append({"role": "user", "content": query})
        st.chat_message("user").write(query)

        # retrieve + answer
        retriever = get_retriever()
        docs = retrieve_docs(query)
        raw = answer_query(documents=docs, model=llm_model, query=query)

        # cleanup (same as before)
        import json, re
        from langchain.schema import AIMessage

        if isinstance(raw, AIMessage):
            text = raw.content
        else:
            try:
                payload = json.loads(raw)
                text = payload.get("content", "")
            except Exception:
                text = str(raw)
        clean = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

        # show AI
        st.session_state.chat_history.append({"role": "assistant", "content": clean})
        st.chat_message("assistant").write(clean)
