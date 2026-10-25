"""Public search-only interface for the TLV700 datasheet."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

import streamlit as st


st.set_page_config(
    page_title="TLV700 Datasheet Assistant",
    layout="centered",
    initial_sidebar_state="collapsed",
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    from search import Search, load
except ImportError as exc:
    st.error(
        "Could not load src/search.py. "
        "Check that it exists and its dependencies are installed."
    )
    st.code(str(exc))
    st.stop()

CHUNKS = ROOT / "data" / "chunks" / "TLV700.jsonl"

EXAMPLES = {
    "Dropout voltage": (
        "What is the maximum dropout voltage at 200 mA?"
    ),
    "Enable input levels": (
        "What input voltage levels are specified for the EN pin "
        "to enable and disable the regulator?"
    ),
    "Output capacitor": (
        "What effective output capacitance is required, and does "
        "a capacitor rated at 0.1 µF necessarily ensure stability?"
    ),
}

st.markdown(
    """
    <style>
    .block-container {
        max-width: 900px;
        padding-top: 2.5rem;
        padding-bottom: 3rem;
    }
    h1 {
        font-size: 1.9rem !important;
        letter-spacing: -.035em;
    }
    [data-testid="stForm"] {
        border: 1px solid #e3e7eb;
        border-radius: 12px;
        padding: 1.1rem;
    }
    [data-testid="stExpander"] {
        border: 1px solid #e3e7eb;
        border-radius: 9px;
    }
    @media (max-width: 640px) {
        .block-container {padding: 1.4rem 1rem;}
        h1 {font-size: 1.6rem !important;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource(show_spinner=False)
def get_index(path, digest):
    """Reload the cached index when the chunk file changes."""
    return Search(load(path))


def execute_search(question, top_k):
    started = time.perf_counter()
    digest = hashlib.sha256(CHUNKS.read_bytes()).hexdigest()
    index = get_index(str(CHUNKS), digest)

    hits = index.query(question, top_k, "TLV700")

    return {
        "question": question,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "search",
        "top_k": top_k,
        "chunk_index_sha256": digest,
        "retrieved_evidence": hits,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def choose_question(question):
    st.session_state["question_input"] = question
    st.session_state.pop("search_result", None)


with st.sidebar:
    st.header("Search settings")
    top_k = st.slider("Maximum passages", 1, 8, 5)
    st.caption("Changes apply to your next search.")

st.title("TLV700 Datasheet Assistant")
st.caption("Search specifications and inspect the supporting passages.")
st.caption(
    "TLV700 · SLVSA00E · Text and tables only · Search-only demo"
)

if not CHUNKS.is_file():
    st.error(
        "Search index missing. Add data/chunks/TLV700.jsonl "
        "to your GitHub repository."
    )
    st.stop()

with st.form("search_form"):
    question = st.text_area(
        "Your question",
        key="question_input",
        height=95,
        placeholder="What is the maximum dropout voltage at 200 mA?",
    )
    submitted = st.form_submit_button("Search", type="primary")

with st.expander("Example questions"):
    for label, example in EXAMPLES.items():
        st.button(
            label,
            key=f"example_{label}",
            on_click=choose_question,
            args=(example,),
        )

if submitted:
    st.session_state.pop("search_result", None)
    cleaned_question = question.strip()

    if not cleaned_question:
        st.warning("Enter a question.")
    else:
        with st.spinner("Searching the datasheet…"):
            try:
                st.session_state["search_result"] = execute_search(
                    cleaned_question, top_k
                )
            except Exception as exc:
                st.error(
                    "Search failed. Check the chunk file and search.py."
                )
                with st.expander("Error details"):
                    st.code(str(exc))

result = st.session_state.get("search_result")

if result:
    st.divider()
    st.subheader("Matching passages")
    st.write(result["question"])

    hits = result["retrieved_evidence"]

    st.caption(
        f"{len(hits)} passage(s) · "
        f"{result['elapsed_seconds']:.2f} seconds"
    )

    if not hits:
        st.info(
            "No keyword matches found. Try a parameter name or "
            "different wording. This does not prove the PDF "
            "contains no answer."
        )
    else:
        st.caption(
            "Results are ranked by keyword relevance. "
            "A matching passage may not answer your question."
        )

        for rank, hit in enumerate(hits, start=1):
            section = hit.get("section") or "Unnamed section"
            name = hit.get("parameter_name") or section
            pages = ", ".join(
                str(page) for page in (hit.get("pages") or [])
            ) or "Unknown"

            with st.expander(
                f"{rank}. {name} · PDF pages {pages}",
                expanded=(rank == 1),
            ):
                st.markdown(
                    hit.get("text", ""),
                    unsafe_allow_html=False,
                )
                st.caption(section)
                st.code(
                    hit.get("chunk_id", "Unknown source ID"),
                    language=None,
                )

    with st.expander("Search details"):
        st.write(
            "This public demo retrieves passages only. "
            "It does not generate or verify answers."
        )
        st.json({
            "created_at": result["created_at"],
            "maximum_passages": result["top_k"],
            "returned_passages": len(hits),
        })

        st.download_button(
            "Download results",
            data=json.dumps(result, ensure_ascii=False, indent=2),
            file_name="datasheet_search_results.json",
            mime="application/json",
        )

st.caption(
    "Verify values and conditions against the original PDF. "
    "Figures and unreviewed appendices are excluded."
)
