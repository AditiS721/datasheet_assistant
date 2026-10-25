"""Dependency-free BM25 evidence search; scores are relevance, not confidence."""
import argparse
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

STOP=set('a an the is are was what which how does do for of at to in and or with me tell please'.split())
def tokenize(text):
    text=unicodedata.normalize('NFKC',text).casefold().replace('μ','u').replace('µ','u')
    # Make 200mA and 200 mA searchable using the same tokens.
    text=re.sub(r'(\d)([a-z])',r'\1 \2',text)
    return [w for w in re.findall(r'[a-z]+\d+[a-z\d]*|[a-z]+|\d+(?:\.\d+)?',text) if w not in STOP]

class Search:
    def __init__(self,chunks):
        if not chunks:raise ValueError('Chunk file is empty')
        ids=[c['chunk_id'] for c in chunks]
        if len(set(ids))!=len(ids):raise ValueError('Duplicate chunk IDs')
        self.chunks=chunks
        self.terms=[Counter(tokenize(c['text'])) for c in chunks]
        self.lengths=[sum(t.values()) for t in self.terms]
        self.average=sum(self.lengths)/len(chunks) or 1
        self.df=Counter(term for bag in self.terms for term in bag)
    def query(self,question,top_k=5,family=None):
        query=set(tokenize(question)); scored=[]; n=len(self.chunks)
        for chunk,bag,length in zip(self.chunks,self.terms,self.lengths):
            if family and chunk['part_family'].casefold()!=family.casefold():continue
            score=0.0
            for term in query:
                tf=bag[term]
                if not tf:continue
                idf=math.log(1+(n-self.df[term]+0.5)/(self.df[term]+0.5))
                score+=idf*(tf*2.5)/(tf+1.5*(0.25+0.75*length/self.average))
            if score>0:scored.append({'score':score,**chunk})
        return sorted(scored,key=lambda c:(-c['score'],c['chunk_id']))[:top_k]

def load(path):
    chunks=[]
    for number,line in enumerate(Path(path).read_text(encoding='utf-8-sig').splitlines(),1):
        if line.strip():
            try:chunks.append(json.loads(line))
            except json.JSONDecodeError as e:raise ValueError(f'Invalid JSON on line {number}: {e}') from e
    return chunks

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--chunks',type=Path,default=Path('data/chunks/TLV700.jsonl'))
    p.add_argument('--query')
    p.add_argument('--top-k',type=int,default=5)
    p.add_argument('--family')
    p.add_argument('--json',action='store_true',help='Print complete results as JSON')
    p.add_argument('--full',action='store_true',help='Show entire chunk instead of preview')
    a=p.parse_args()
    if a.top_k<1:p.error('top-k must be positive')
    index=Search(load(a.chunks))
    def run(question):
        hits=index.query(question,a.top_k,a.family)
        if a.json:print(json.dumps(hits,ensure_ascii=False,indent=2));return
        if not hits:print('No keyword matches. This does not establish that the PDF has no answer.')
        for rank,h in enumerate(hits,1):
            print(f"\n{rank}. {h['chunk_id']} | score={h['score']:.3f}")
            print(f"{h['section']} | PDF pages {h['pages']} | {h['type']}")
            print(h['text'] if a.full else h['text'][:1800])
    if a.query:run(a.query)
    else:
        while True:
            try:q=input('\nQuestion (or quit): ').strip()
            except (EOFError,KeyboardInterrupt):break
            if q.casefold() in {'quit','exit'}:break
            if q:run(q)

if __name__=='__main__':main()
