"""Evaluate retrieval with manually assigned relevant chunk IDs."""
import argparse,json
from pathlib import Path
from search import Search,load

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--chunks',default='data/chunks/TLV700.jsonl')
    p.add_argument('--questions',required=True,type=Path)
    p.add_argument('--output',type=Path,default=Path('data/evaluation/results.json'))
    a=p.parse_args();chunks=load(a.chunks);index=Search(chunks);ids={c['chunk_id'] for c in chunks}
    questions=json.loads(a.questions.read_text(encoding='utf-8-sig'))
    rows=[];hits=0;evaluated=0
    for q in questions:
        results=index.query(q['question'],5,q.get('part_family'))
        expected=set(q.get('expected_chunk_ids',[]));hit=None
        if expected-ids:raise ValueError(f"{q['id']}: unknown chunk IDs {expected-ids}; update labels after rechunking")
        if q.get('answerable',True) and expected:
            hit=bool(expected & {r['chunk_id'] for r in results});hits+=int(hit);evaluated+=1
        rows.append({'id':q['id'],'question':q['question'],'hit_at_5':hit,
            'note':'Not scored without gold IDs or for unanswerable questions' if hit is None else '',
            'retrieved':[{'chunk_id':r['chunk_id'],'pages':r['pages'],'score':r['score']} for r in results]})
    summary={'evaluated':evaluated,'hit_at_5':hits/evaluated if evaluated else None,'results':rows}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    print(f'Scored {evaluated} questions; hits {hits}; results: {a.output}')
    if not evaluated:print('Add manually verified expected_chunk_ids before claiming an accuracy score.')

if __name__=='__main__':main()
