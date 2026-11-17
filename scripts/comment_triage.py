#!/usr/bin/env python3
"""每日 GitHub 评论整理：抓取、分类、打标签、建跟踪 Issue、输出简报。

只用标准库。Token 依次从 GITHUB_TOKEN / GH_TOKEN 读取，否则走
`git credential fill`（复用本机已保存的 GitHub 凭据）。

用法：
    python scripts/comment_triage.py --dry-run          # 只看简报，不写 GitHub
    python scripts/comment_triage.py --apply            # 打标签 / 建 Issue / 归档广告
    python scripts/comment_triage.py --apply --since 2026-11-16T00:00:00Z
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_REPO = "ybw-ly/global-news-timeline"
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE = ROOT / "data" / "comment-triage-state.json"
API = "https://api.github.com"

LABEL_SPECS = {
    "triage": ("5319e7", "自动评论整理生成"),
    "valuable": ("0e8a16", "有价值的反馈"),
    "type:bug": ("d73a4a", "缺陷 / 报错"),
    "type:feature": ("a2eeef", "功能建议"),
    "type:question": ("d876e3", "使用提问"),
    "type:docs": ("0075ca", "文档问题"),
    "type:security": ("b60205", "安全相关"),
    "type:spam": ("ededed", "垃圾 / 广告"),
}

TYPE_LABELS = {
    "bug": "type:bug",
    "feature": "type:feature",
    "question": "type:question",
    "docs": "type:docs",
    "security": "type:security",
}

CATEGORY_RULES = [
    (
        "security",
        (
            "security", "vulnerability", "cve-", "xss", "csrf", "ssrf",
            "injection", "rce", "path traversal", "泄露", "漏洞", "安全",
        ),
    ),
    (
        "bug",
        (
            "bug", "error", "crash", "exception", "traceback", "failed",
            "failure", "broken", "doesn't work", "does not work", "not working",
            "regression", "报错", "崩溃", "闪退", "无法", "失败", "异常",
            "不能用", "坏了", "复现",
        ),
    ),
    (
        "feature",
        (
            "feature", "request", "suggest", "would be nice", "it would be",
            "add support", "support for", "希望", "建议", "能否", "可以加",
            "增加", "支持", "改进",
        ),
    ),
    (
        "docs",
        (
            "documentation", "readme", "doc typo", "typo", "example missing",
            "文档", "说明", "错别字", "示例",
        ),
    ),
    (
        "question",
        (
            "how do", "how to", "how can", "why does", "why is", "what is",
            "question", "怎么", "如何", "为什么", "请问", "是否",
        ),
    ),
]

SPAM_WORDS = (
    "casino", "viagra", "cheap loan", "crypto giveaway", "free followers",
    "telegram.me", "t.me/", "whatsapp", "加微信", "加v", "博彩", "代购",
    "刷单", "推广", "广告", "返利", "兼职日结", "usdt",
)

PRAISE_WORDS = (
    "thank", "thanks", "nice work", "great", "awesome", "love it",
    "谢谢", "感谢", "好用", "不错", "很棒", "牛",
)

REPRO_WORDS = (
    "reproduce", "repro", "steps", "expected", "actual", "version",
    "复现", "步骤", "期望", "实际", "版本", "环境",
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clipboard(text: str, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def classify(text: str) -> dict:
    body = (text or "")[:8000]
    low = body.casefold()
    matched: dict[str, int] = {}
    for category, words in CATEGORY_RULES:
        hits = sum(1 for w in words if w in low)
        if hits:
            matched[category] = hits

    spam_hits = sum(1 for w in SPAM_WORDS if w in low)
    if spam_hits:
        category = "spam"
    elif matched:
        category = max(matched, key=lambda c: matched[c])
    elif any(w in low for w in PRAISE_WORDS) or re.search(r"[!！]{2,}|❤", body):
        category = "praise"
    else:
        category = "other"

    score = 0
    substantive = category != "question" or len(body.strip()) >= 15
    if category in ("bug", "feature", "security", "docs", "question") and substantive:
        score += 2
    if len(body) >= 80:
        score += 1
    if any(w in low for w in REPRO_WORDS):
        score += 1
    if "```" in body or re.search(r"`[^`\n]{2,}`", body):
        score += 1
    if re.search(r"https?://", body):
        score += 1
    if category == "spam":
        score = -5
    elif category == "praise":
        score = max(score, 1)

    return {
        "category": category,
        "score": score,
        "valuable": score >= 2 and category != "spam",
    }


def resolve_token() -> str:
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    try:
        proc = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        proc = None
    if proc and proc.returncode == 0:
        for line in proc.stdout.splitlines():
            if line.startswith("password="):
                return line.split("=", 1)[1].strip()
    raise SystemExit(
        "找不到 GitHub 凭据：请设置 GITHUB_TOKEN，或先让 git 保存 GitHub 登录。"
    )


class GitHub:
    def __init__(self, token: str, repo: str):
        self.token = token
        self.repo = repo
        self.rate_remaining = None

    def _request(self, method: str, path: str, payload: dict | None = None):
        url = path if path.startswith("http") else API + path
        data = None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "global-news-timeline-comment-triage",
        }
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                self.rate_remaining = resp.headers.get("X-RateLimit-Remaining")
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            try:
                message = json.loads(body).get("message", body)
            except json.JSONDecodeError:
                message = body[:300]
            raise RuntimeError(f"GitHub API {exc.code}: {message}") from exc

    def get(self, path: str, params: dict | None = None, pages: int = 5):
        if params:
            path = f"{path}?{urllib.parse.urlencode(params)}"
        results = []
        for page in range(1, pages + 1):
            sep = "&" if "?" in path else "?"
            chunk = self._request("GET", f"{path}{sep}per_page=100&page={page}")
            if not isinstance(chunk, list):
                return chunk
            results.extend(chunk)
            if len(chunk) < 100:
                break
        return results

    def post(self, path: str, payload: dict):
        return self._request("POST", path, payload)

    def graphql(self, query: str, variables: dict):
        return self._request(
            "POST", f"{API}/graphql", {"query": query, "variables": variables}
        )

    def issue(self, number: int):
        return self._request("GET", f"/repos/{self.repo}/issues/{number}")


def load_state(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {"last_run": "", "created": []}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def ensure_labels(gh: GitHub) -> set[str]:
    existing = {
        label["name"] for label in gh.get(f"/repos/{gh.repo}/labels", pages=2)
    }
    for name, (color, description) in LABEL_SPECS.items():
        if name in existing:
            continue
        try:
            gh.post(
                f"/repos/{gh.repo}/labels",
                {"name": name, "color": color, "description": description},
            )
            existing.add(name)
        except RuntimeError as exc:
            if "already_exists" in str(exc) or "422" in str(exc):
                existing.add(name)
            else:
                raise
    return existing


def fetch_activity(gh: GitHub, since: str) -> dict:
    issues = gh.get(
        f"/repos/{gh.repo}/issues",
        {"state": "all", "sort": "updated", "direction": "desc", "since": since},
    )
    issue_comments = gh.get(
        f"/repos/{gh.repo}/issues/comments", {"since": since, "sort": "updated"}
    )
    review_comments = gh.get(
        f"/repos/{gh.repo}/pulls/comments", {"since": since, "sort": "updated"}
    )
    commit_comments = gh.get(f"/repos/{gh.repo}/comments", {"since": since})

    issues = [i for i in issues if i.get("updated_at", "") >= since]
    issue_comments = [c for c in issue_comments if c.get("updated_at", "") >= since]
    review_comments = [
        c for c in review_comments if c.get("updated_at", "") >= since
    ]
    commit_comments = [
        c for c in commit_comments if c.get("updated_at", "") >= since
    ]

    for item in issues:
        item["_kind"] = "pull" if "pull_request" in item else "issue"
    for item in issue_comments + review_comments:
        item["_kind"] = "comment"
    for item in commit_comments:
        item["_kind"] = "commit_comment"
    return {
        "issues": issues,
        "issue_comments": issue_comments,
        "review_comments": review_comments,
        "commit_comments": commit_comments,
    }


def apply_labels(gh: GitHub, number: int, labels: set[str], applied: list[dict]) -> None:
    if not labels:
        return
    current = gh.issue(number)
    have = {label["name"] for label in current.get("labels", [])}
    missing = sorted(labels - have)
    if not missing:
        return
    gh.post(f"/repos/{gh.repo}/issues/{number}/labels", {"labels": missing})
    applied.append(
        {"issue": number, "labels": missing, "url": current.get("html_url", "")}
    )


def minimize_comment(gh: GitHub, node_id: str) -> bool:
    query = (
        "mutation($id:ID!){minimizeComment(input:{subjectId:$id,"
        "classifier:SPAM}){minimizedComment{isMinimized}}}"
    )
    try:
        result = gh.graphql(query, {"id": node_id})
        return bool(
            result.get("data", {})
            .get("minimizeComment", {})
            .get("minimizedComment", {})
            .get("isMinimized")
        )
    except RuntimeError:
        return False


def build_digest(
    activity: dict,
    verdicts: dict,
    applied: list[dict],
    created: list[dict],
    since: str,
    dry_run: bool,
) -> str:
    issues = activity["issues"]
    comments = (
        activity["issue_comments"]
        + activity["review_comments"]
        + activity["commit_comments"]
    )
    valuable = [c for c in comments if verdicts.get(c["id"], {}).get("valuable")]
    spam = [c for c in comments if verdicts.get(c["id"], {}).get("category") == "spam"]

    lines = [f"## 评论整理简报 — {now_utc().strftime('%Y-%m-%d')}", ""]
    lines.append(
        f"- 检查范围：{since} 之后；Issue/PR {len(issues)} 条，"
        f"评论 {len(comments)} 条"
    )
    lines.append(f"- 有价值：**{len(valuable)}** 条；疑似广告：**{len(spam)}** 条")

    if not comments and not issues:
        lines.extend(["", "今日无新评论。"])
        return "\n".join(lines)

    if valuable:
        lines.extend(
            [
                "",
                "### 有价值反馈",
                "",
                "| 类型 | 作者 | 摘要 | 链接 |",
                "|---|---|---|---|",
            ]
        )
        for comment in valuable[:30]:
            v = verdicts.get(comment["id"], {})
            user = (comment.get("user") or {}).get("login", "?")
            lines.append(
                f"| {v.get('category', 'other')} | @{user} | "
                f"{clipboard(comment.get('body', ''), 110)} | "
                f"[查看]({comment.get('html_url', '')}) |"
            )

    if created:
        lines.extend(["", "### 已自动创建 Issue", ""])
        for item in created:
            lines.append(f"- #{item['number']} {item['title']} — {item['url']}")

    if applied:
        lines.extend(["", "### 已自动打标签", ""])
        for item in applied:
            lines.append(
                f"- #{item['issue']}: {', '.join(item['labels'])} — {item['url']}"
            )

    if spam:
        lines.extend(["", "### 疑似广告 / 垃圾", ""])
        for comment in spam:
            user = (comment.get("user") or {}).get("login", "?")
            lines.append(
                f"- @{user}: {clipboard(comment.get('body', ''), 100)} "
                f"[查看]({comment.get('html_url', '')})"
            )

    if dry_run:
        lines.extend(["", "> dry-run：未写入 GitHub。"])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="每日 GitHub 评论整理")
    parser.add_argument("--repo", default=os.environ.get("TRIAGE_REPO", DEFAULT_REPO))
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--since", default="", help="ISO 时间；默认读上次运行时间")
    parser.add_argument("--apply", action="store_true", help="写入标签/Issue/折叠广告")
    parser.add_argument("--dry-run", action="store_true", help="只输出简报")
    parser.add_argument("--out", type=Path, default=None, help="同时写入 Markdown 文件")
    parser.add_argument("--quiet", action="store_true", help="不打印简报")
    args = parser.parse_args()

    dry_run = args.dry_run or not args.apply
    state = load_state(args.state)

    if args.since:
        since = args.since
    elif state.get("last_run"):
        since = state["last_run"]
    else:
        since = iso(now_utc() - timedelta(days=1))

    gh = GitHub(resolve_token(), args.repo)
    activity = fetch_activity(gh, since)

    verdicts: dict[int, dict] = {}
    for comment in (
        activity["issue_comments"]
        + activity["review_comments"]
        + activity["commit_comments"]
    ):
        verdicts[comment["id"]] = classify(comment.get("body", ""))

    applied: list[dict] = []
    created: list[dict] = []
    created_keys = set(state.get("created", []))

    if not dry_run:
        ensure_labels(gh)

        comments_by_issue: dict[int, list[dict]] = {}
        for comment in activity["issue_comments"]:
            number = int(comment.get("issue_url", "").rsplit("/", 1)[-1] or 0)
            comments_by_issue.setdefault(number, []).append(comment)

        for issue in activity["issues"]:
            number = issue["number"]
            texts = [issue.get("title", ""), issue.get("body", "")]
            texts += [c.get("body", "") for c in comments_by_issue.get(number, [])]
            categories = {classify(t)["category"] for t in texts if t}
            labels = {TYPE_LABELS[c] for c in categories if c in TYPE_LABELS}
            if any(
                verdicts.get(c["id"], {}).get("valuable")
                for c in comments_by_issue.get(number, [])
            ):
                labels.add("valuable")
            if "spam" in categories:
                labels.add("type:spam")
            apply_labels(gh, number, labels, applied)

        for comment in activity["review_comments"]:
            verdict = verdicts.get(comment["id"], {})
            number = int(comment.get("pull_request_url", "").rsplit("/", 1)[-1] or 0)
            if number and verdict.get("valuable"):
                apply_labels(gh, number, {"valuable"}, applied)

        for comment in activity["commit_comments"]:
            verdict = verdicts.get(comment["id"], {})
            if not verdict.get("valuable"):
                continue
            key = f"commit_comment:{comment['id']}"
            if key in created_keys:
                continue
            category = verdict.get("category", "other")
            labels = ["triage"] + ([TYPE_LABELS[category]] if category in TYPE_LABELS else [])
            title_text = clipboard(comment.get("body", ""), 70) or "提交评论反馈"
            title = f"[triage] {title_text}"
            body = (
                f"来源：{comment.get('html_url', '')}\n"
                f"作者：@{(comment.get('user') or {}).get('login', '?')}\n\n"
                f"> {comment.get('body', '')}\n\n"
                "_由每日评论整理自动创建，可在合并/处理后关闭。_"
            )
            try:
                issue = gh.post(
                    f"/repos/{gh.repo}/issues",
                    {"title": title, "body": body, "labels": labels},
                )
                created.append(
                    {
                        "number": issue["number"],
                        "title": title,
                        "url": issue["html_url"],
                    }
                )
                created_keys.add(key)
            except RuntimeError as exc:
                print(f"创建 Issue 失败：{exc}", file=sys.stderr)

        for comment in (
            activity["issue_comments"]
            + activity["review_comments"]
            + activity["commit_comments"]
        ):
            if verdicts.get(comment["id"], {}).get("category") != "spam":
                continue
            node_id = comment.get("node_id")
            if node_id and not comment.get("isMinimized"):
                minimize_comment(gh, node_id)

    digest = build_digest(activity, verdicts, applied, created, since, dry_run)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(digest + "\n", encoding="utf-8")
        print(f"简报已写入 {args.out}", file=sys.stderr)
    if not args.quiet:
        print(digest)

    if not dry_run:
        state["last_run"] = iso(now_utc())
        state["created"] = sorted(created_keys)
        save_state(args.state, state)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
