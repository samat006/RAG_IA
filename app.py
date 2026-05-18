import streamlit as st
from legal_rag.pipeline import IngestionPipeline
from legal_rag.generation import AnswerGenerator

st.set_page_config(page_title="Assistant RAG — Corte", page_icon="🏛️", layout="centered")

st.title("🏛️ Assistant RAG — Corte")
st.caption("Posez votre question sur le tourisme, l'hébergement et les activités de Corte.")

@st.cache_resource(show_spinner="Chargement du corpus…")
def load():
    pipeline = IngestionPipeline(collection_name="legal_corpus_m2_tp", retriever_type="recursive")
    pipeline.ingest_corpus("./documents/test")
    return pipeline, AnswerGenerator()

pipeline, generator = load()

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if query := st.chat_input("Votre question…"):
    st.session_state.messages.append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.markdown(query)

    with st.chat_message("assistant"):
        with st.spinner("Recherche…"):
            results = pipeline.search(query=query.strip(), n_results=5)

        no_ids = not results or not results.get("ids") or not results["ids"][0]
        if no_ids:
            st.warning("Aucun document trouvé pour cette question.")
            st.session_state.messages.append({"role": "assistant", "content": "⚠️ Aucun document trouvé."})

        else:
            context = generator.build_context(results)
            if not context:
                st.warning("Les passages trouvés ne sont pas assez pertinents pour répondre.")
                st.session_state.messages.append({"role": "assistant", "content": "⚠️ Passages non pertinents."})

            else:
                with st.spinner("Génération…"):
                    answer = generator.generate_answer(query.strip(), results)

                st.markdown(answer)

                distances = results.get("distances", [[]])[0]
                sources = []
                for i, meta in enumerate(results["metadatas"][0]):
                    dist = distances[i] if i < len(distances) else None
                    src = meta.get("source_file", "?").split("/")[-1]
                    dist_str = f" · {dist:.2f}" if dist is not None else ""
                    sources.append(f"`{src}{dist_str}`")

                if sources:
                    st.caption("Sources : " + "  ".join(sources))

                st.session_state.messages.append({"role": "assistant", "content": answer})

if st.session_state.messages:
    if st.button("🗑️ Effacer", type="secondary"):
        st.session_state.messages = []
        st.rerun()
