# TLV700 Datasheet Assistant

A datasheet question-answering project for the Texas Instruments TLV700 regulator. It retrieves relevant text and tables using BM25 and generates local answers using Ollama, with supporting passages and PDF page references.

## Two Interfaces

| Interface | Purpose |
|---|---|
| Public Streamlit demo | Search and inspect datasheet passages |
| Local Ollama app | Generate answers with citations and supporting evidence |

The public demo does not generate AI answers. Full answer generation runs locally using `qwen3:8b`.

## Features

- PDF extraction using Docling.
- Manually reviewed Markdown with source-page markers.
- Specification chunks preserving values, conditions, and footnotes.
- BM25 keyword retrieval.
- Local answer generation using Ollama.
- Expandable supporting evidence and JSON result downloads.
- Retrieval evaluation using questions with labelled evidence.

## Pipeline

PDF → Extraction → Manual review → Chunking → BM25 retrieval → Ollama → Answer with citations

The public demo stops at retrieval. The local app sends complete retrieved chunks to Ollama within the configured context budget.

## Tech Stack

Python · Docling · BM25 · Ollama · Qwen3 · Streamlit

## Project Structure

```text
datasheet_assistant/
├── app/
│   ├── streamlit_app.py       # Public search-only interface
│   ├── streamlit_local.py     # Local Ollama answer interface
│   └── requirements.txt
├── src/
│   ├── chunk.py
│   ├── search.py
│   ├── evaluate.py
│   └── answer.py
├── data/
│   ├── chunks/
│   │   └── TLV700.jsonl
│   └── evaluation/
├── .streamlit/
│   └── config.toml
└── README.md
```

## Setup

Requires Python and the prepared chunk file included in the repository.

Run in PowerShell:

```powershell
git clone https://github.com/AditiS721/datasheet_assistant.git
cd datasheet_assistant

python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install -r app/requirements.txt
```

### Run the Search Interface

```powershell
python -m streamlit run app/streamlit_app.py
```

This interface does not require Ollama.

### Run the Local Answer Interface

Install and open [Ollama](https://ollama.com), then download the model:

```powershell
ollama pull qwen3:8b
```

Start the app:

```powershell
python -m streamlit run app/streamlit_local.py --server.address 127.0.0.1
```

The local interface defaults to `qwen3:8b`, five retrieved passages, and an 8192-token context setting. Memory requirements depend on the model and context configuration.

Docling and its dependencies are needed separately to reprocess source PDFs.

## Example Questions

- What is the maximum dropout voltage at 200 mA?
- Which voltage levels enable and disable the regulator?
- What ground pin current is specified at no load?
- Does a capacitor rated at 0.1 µF necessarily ensure stability?

## Evaluation

Run retrieval evaluation:

```powershell
python src/evaluate.py --chunks data/chunks/TLV700.jsonl --questions data/evaluation/questions.json --output data/evaluation/results.json
```

Recorded retrieval results after improvements:

| Development question set | Questions scored | Hit@5 |
|---|---:|---:|
| Original | 9 | 9/9 |
| Additional | 10 | 10/10 |

Hit@5 measures whether at least one expected evidence chunk appears in the top five results. The original set also contains one unanswerable question, excluded from this metric.

These small sets were used during development. The scores measure retrieval, not generated-answer accuracy or performance on unseen questions.

## Limitations

- Currently covers one TLV700 datasheet.
- Figures and unreviewed appendix content are excluded.
- The model can confuse table columns, omit conditions, or select the wrong test-condition row.
- Citation checks validate source IDs, not factual support.
- Retrieved passages may be omitted when they exceed the context budget.
- Keyword matches do not guarantee that a question is answerable.
- The public demo cannot access Ollama running on a user's laptop.

Verify values and conditions against the original PDF before using an answer in a design.

## Source

Texas Instruments TLV700 datasheet, document SLVSA00E, revision E, April 2015.