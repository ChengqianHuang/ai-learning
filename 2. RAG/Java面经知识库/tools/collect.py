#!/usr/bin/env python3
"""Download original documents at pinned commits; never split articles to inflate count."""
import concurrent.futures as cf
import collections
import hashlib
import json
import re
import subprocess
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    ('Snailclimb/JavaGuide', 'JavaGuide', 'Apache-2.0', 320),
    ('doocs/advanced-java', 'AdvancedJava', 'CC-BY-SA-4.0', 100),
    ('dunwu/javacore', 'JavaCore', 'CC-BY-SA-4.0', 100),
    ('doocs/jvm', 'JVM', 'CC-BY-SA-4.0', 30),
    ('spring-projects/spring-framework', 'SpringFramework', 'Apache-2.0', 150),
]

def fetch(url):
    # A fresh process per attempt discards partial stdout from failed transfers.
    for attempt in range(4):
        result = subprocess.run(['curl', '-fLsS',
                                 '--connect-timeout', '15', '--max-time', '90',
                                 '-H', 'User-Agent: Java-RAG-Learning-Corpus', url],
                                capture_output=True)
        if result.returncode == 0:
            return result.stdout
        if attempt == 3:
            raise RuntimeError(result.stderr.decode(errors='replace'))
        time.sleep(attempt+1)

def api(path):
    return json.loads(fetch('https://api.github.com/' + path))

def inspect_source(spec):
    repo, name, license_id, cap = spec
    cache = ROOT / 'metadata' / (name + '-tree.json')
    if cache.exists():
        info = json.loads(cache.read_text())
    else:
        meta = api('repos/' + repo)
        commit = api('repos/' + repo + '/commits/' + meta['default_branch'])['sha']
        tree = api('repos/' + repo + '/git/trees/' + commit + '?recursive=1')
        assert not tree.get('truncated'), repo + ': truncated tree'
        info = dict(repo=repo, name=name, commit=commit, license=license_id,
                    declared_license=meta.get('license'), tree=tree['tree'])
        cache.write_text(json.dumps(info, ensure_ascii=False, indent=2))
    docs = []
    for x in info['tree']:
        p = x['path']; low = p.lower()
        if x['type'] != 'blob' or x.get('size', 0) < 1800:
            continue
        if low.endswith(('readme.md', 'index.md')):
            continue
        if name == 'JavaGuide':
            if not low.startswith(('docs/java/', 'docs/database/', 'docs/system-design/',
                                   'docs/cs-basics/', 'docs/high-performance/',
                                   'docs/high-availability/', 'docs/distributed-system/',
                                   'docs/framework/', 'docs/tools/', 'docs/books/',
                                   'docs/algorithms/', 'docs/collection/',
                                   'docs/interview-experience/')) or not low.endswith('.md'):
                continue
        elif name in ('AdvancedJava', 'JVM', 'JavaCore'):
            if not low.startswith('docs/') or not low.endswith('.md'):
                continue
        elif name == 'SpringFramework':
            if not low.startswith('framework-docs/modules/root/pages/') or not low.endswith('.adoc'):
                continue
            if not any('/'+s+'/' in low for s in ('core', 'data-access', 'web', 'integration', 'testing')):
                continue
        docs.append(dict(x, **{k: info[k] for k in ('repo', 'name', 'commit', 'license')}))
    # Prefer substantive documents while keeping original file boundaries.
    docs.sort(key=lambda x: (-x['size'], x['path']))
    docs = docs[:cap]
    for x in info['tree']:
        if x['type'] == 'blob' and (x['path'].upper() in ('LICENSE', 'LICENSE.TXT', 'LICENSE.MD', 'NOTICE', 'NOTICE.TXT') or x['path'] == 'README.md'):
            target = ROOT / 'licenses' / name / x['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(fetch(raw_url(info, x['path'])))
    return info, docs

def raw_url(info, path):
    return 'https://raw.githubusercontent.com/' + info['repo'] + '/' + info['commit'] + '/' + urllib.parse.quote(path)

def document_title(text, path):
    front_matter = re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)', text, re.DOTALL)
    if front_matter:
        title = re.search(r'^title:[ \t]*(\S[^\r\n]*)', front_matter[1], re.MULTILINE)
        if title:
            value = title[1].strip()
            if len(value) >= 2 and value[0] in "\"'" and value[0] == value[-1]:
                return value[1:-1]
            return value
        text = text[front_matter.end():]

    pattern = r'^=[ \t]+(.+)' if Path(path).suffix == '.adoc' else r'^#[ \t]+(.+)'
    heading = re.search(pattern, text, re.MULTILINE)
    return heading[1].strip() if heading else Path(path).stem

def download(x):
    url = raw_url(x, x['path'])
    dest = ROOT / 'corpus' / x['name'] / x['path']
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = dest.read_bytes() if dest.exists() else fetch(url)
    blob_sha = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
    if blob_sha != x['sha']:
        data = fetch(url)
        blob_sha = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
    assert blob_sha == x['sha'], 'upstream git blob mismatch: '+x['path']
    text = data.decode('utf-8-sig')
    if len(data) < 1800 or len(re.sub(r'\s+', '', text)) < 500:
        raise ValueError('insufficient text: ' + x['path'])
    if text.lstrip().lower().startswith(('<!doctype html', '<html', '404: not found')):
        raise ValueError('not a document: ' + x['path'])
    dest.write_bytes(data)
    title = document_title(text, x['path'])
    return dict(id=hashlib.sha256((x['repo']+'/'+x['path']).encode()).hexdigest()[:16],
                title=title, path=dest.relative_to(ROOT).as_posix(), source=x['name'],
                repository=x['repo'], original_path=x['path'], commit=x['commit'],
                source_url='https://github.com/'+x['repo']+'/blob/'+x['commit']+'/'+urllib.parse.quote(x['path']),
                download_url=url, license=x['license'], bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                normalized_sha256=hashlib.sha256(re.sub(r'\s+', '', text).encode()).hexdigest(),
                format=dest.suffix.lstrip('.'), language='en' if x['name']=='SpringFramework' else 'zh',
                document_type='official_reference' if x['name']=='SpringFramework' else 'interview_and_technical_guide')

def main():
    existing=ROOT/'metadata/manifest.jsonl'
    if existing.exists() and len(existing.read_text().splitlines())>500:
        raise SystemExit('Corpus has book extensions. Use tools/add_books.py to extend; tools/verify.py to verify. Base collector will not overwrite an expanded manifest.')
    infos = []; candidates = []
    with cf.ThreadPoolExecutor(max_workers=5) as pool:
        for info, docs in pool.map(inspect_source, SOURCES):
            infos.append({k:v for k,v in info.items() if k!='tree'})
            candidates.extend(docs)
            print('SOURCE', info['name'], 'candidates', len(docs), flush=True)
    (ROOT/'metadata/sources.json').write_text(json.dumps(infos,ensure_ascii=False,indent=2))
    # Source priority: Chinese interview guides first; official reference fills remaining slots.
    order = {name:i for i,(_,name,_,_) in enumerate(SOURCES)}
    candidates.sort(key=lambda x:(order[x['name']], -x['size'], x['path']))
    unique_candidates=[]; disk_paths=set()
    for x in candidates:
        key=(x['name']+'/'+x['path']).casefold()
        if key not in disk_paths:
            unique_candidates.append(x);disk_paths.add(key)
    candidates=unique_candidates
    records = []; seen = set(); failures = []
    for start in range(0, len(candidates), 32):
        if len(records) >= 499:
            break
        batch = candidates[start:start+32]
        with cf.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(download,x) for x in batch]
            for x, f in zip(batch, futures):
                try:
                    r = f.result()
                    if len(records)>=499 or r['normalized_sha256'] in seen:
                        (ROOT/r['path']).unlink()
                        continue
                    seen.add(r['normalized_sha256']); records.append(r)
                except Exception as e:
                    failures.append(dict(source=x['name'],path=x['path'],error=str(e)))
        (ROOT/'metadata/manifest.partial.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
        print('DOWNLOADED',len(records),'failures',len(failures),flush=True)
    book_url='https://greenteapress.com/thinkjava2/thinkjava2.pdf'
    book_path=ROOT/'corpus/Books/Think_Java_2e.pdf';book_path.parent.mkdir(exist_ok=True)
    data=book_path.read_bytes() if book_path.exists() else fetch(book_url)
    assert data.startswith(b'%PDF-') and len(data)>100000
    book_path.write_bytes(data)
    records.append(dict(id='think-java-2e',title='Think Java, 2nd Edition',path=book_path.relative_to(ROOT).as_posix(),
                        source='ThinkJava2e',source_url='https://greenteapress.com/wp/think-java-2e/',download_url=book_url,
                        license='CC-BY-NC-SA-4.0',bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),
                        format='pdf',language='en',document_type='complete_book',authors=['Allen B. Downey','Chris Mayfield']))
    (ROOT/'licenses/ThinkJava2e').mkdir(exist_ok=True)
    (ROOT/'licenses/ThinkJava2e/source.html').write_bytes(fetch('https://greenteapress.com/wp/think-java-2e/'))
    (ROOT/'metadata/download_failures.json').write_text(json.dumps(failures,ensure_ascii=False,indent=2))
    (ROOT/'metadata/manifest.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records))
    assert len(records)==500, f'Expected 500, got {len(records)}'
    print('COMPLETE',len(records),dict(collections.Counter(r['source'] for r in records)),flush=True)

if __name__=='__main__':
    main()
