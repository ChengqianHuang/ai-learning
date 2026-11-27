"""根据 manifest 下载本机缺少的原文，并按 SHA-256 校验。"""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]


def restore(record: dict) -> bool:
    relative = Path(record["path"])
    if not relative.parts or relative.parts[0] != "corpus" or ".." in relative.parts:
        raise ValueError(f"清单路径无效：{relative}")
    target = ROOT / relative
    expected = record["sha256"]
    if target.is_file():
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError("现有原文与清单哈希不符，请核对这份文件")
        return False

    url = record["download_url"]
    if not url.startswith("https://"):
        raise ValueError("下载地址须为 HTTPS")
    with urlopen(Request(url, headers={"User-Agent": "AI-Learning-Corpus"}), timeout=90) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("上游下载内容与清单哈希不符")
    target.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=target.parent, delete_on_close=False) as temp:
        temp.write(data)
        temp.close()
        Path(temp.name).replace(target)
    return True


def restore_entry(record: dict) -> tuple[str, str]:
    try:
        downloaded = restore(record)
    except (OSError, URLError, ValueError) as exc:
        return "失败", f"{record['path']}：{exc}"
    return ("已下载" if downloaded else "已存在"), record["path"]


def main() -> None:
    manifest = ROOT / "metadata" / "manifest.jsonl"
    with manifest.open(encoding="utf-8") as lines:
        records = [json.loads(line) for line in lines if line.strip()]
    downloaded = existing = failures = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for state, detail in pool.map(restore_entry, records):
            if state == "失败":
                failures += 1
            elif state == "已下载":
                downloaded += 1
            else:
                existing += 1
                continue
            print(f"[{state}] {detail}", flush=True)
    print(f"已验证 {existing + downloaded}/{len(records)} 份，下载 {downloaded} 份，失败 {failures} 份。")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
