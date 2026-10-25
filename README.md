# TLV700 Datasheet Assistant

A local RAG application for asking questions about the Texas Instruments TLV700 datasheet. It retrieves relevant text and tables, generates an answer using Ollama, and displays supporting passages with PDF page references.

## Features

- PDF extraction using Docling.
- Manually reviewed Markdown with source-page markers.
- Specification chunks preserving table headers, conditions, and footnotes.
- BM25 keyword retrieval.
- Local answer generation with `qwen3:8b`.
- Streamlit interface with supporting evidence and JSON downloads.
- Retrieval evaluation using labelled questions and expected chunk IDs.

## How It Works

PDF → Docling extraction → Manual review → Chunking → BM25 retrieval → Ollama → Answer and citations

Only retrieved chunks that fit the configured context budget are sent to the model. The interface identifies omitted passages.

## Tech Stack

Python · Docling · BM25 · Ollama · Qwen3 · Streamlit

## Project Structure

```text
datasheet_assistant/
├── app/
│   └── streamlit_app.py
├── src/
│   ├── chunk.py
│   ├── search.py
│   ├── evaluate.py
│   └── answer.py
├── data/
│   ├── raw/
│   ├── extracted/
│   ├── validated/
│   ├── chunks/
│   ├── evaluation/
│   └── answers/
└── .streamlit/
    └── config.toml
```

## Run Locally

Requires Python, Streamlit, Ollama, and the prepared chunk file at `data/chunks/TLV700.jsonl`.

From the project folder in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install streamlit

ollama pull qwen3:8b

python -m streamlit run app/streamlit_app.py --server.address 127.0.0.1
```

Keep Ollama running. The interface defaults to an 8192-token context setting; memory requirements depend on the model and configuration.

Docling and its dependencies are required separately to reprocess source PDFs.

## Example Questions

- What is the maximum dropout voltage at 200 mA?
- Which voltage levels enable and disable the regulator?
- What ground pin current is specified at no load?
- Does a capacitor rated at 0.1 µF necessarily ensure stability?

## Retrieval Evaluation

```powershell
python src/evaluate.py --chunks data/chunks/TLV700.jsonl --questions data/evaluation/questions.json --output data/evaluation/results.json
```

Recorded retrieval results after improvements:

| Question set | Questions scored | Hit@5 |
|---|---:|---:|
| Original | 9 | 9/9 |
| Additional | 10 | 10/10 |

Hit@5 checks whether at least one expected evidence chunk appears in the first five results. These small development sets were used during iteration; the results do not measure answer accuracy or generalisation. The unanswerable question in the original set is excluded from this retrieval metric.

## Limitations

- Currently covers one TLV700 datasheet.
- Figures and unreviewed appendix content are excluded from search.
- The model can confuse typical and maximum values, omit conditions, or select the wrong table row.
- Citation validation checks source IDs, not whether every claim is supported.
- Some retrieved passages may be excluded by the context budget.
- Current prices and other information outside the indexed datasheet are unavailable.

Verify technical values and conditions against the original PDF before using an answer in a design.

## Datasheet

Texas Instruments TLV700, document SLVSA00E, revision E, April 2015.