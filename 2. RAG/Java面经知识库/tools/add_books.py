#!/usr/bin/env python3
"""Append whole author/publisher-hosted backend books; preserve the original corpus."""
import concurrent.futures as cf
import hashlib
import io
import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from pypdf import PdfReader
from collect import ROOT

# id, title, Chinese display title, subject, author, language, rights, source page, PDF
BOOKS = [
('javanotes9','Introduction to Programming Using Java, Version 9','Java 17 编程入门（第9版）','Java与数据结构','David J. Eck','en','CC-BY-NC-SA-4.0','https://math.hws.edu/javanotes/','https://math.hws.edu/eck/cs124/downloads/javanotes9-linked.pdf'),
('open-data-structures-java','Open Data Structures (Java Edition)','开放数据结构：Java版','Java与数据结构','Pat Morin','en','CC-BY-2.5-CA','https://opendatastructures.org/','https://opendatastructures.org/ods-java.pdf'),
('think-os','Think OS: A Brief Introduction to Operating Systems','操作系统简明入门','操作系统与并发','Allen B. Downey','en','CC-BY-NC-SA-4.0','https://greenteapress.com/wp/think-os/','https://greenteapress.com/thinkos/thinkos.pdf'),
('little-book-semaphores','The Little Book of Semaphores','信号量小书','操作系统与并发','Allen B. Downey','en','CC-BY-NC-SA-4.0','https://greenteapress.com/wp/semaphores/','https://greenteapress.com/semaphores/LittleBookOfSemaphores.pdf'),
('beej-network','Beej’s Guide to Network Programming','Beej 网络编程指南','网络与通信','Brian Hall','en','CC-BY-NC-ND-3.0','https://beej.us/guide/bgnet/','https://beej.us/guide/bgnet/pdf/bgnet_usl_c_1.pdf'),
('beej-ipc','Beej’s Guide to Interprocess Communication','Beej 进程间通信指南','操作系统与并发','Brian Hall','en','CC-BY-NC-ND-3.0','https://beej.us/guide/bgipc/','https://beej.us/guide/bgipc/pdf/bgipc_usl_c_1.pdf'),
('intro-computer-networks','An Introduction to Computer Networks','计算机网络导论','网络与通信','Peter L. Dordal','en','CC-BY-NC-ND-3.0','https://intronetworks.cs.luc.edu/','https://intronetworks.cs.luc.edu/current2/ComputerNetworks.pdf'),
('computer-networking-principles','Computer Networking: Principles, Protocols and Practice, 3rd Edition','计算机网络：原理、协议与实践','网络与通信','Olivier Bonaventure and contributors','en','CC-BY-3.0','https://www.computer-networking.info/','https://github.com/cnp3/ebook/releases/download/draft-3rd/CNP3-2021.pdf'),
('computer-networks-systems','Computer Networks: A Systems Approach, 6.1','计算机网络：系统方法','网络与通信','Larry Peterson and Bruce Davie','en','CC-BY-4.0','https://book.systemsapproach.org/','https://github.com/SystemsApproach/book/releases/download/v6.1/book.pdf'),
('producing-open-source','Producing Open Source Software','开源软件项目管理','软件工程与协作','Karl Fogel','en','CC-BY-SA-4.0','https://producingoss.com/','https://producingoss.com/en/producingoss-letter.pdf'),
('pro-git-zh','Pro Git, 2nd Edition (Simplified Chinese)','Pro Git 第二版（简体中文）','软件工程与协作','Scott Chacon and Ben Straub; Chinese translation contributors','zh','CC-BY-NC-SA-3.0','https://git-scm.com/book/zh/v2','https://github.com/progit/progit2-zh/releases/download/2.1.80/progit.pdf'),
('algorithms-erickson','Algorithms','算法','算法与数据结构','Jeff Erickson','en','CC-BY-4.0','https://jeffe.cs.illinois.edu/teaching/algorithms/','https://jeffe.cs.illinois.edu/teaching/algorithms/book/Algorithms-JeffE.pdf'),
('xv6-riscv','xv6: a Simple, Unix-like Teaching Operating System','xv6：类 Unix 教学操作系统','操作系统与并发','Russ Cox, Frans Kaashoek and Robert Morris','en','MIT-style; book source repository LICENSE','https://pdos.csail.mit.edu/6.1810/2025/xv6.html','https://pdos.csail.mit.edu/6.1810/2025/xv6/book-riscv-rev5.pdf'),
('linux-from-scratch','Linux From Scratch, 12.4','从零构建 Linux','Linux与运维','Gerard Beekmans and LFS contributors','en','CC-BY-NC-SA-2.0; book text; see embedded license','https://www.linuxfromscratch.org/lfs/downloads/stable/','https://www.linuxfromscratch.org/lfs/downloads/stable/LFS-BOOK-12.4.pdf'),
('linux-command-line','The Linux Command Line','Linux 命令行','Linux与运维','William Shotts','en','CC-BY-NC-ND-3.0','https://linuxcommand.org/tlcl.php','https://sourceforge.net/projects/linuxcommand/files/TLCL/25.12/TLCL-25.12A.pdf/download'),
('adventures-linux-command-line','Adventures with the Linux Command Line','Linux 命令行进阶实践','Linux与运维','William Shotts','en','CC-BY-NC-ND-3.0','https://linuxcommand.org/tlcl.php','https://sourceforge.net/projects/linuxcommand/files/AWTLCL/21.10/AWTLCL-21.10.pdf/download'),
('database-design2','Database Design, 2nd Edition','数据库设计第二版','数据库','Adrienne Watt and Nelson Eng','en','CC-BY-4.0; exceptions noted in book','https://opentextbc.ca/dbdesign01/','https://openlibrary-repo.ecampusontario.ca/xmlui/bitstream/handle/123456789/247/Database-Design-2nd-Edition-1540829576.pdf?isAllowed=y&sequence=16'),
('architecture-database','Architecture of a Database System','数据库系统架构（研究专著）','数据库','Joseph M. Hellerstein, Michael Stonebraker and James Hamilton','en','Author-hosted free PDF; copyright retained; not an open license','https://dsf.berkeley.edu/papers/','https://db.cs.berkeley.edu/papers/fntdb07-architecture.pdf'),
('software-engineering-marsic','Software Engineering','软件工程','软件工程与协作','Ivan Marsic','en','Author-hosted free textbook; see embedded terms','https://eceweb1.rutgers.edu/~marsic/books/SE/','https://eceweb1.rutgers.edu/~marsic/books/SE/book-SE_marsic.pdf'),
('java-notes-professionals','Java Notes for Professionals','Java 开发参考手册','Java与数据结构','Stack Overflow Documentation contributors; compiled by GoalKicker','en','CC-BY-SA (text); images retain respective rights; see credits','https://goalkicker.com/JavaBook/','https://goalkicker.com/JavaBook/JavaNotesForProfessionals.pdf'),
('spring-notes-professionals','Spring Framework Notes for Professionals','Spring Framework 开发参考手册','Java框架','Stack Overflow Documentation contributors; compiled by GoalKicker','en','CC-BY-SA (text); images retain respective rights; see credits','https://goalkicker.com/SpringFrameworkBook/','https://goalkicker.com/SpringFrameworkBook/SpringFrameworkNotesForProfessionals.pdf'),
]

def fetch(url):
    if 'sourceforge.net/' in url:
        # Resume interrupted transfers into a temporary file, never into the corpus.
        with tempfile.TemporaryDirectory(prefix='backend-book-') as tmp:
            dest=Path(tmp)/'download.pdf'
            for attempt in range(6):
                p=subprocess.run(['curl','--http1.1','-fLsS','--connect-timeout','15','--max-time','120',
                                  '-C','-','-o',str(dest),url],capture_output=True)
                if p.returncode==0:return dest.read_bytes()
                if p.returncode==33 and dest.exists():dest.unlink()
            raise RuntimeError(p.stderr.decode(errors='replace').strip())
    for attempt in range(4):
        p=subprocess.run(['curl','--http1.1','-fLsS','--connect-timeout','15','--max-time','150',
                          '-H','User-Agent: Backend-RAG-Learning-Corpus',url],capture_output=True)
        if p.returncode==0:return p.stdout
    raise RuntimeError(p.stderr.decode(errors='replace').strip())

def get_book(spec):
    bid,title,zh,subject,author,lang,license_id,page,url=spec
    dest=ROOT/'corpus/Books'/subject/(bid+'.pdf');dest.parent.mkdir(parents=True,exist_ok=True)
    data=dest.read_bytes() if dest.exists() else fetch(url)
    assert data.startswith(b'%PDF-') and b'%%EOF' in data[-4096:], 'Not a complete PDF'
    assert len(data)>50000,'Suspiciously small PDF'
    reader=PdfReader(io.BytesIO(data))
    assert len(reader.pages)>=30,'Not a book-length document'
    # Parse the whole page tree; text extraction of sampled pages catches image-only PDFs.
    samples=sorted({0,1,min(3,len(reader.pages)-1),len(reader.pages)//3,len(reader.pages)//2,len(reader.pages)-2})
    texts=[reader.pages[i].extract_text() or '' for i in samples]
    assert sum(len(t.strip()) for t in texts)>1500,'PDF has insufficient extractable text'
    dest.write_bytes(data)
    licdir=ROOT/'licenses/BooksExpansion'/bid;licdir.mkdir(parents=True,exist_ok=True)
    front='\n\n'.join((reader.pages[i].extract_text() or '') for i in range(min(12,len(reader.pages))))
    (licdir/'frontmatter-extract.txt').write_text(front)
    proof=dict(title=title,source_url=page,download_url=url,rights=license_id,
               note='Original whole PDF downloaded from author/publisher/project. Rights remain with original holders.')
    (licdir/'source.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
    r=dict(id=bid,title=title,title_zh=zh,subject=subject,authors=[author],language=lang,
           path=dest.relative_to(ROOT).as_posix(),source='BackendBooks',source_url=page,
           download_url=url,license=license_id,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),
           format='pdf',document_type='research_monograph' if bid=='architecture-database' else 'complete_book',
           collection_date='2026-11-13',pages=len(reader.pages),sample_text_extraction=True)
    print('BOOK_OK',bid,'pages',len(reader.pages),'bytes',len(data),flush=True)
    return r

def main():
    logging.getLogger('pypdf').setLevel(logging.ERROR)
    manifest=ROOT/'metadata/manifest.jsonl';rows=[json.loads(s) for s in manifest.read_text().splitlines()]
    specs={s[0]:s for s in BOOKS}
    for r in rows:
        if r['id'] in specs:
            spec=specs[r['id']]
            r['license']=spec[6]
            proof=ROOT/'licenses/BooksExpansion'/r['id']/'source.json'
            if proof.exists():
                info=json.loads(proof.read_text());info['rights']=spec[6]
                proof.write_text(json.dumps(info,ensure_ascii=False,indent=2))
    manifest.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    backup=ROOT/'metadata/manifest.initial-500.jsonl'
    if not backup.exists():backup.write_bytes(manifest.read_bytes())
    known={r['id'] for r in rows};failures=[]
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        futures={pool.submit(get_book,spec):spec for spec in BOOKS if spec[0] not in known}
        for future in cf.as_completed(futures):
            spec=futures[future]
            try:
                r=future.result()
                assert not any(x['sha256']==r['sha256'] for x in rows),'Duplicate book'
                rows.append(r)
                manifest.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
            except Exception as e:
                failures.append(dict(id=spec[0],url=spec[-1],error=str(e)))
                print('BOOK_FAILED',spec[0],str(e)[:250],flush=True)
    (ROOT/'metadata/book_download_failures.json').write_text(json.dumps(failures,ensure_ascii=False,indent=2))
    print('BOOK_EXPANSION_COMPLETE',len(rows),'new books',sum(r['source']=='BackendBooks' for r in rows),flush=True)

if __name__=='__main__':main()
