#!/usr/bin/env python3
"""Validate delivered files and regenerate human-readable catalogue and statistics."""
import collections
import csv
import hashlib
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def topic(r):
    p=r.get('original_path','').lower()
    if r['document_type'] in ('complete_book','research_monograph'):return r.get('subject','完整书籍')
    if 'interview-preparation' in p:return '面试准备与经验'
    if r['source']=='SpringFramework':return 'Spring官方参考'
    if any(s in p for s in ('jvm','garbage','gc-','class-load','hotspot')):return 'JVM与内存管理'
    if any(s in p for s in ('concurrent','thread','juc','并发','线程')):return '并发与多线程'
    if any(s in p for s in ('database','mysql','redis','sql','mongodb','elastic')):return '数据库与缓存'
    if any(s in p for s in ('distributed','high-availability','high-performance','high-concurrency','micro-service')):return '分布式与高并发'
    if any(s in p for s in ('network','tcp','http','netty')):return '网络与通信'
    if 'operating-system' in p:return '操作系统'
    if any(s in p for s in ('algorithm','data-structure','big-data','leetcode')):return '算法与数据结构'
    if any(s in p for s in ('spring','framework','mybatis','design-pattern','system-design')):return '框架与系统设计'
    if any(s in p for s in ('java','collection','io/','container')):return 'Java基础与核心'
    return '开发工具与计算机基础'

def main():
    manifest=ROOT/'metadata/manifest.jsonl'
    records=[json.loads(s) for s in manifest.read_text().splitlines()]
    assert len(records)>=500
    actual={p.relative_to(ROOT).as_posix() for p in (ROOT/'corpus').rglob('*') if p.is_file()}
    expected={r['path'] for r in records}
    assert actual==expected,dict(extra=sorted(actual-expected),missing=sorted(expected-actual))
    exact=set();normalized=set();minimum=None;pdfs=[]
    trees={}
    for p in (ROOT/'metadata').glob('*-tree.json'):
        tree=json.loads(p.read_text())
        trees[tree['name']]={x['path']:x for x in tree['tree'] if x['type']=='blob'}
    for r in records:
        path=ROOT/r['path'];data=path.read_bytes();sha=hashlib.sha256(data).hexdigest()
        assert sha==r['sha256'],r['path']
        assert len(data)==r['bytes']
        if 'original_path' in r:
            blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
            expected_blob=trees[r['source']][r['original_path']]['sha']
            assert blob==expected_blob, 'upstream blob mismatch: '+r['path']
            r['git_blob_sha1']=blob
        assert sha not in exact,'duplicate bytes: '+r['path']
        exact.add(sha)
        if r['format']=='pdf':
            assert data.startswith(b'%PDF-') and b'%%EOF' in data[-4096:]
            pdfs.append(r['path'])
        else:
            text=data.decode('utf-8-sig')
            compact=re.sub(r'\s+','',text)
            assert len(compact)>=500 and len(data)>=1800
            digest=hashlib.sha256(compact.encode()).hexdigest()
            assert digest not in normalized,'duplicate text: '+r['path']
            normalized.add(digest)
            minimum=min(minimum or len(compact),len(compact))
            r['external_image_count']=len(re.findall(r'!\[[^\]]*\]\(',text))
            r['asciidoc_include_count']=len(re.findall(r'^\s*include::',text,re.M))
        r['topic']=topic(r)
    stats=dict(total_files=len(records),total_bytes=sum(r['bytes'] for r in records),
               book_pdf_count=sum(r['format']=='pdf' for r in records),
               book_pdf_page_total=sum(r.get('pages',0) for r in records if r['format']=='pdf'),
               by_source=dict(collections.Counter(r['source'] for r in records)),
               by_format=dict(collections.Counter(r['format'] for r in records)),
               by_language=dict(collections.Counter(r['language'] for r in records)),
               by_topic=dict(collections.Counter(r['topic'] for r in records)),
               exact_duplicate_files=0,whitespace_normalized_duplicate_text_files=0,
               upstream_git_blob_checks=sum('original_path' in r for r in records),
               minimum_nonwhitespace_characters=minimum,
               documents_with_external_images=sum(r.get('external_image_count',0)>0 for r in records),
               documents_with_unexpanded_asciidoc_includes=sum(r.get('asciidoc_include_count',0)>0 for r in records),
               pdfs=pdfs)
    manifest.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records))
    (ROOT/'metadata/verification.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2))
    with (ROOT/'metadata/文件清单.csv').open('w',encoding='utf-8-sig',newline='') as f:
        fields=['id','title','title_zh','topic','subject','source','document_type','language','format','pages','bytes','license','path','source_url','sha256']
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(records)
    lines=['# Java 与后端知识库目录','',f'共 {len(records)} 份原始正文文件。书籍按整本计数，文章按上游原始文件计数。','']
    for source in stats['by_source']:
        lines.extend(['## '+source,''])
        for r in sorted((r for r in records if r['source']==source),key=lambda r:r['path']):
            title = r['title'].replace('[', '').replace(']', '')
            lines.append(f"- [{title}](<{r['source_url']}>) · {r['topic']}")
        lines.append('')
    (ROOT/'目录.md').write_text('\n'.join(lines))
    print(json.dumps(stats,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
