#!/usr/bin/env python3
"""Replace reading lists with interview material and a second complete book."""
import collections
import csv
import hashlib
import json
import re
from pathlib import Path
from collect import ROOT, download, fetch

def main():
    manifest = ROOT/'metadata/manifest.jsonl'
    records=[json.loads(line) for line in manifest.read_text().splitlines()]
    if any(r['id']=='think-data-structures' for r in records):
        print('Curation already applied'); return
    removed=[r for r in records if r.get('original_path','').startswith('docs/books/')]
    assert len(removed)==6, len(removed)
    tree=json.loads((ROOT/'metadata/JavaGuide-tree.json').read_text())
    selected=[
        'backend-project-interview-guide.md', 'project-experience-guide.md',
        'internship-experience.md', 'key-points-of-interview.md',
        'teach-you-how-to-prepare-for-the-interview-hand-in-hand.md',
    ]
    additions=[]
    for filename in selected:
        path='docs/interview-preparation/'+filename
        x=next(x for x in tree['tree'] if x['path']==path)
        x=dict(x,**{k:tree[k] for k in ('repo','name','commit','license')})
        r=download(x);r['document_type']='interview_preparation_and_experience';additions.append(r)
    url='https://greenteapress.com/thinkdast/thinkdast.pdf'
    data=fetch(url);assert data.startswith(b'%PDF-') and len(data)>100000
    path=ROOT/'corpus/Books/Think_Data_Structures.pdf';path.write_bytes(data)
    additions.append(dict(id='think-data-structures',title='Think Data Structures: Algorithms and Information Retrieval in Java',
                          path=path.relative_to(ROOT).as_posix(),source='ThinkDataStructures',
                          source_url='https://greenteapress.com/wp/think-data-structures/',download_url=url,
                          license='CC-BY-NC-SA-3.0',bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),
                          format='pdf',language='en',document_type='complete_book',authors=['Allen B. Downey']))
    lic=ROOT/'licenses/ThinkDataStructures';lic.mkdir(exist_ok=True)
    (lic/'source.html').write_bytes(fetch('https://greenteapress.com/wp/think-data-structures/'))
    for r in removed:
        (ROOT/r['path']).unlink()
    (ROOT/'metadata/curation_excluded.json').write_text(json.dumps(removed,ensure_ascii=False,indent=2))
    records=[r for r in records if r not in removed]+additions
    assert len(records)==500
    for r in records:
        r['collection_date']='2026-11-13'
    manifest.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records))
    print('CURATED', len(records),dict(collections.Counter(r['source'] for r in records)))

if __name__=='__main__':main()
