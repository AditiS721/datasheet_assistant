"""Local interface for the existing datasheet search and Ollama answer modules."""
from datetime import datetime, timezone
import html
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.request import urlopen

import streamlit as st

st.set_page_config(page_title='TLV700 Datasheet Assistant', layout='centered', initial_sidebar_state='collapsed')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
try:
    from search import Search, load
    from answer import pack, ask
except ImportError as exc:
    st.error('Place this file in app/ beside your existing src/ folder. '
             'src/search.py and the Ollama version of src/answer.py are required.')
    st.stop()

CHUNKS = ROOT / 'data' / 'chunks' / 'TLV700.jsonl'
EXAMPLES = {
    'Write my own question': '',
    'Dropout voltage': 'What is the maximum dropout voltage at 200 mA?',
    'Enable input ranges': 'What input voltage levels are specified for the EN pin to enable and disable the regulator?',
    'Output capacitor': 'What effective output capacitance is required, and does a capacitor rated at 0.1 µF necessarily ensure stability?',
    'Missing information': 'What is the price of ten TLV700 devices today?',
}


def citation_sources(answer, evidence):
    """Map cited IDs ONLY to evidence actually sent; reject missing sources."""
    lookup = {h['chunk_id']: h for h in evidence}
    mapped = []
    for claim in answer['claims']:
        sources = []
        for ident in dict.fromkeys(claim['evidence_ids']):
            if ident not in lookup:
                raise ValueError('Answer contains a citation outside the supplied evidence.')
            sources.append(lookup[ident])
        mapped.append((claim['text'], sources))
    return mapped


@st.cache_resource(show_spinner=False)
def get_index(path, digest):
    # Digest invalidates the index when chunk contents change.
    return Search(load(path))


def execute(question, model, context, output_tokens, top_k, search_only):
    index_digest = hashlib.sha256(CHUNKS.read_bytes()).hexdigest()
    index = get_index(str(CHUNKS), index_digest)
    started = time.perf_counter()
    hits = index.query(question, top_k, 'TLV700')
    record = {
        'question': question, 'created_at': datetime.now(timezone.utc).isoformat(),
        'mode': 'search' if search_only else 'answer', 'model': model,
        'context_limit': context, 'max_output': output_tokens,
        'chunk_index_sha256': index_digest, 'retrieved_evidence': hits,
        'sent_evidence': [], 'omitted_chunk_ids': [], 'answer': None, 'statistics': {},
    }
    if not hits:
        record['notice'] = 'No keyword matches. This does not prove the PDF has no answer.'
    elif not search_only:
        evidence, omitted = pack(question, hits, context, output_tokens)
        record['sent_evidence'] = evidence
        record['omitted_chunk_ids'] = omitted
        if not evidence:
            raise RuntimeError('No complete evidence chunk fits. Increase context size or use search-only mode.')
        answer, statistics = ask(question, evidence, model, context, output_tokens, 180)
        citation_sources(answer, evidence)
        record['answer'], record['statistics'] = answer, statistics
    record['elapsed_seconds'] = round(time.perf_counter() - started, 2)
    return record


st.markdown('''<style>
.block-container {max-width:900px;padding-top:2.5rem;padding-bottom:3rem;}
h1 {font-size:1.9rem!important;letter-spacing:-.035em;}
h2,h3 {letter-spacing:-.02em;}
[data-testid="stForm"] {border:1px solid #e3e7eb;border-radius:12px;padding:1.1rem;}
[data-testid="stExpander"] {border:1px solid #e3e7eb;border-radius:9px;}
.stButton button,.stDownloadButton button {border-radius:8px;}
.answer {border-left:3px solid #16796b;padding:0 0 0 1.1rem;margin:1rem 0;}
.claim {font-size:1.02rem;line-height:1.7;white-space:pre-wrap;overflow-wrap:anywhere;margin:0 0 .4rem;}
.source {font-size:.8rem;color:#52616d;margin:0 0 1rem;}
@media(max-width:640px){.block-container{padding:1.4rem 1rem;}h1{font-size:1.6rem!important;}}
</style>''', unsafe_allow_html=True)


def choose_question(text):
    st.session_state['question_input'] = text
    st.session_state.pop('result', None)


def answer_html(answer, evidence):
    parts = ['<div class="answer">']
    for text, sources in citation_sources(answer, evidence):
        parts.append('<p class="claim">' + html.escape(text) + '</p>')
        for source in sources:
            pages = ', '.join(map(str, source.get('pages', []))) or 'Unknown'
            parts.append('<div class="source">PDF pages ' + html.escape(pages) + ' · ' + html.escape(source['section']) + '</div>')
    return ''.join(parts) + '</div>'


with st.sidebar:
    st.header('Settings')
    search_only = st.checkbox('Search without generating an answer', value=False)
    model = st.text_input('Ollama model', value='qwen3:8b')
    context = st.selectbox('Context size', [4096, 8192, 12288, 16384], index=1)
    top_k = st.slider('Retrieved passages', 1, 8, 5)
    output_tokens = st.selectbox('Maximum output tokens', [768, 1024, 1536])
    st.caption('Changes apply to your next question.')
    if st.button('Check Ollama connection'):
        try:
            with urlopen('http://127.0.0.1:11434/api/tags', timeout=5) as response:
                tags = json.load(response)
            st.success('Ollama is reachable.')
            st.caption('Installed: ' + ', '.join(m['name'] for m in tags.get('models', [])))
        except Exception:
            st.error('Open Ollama and try again.')

st.title('TLV700 Datasheet Assistant')
st.caption('Ask about specifications. Check the supporting passages.')
st.caption('TLV700 · SLVSA00E · Local Ollama answers · Text and tables only')

if not CHUNKS.is_file():
    st.error('Search index missing. Run chunk.py to create data/chunks/TLV700.jsonl.')
    st.stop()

with st.form('ask_form'):
    question = st.text_area('Your question', key='question_input', height=95,
                            placeholder='What is the maximum dropout voltage at 200 mA?')
    submit = st.form_submit_button('Search' if search_only else 'Ask', type='primary')

with st.expander('Example questions'):
    for label in ['Dropout voltage', 'Enable input ranges', 'Output capacitor', 'Missing information']:
        st.button(label, on_click=choose_question, args=(EXAMPLES[label],))

if submit:
    st.session_state.pop('result', None)
    if not question.strip():
        st.warning('Enter a question.')
    elif not model.strip() and not search_only:
        st.warning('Enter an installed model name in Settings.')
    else:
        with st.spinner('Searching…' if search_only else 'Preparing your answer…'):
            try:
                st.session_state['result'] = execute(question.strip(), model.strip(), context, output_tokens, top_k, search_only)
            except Exception as exc:
                st.error('Could not complete the request. Check that Ollama is running and the selected model is installed.')
                with st.expander('Error details'):
                    st.code(str(exc))

result = st.session_state.get('result')
if result:
    st.divider()
    st.subheader('Search results' if result['mode'] == 'search' else 'Answer')
    # Keep the submitted question visible even when the input is edited.
    st.caption(result['question'])
    answer = result['answer']
    cited_ids = {ident for claim in (answer or {}).get('claims', []) for ident in claim['evidence_ids']}
    sent_ids = {h['chunk_id'] for h in result['sent_evidence']}
    if result.get('notice'):
        st.info(result['notice'])
    if answer:
        if answer['insufficient_evidence']:
            st.info('Insufficient evidence: ' + answer['missing_information'])
        else:
            st.markdown(answer_html(answer, result['sent_evidence']), unsafe_allow_html=True)
    if result['omitted_chunk_ids']:
        st.caption(f"{len(result['omitted_chunk_ids'])} retrieved passage(s) did not fit in the model context. They are marked below.")
    st.caption(f"{result['elapsed_seconds']:.1f} seconds · " + ('Search only' if result['mode'] == 'search' else result['model']))

    st.subheader('Supporting evidence')
    for rank, hit in enumerate(result['retrieved_evidence'], 1):
        status = ('Search result' if result['mode'] == 'search' else 'Used as context' if hit['chunk_id'] in sent_ids else 'Not sent to model')
        if hit['chunk_id'] in cited_ids:
            status = 'Cited'
        name = hit.get('parameter_name') or hit['section']
        pages = ', '.join(map(str, hit.get('pages', []))) or 'Unknown'
        with st.expander(f"{rank}. {name} · PDF pages {pages} · {status}"):
            st.markdown(hit['text'], unsafe_allow_html=False)
            st.caption(hit['section'])
            st.code(hit['chunk_id'], language=None)

    with st.expander('Result details'):
        st.caption('Citations link to supplied passages; they do not verify the answer’s accuracy.')
        st.json({'model': result['model'], 'context_size': result['context_limit'],
                 'created_at': result['created_at'], 'omitted_chunk_ids': result['omitted_chunk_ids'],
                 'statistics': result['statistics']})
        st.download_button('Download result (JSON)', data=json.dumps(result, ensure_ascii=False, indent=2),
                           file_name='datasheet_answer.json', mime='application/json')

st.caption('Verify values and conditions against the original PDF. Figures and unreviewed appendices are excluded.')
with st.expander('Known limitation'):
    st.write('The model can confuse table columns or select the wrong test-condition row, including shutdown current. '
             'Check the cited table before using an answer in a design.')
