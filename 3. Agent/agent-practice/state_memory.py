"""用 SQLite 恢复笔记检索任务，并在新任务中读取用户的检索条数偏好。"""

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from notes_tool import MAX_QUERY_LENGTH, MAX_TOP_K, search_notes


DEFAULT_DB = Path(__file__).resolve().parent / ".local" / "state.sqlite3"


def initialize(db: sqlite3.Connection) -> None:
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS preferences (
            user_id TEXT PRIMARY KEY,
            top_k INTEGER NOT NULL CHECK (top_k BETWEEN 1 AND 5)
        );
        CREATE TABLE IF NOT EXISTS tasks (
            user_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            question TEXT NOT NULL,
            top_k INTEGER NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('ready', 'searched', 'done')),
            evidence TEXT,
            answer TEXT,
            PRIMARY KEY (user_id, task_id)
        );
    """)


def get_task(db: sqlite3.Connection, user: str, task_id: str) -> sqlite3.Row:
    task = db.execute(
        "SELECT * FROM tasks WHERE user_id = ? AND task_id = ?", (user, task_id)
    ).fetchone()
    if task is None:
        raise ValueError(f"用户 {user} 下找不到任务 {task_id}")
    return task


def start_task(db: sqlite3.Connection, user: str, task_id: str, question: str) -> None:
    # 在同一条语句里读取偏好并保存快照，并发修改偏好只会影响之后创建的任务。
    with db:
        created = db.execute("""
            INSERT INTO tasks (user_id, task_id, question, top_k, state)
            VALUES (?, ?, ?, COALESCE((SELECT top_k FROM preferences WHERE user_id = ?), 3), 'ready')
            ON CONFLICT (user_id, task_id) DO NOTHING
        """, (user, task_id, question, user)).rowcount
        task = get_task(db, user, task_id)
        if task["question"] != question:
            raise ValueError(f"任务 {task_id} 已用于另一个问题，请换一个任务 ID")
    print(f"[{'新任务' if created else '已有任务'}] user={user} task={task_id} top_k={task['top_k']}")


def render_evidence(hits: list[dict[str, str]]) -> str:
    if not hits:
        return "本次检索未找到相关证据。"
    passages = []
    for rank, hit in enumerate(hits, 1):
        passages.append(f"[{rank}] {hit['source']} · {hit['heading']}\n{hit['text']}")
    return "\n\n".join(passages)


def advance(db: sqlite3.Connection, user: str, task_id: str, pause_after_search: bool) -> None:
    # 本地检索很短。先取写锁再读状态，让并发恢复者复用已提交的证据。
    # 进程在事务提交前退出时，下一次恢复会重算这次只读检索。
    with db:
        db.execute("BEGIN IMMEDIATE")
        task = get_task(db, user, task_id)
        if task["state"] == "done":
            print(f"[复用已完成结果] task={task_id}\n{task['answer']}")
            return
        if task["state"] == "ready":
            hits = search_notes(task["question"], top_k=task["top_k"])
            db.execute("""
                UPDATE tasks SET state = 'searched', evidence = ?
                WHERE user_id = ? AND task_id = ?
            """, (json.dumps(hits, ensure_ascii=False), user, task_id))
            trace = f"[工具] search_notes top_k={task['top_k']}，已保存 {len(hits)} 条证据"
        else:
            trace = f"[恢复检查点] task={task_id}，从 SQLite 读取已保存的检索结果"
    print(trace)
    if pause_after_search:
        print(f"[暂停] task={task_id}，检索检查点已提交")
        return

    with db:
        db.execute("BEGIN IMMEDIATE")
        task = get_task(db, user, task_id)
        if task["state"] == "done":
            answer = task["answer"]
        else:
            answer = render_evidence(json.loads(task["evidence"]))
            db.execute("""
                UPDATE tasks SET state = 'done', answer = ?
                WHERE user_id = ? AND task_id = ?
            """, (answer, user, task_id))
    print(f"[完成] task={task_id} top_k={task['top_k']}\n{answer}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite 文件路径")
    parser.add_argument("--user", default="local", help="本地实验的用户分区")
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="创建任务并执行检索")
    start.add_argument("task_id")
    start.add_argument("question")
    start.add_argument("--pause-after-search", action="store_true", help="提交检索检查点后退出")
    resume = commands.add_parser("resume", help="从任务的持久化状态继续")
    resume.add_argument("task_id")
    remember = commands.add_parser("remember", help="保存本用户后续新任务的检索条数")
    remember.add_argument("--top-k", type=int, choices=range(1, MAX_TOP_K + 1), required=True)
    args = parser.parse_args()

    if not args.user.strip() or (args.command != "remember" and not args.task_id.strip()):
        parser.error("用户标识和任务 ID 不能为空")
    if args.command == "start":
        args.question = args.question.strip()
        if not 1 <= len(args.question) <= MAX_QUERY_LENGTH:
            parser.error(f"问题长度必须在 1 至 {MAX_QUERY_LENGTH} 个字符之间")
    try:
        args.db.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(args.db, timeout=10)) as db:
            initialize(db)
            if args.command == "remember":
                with db:
                    db.execute("""
                        INSERT INTO preferences (user_id, top_k) VALUES (?, ?)
                        ON CONFLICT (user_id) DO UPDATE SET top_k = excluded.top_k
                    """, (args.user, args.top_k))
                print(f"[记忆] user={args.user} top_k={args.top_k}，创建新任务时读取")
                return
            if args.command == "start":
                start_task(db, args.user, args.task_id, args.question)
            advance(db, args.user, args.task_id, args.command == "start" and args.pause_after_search)
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"运行失败：{exc}\n")


if __name__ == "__main__":
    main()
