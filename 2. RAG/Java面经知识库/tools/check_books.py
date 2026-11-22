#!/usr/bin/env python3
"""Read every PDF page, render a sample, and cache per-file QA by SHA-256."""
import hashlib
import json
import logging
import re
import subprocess
from pathlib import Path
from pypdf import PdfReader
import pypdfium2 as pdfium
from collect import ROOT

QA=Path('/tmp/java-backend-books-qa')

def check(path):
    rel=path.relative_to(ROOT).as_posix();sha=hashlib.sha256(path.read_bytes()).hexdigest()
    bid=path.stem;dest=ROOT/'metadata/pdf_checks'/(bid+'.json')
    if dest.exists():
        old=json.loads(dest.read_text())
        if old.get('sha256')==sha:return old
    reader=PdfReader(path,strict=True)
    lengths=[];rights=[]
    # PDFium avoids pathological token-stream parsing in graphics-heavy handbooks.
    document=pdfium.PdfDocument(path)
    assert len(document)==len(reader.pages)
    for i in range(len(document)):
        page=document[i];textpage=page.get_textpage();text=textpage.get_text_range()
        textpage.close();page.close()
        lengths.append(len(text.strip()))
        if i<15 or i>=len(reader.pages)-20:
            for m in re.finditer(r'creative\s*commons|permission is|licensed under|copyright',text,re.I):
                rights.append(re.sub(r'\s+',' ',text[max(0,m.start()-30):m.start()+450]))
    document.close()
    assert sum(lengths)>10000,(rel,sum(lengths))
    sample=max(1,len(reader.pages)//3)
    subprocess.run(['pdftoppm','-f',str(sample),'-l',str(sample),'-scale-to','800','-singlefile','-png',str(path),str(QA/bid)],check=True,capture_output=True)
    row=dict(path=rel,sha256=sha,pages=len(reader.pages),extracted_characters=sum(lengths),pages_with_text=sum(x>0 for x in lengths),
             strict_pdf_parse=True,text_extraction_engine='PDFium',sample_render_page=sample,sample_image=str(QA/(bid+'.png')),rights_excerpts=rights)
    dest.write_text(json.dumps(row,ensure_ascii=False,indent=2))
    print('QA_OK',bid,len(reader.pages),'pages',sum(lengths),'characters',flush=True)
    return row

def main():
    logging.getLogger('pypdf').setLevel(logging.ERROR)
    QA.mkdir(exist_ok=True);(ROOT/'metadata/pdf_checks').mkdir(exist_ok=True)
    files=sorted((ROOT/'corpus/Books').rglob('*.pdf'))
    # PDFium has process-global state and must not run in concurrent threads.
    results=[check(path) for path in files]
    (ROOT/'metadata/pdf_verification.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    print('PDF_QA_COMPLETE',len(results),'PDFs',sum(x['pages'] for x in results),'pages',flush=True)

if __name__=='__main__':main()
