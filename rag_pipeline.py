from langchain_groq import ChatGroq
from vector_database import load_or_build_faiss, get_faiss_retriever
from langchain_core.prompts import ChatPromptTemplate

# 1) LLM setup
llm_model = ChatGroq(model="deepseek-r1-distill-llama-70b")

# 2) Build or load the FAISS index when given a pdf path
def build_or_load_faiss(pdf_path: str):
    return load_or_build_faiss(pdf_path)

# 3) Get a retriever for queries
def get_retriever():
    return get_faiss_retriever()

# 4) Retrieve docs via retriever
def retrieve_docs(query, k: int = 10):
    retriever = get_retriever()
    return retriever.get_relevant_documents(query)

# 5) Context builder
def get_context(documents):
    return "\n\n".join([d.page_content for d in documents])

# 6) QA prompt & chain
custom_prompt_template = """
You are Lexio, an AI lawyer assistant. Use ONLY the provided context to answer.
If the answer is not in context, say “I don’t know.”
Question: {question}
Context: {context}
Answer:
"""

def answer_query(documents, model, query):
    context = get_context(documents)
    prompt = ChatPromptTemplate.from_template(custom_prompt_template)
    chain = prompt | model
    return chain.invoke({"question": query, "context": context})
