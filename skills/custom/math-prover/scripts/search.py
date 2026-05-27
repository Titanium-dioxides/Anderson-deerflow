#!/usr/bin/env python3
"""
轻量级定理搜索脚本 — Matlas 后门

从 Rethlas 源码中提取的 leansearch.net 定理搜索接口。
当 DeerFlow 的生成/验证模式需要外部定理参考时使用。

用法：
    python scripts/search.py "勾股定理"
    python scripts/search.py "素数无限" --num 5
"""

import sys
import json
import argparse

try:
    import httpx
except ImportError:
    httpx = None  # fallback to urllib

# 从 Rethlas 源码提取的定理搜索端点
THEOREM_SEARCH_URL = "https://leansearch.net/thm/search"

# 搜索任务上下文
THEOREM_SEARCH_TASK = (
    "Given a math statement, retrieve useful references, such as theorems, "
    "lemmas, and definitions, that are useful for solving the given problem."
)


def search_theorems(query: str, num_results: int = 10, timeout: int = 30) -> dict:
    """搜索相关数学定理，返回结构化结果"""
    if not query.strip():
        return {"error": "查询不能为空", "count": 0, "results": []}

    payload = {
        "query": query,
        "task": THEOREM_SEARCH_TASK,
        "num_results": min(num_results, 50),
    }

    if httpx is not None:
        try:
            resp = httpx.post(THEOREM_SEARCH_URL, json=payload, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            return {"error": f"httpx 请求失败: {e}", "count": 0, "results": []}
    else:
        # fallback to urllib (no external deps)
        import urllib.request
        import ssl

        try:
            req_data = json.dumps(payload).encode("utf-8")
            ctx = ssl.create_default_context()
            req = urllib.request.Request(
                THEOREM_SEARCH_URL,
                data=req_data,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (compatible; MathProver/1.0)",
                },
            )
            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"error": f"urllib 请求失败: {e}", "count": 0, "results": []}

    # 规范化返回格式
    if not isinstance(data, list):
        return {"error": "服务器返回格式异常", "count": 0, "results": []}

    normalized = []
    for item in data:
        if not isinstance(item, dict):
            continue
        normalized.append({
            "title": str(item.get("title", "")),
            "theorem": str(item.get("theorem", "")),
            "arxiv_id": str(item.get("arxiv_id", "")),
            "theorem_id": str(item.get("theorem_id", "")),
        })

    return {
        "query": query,
        "count": len(normalized),
        "results": normalized,
        "endpoint": THEOREM_SEARCH_URL,
    }


def main():
    parser = argparse.ArgumentParser(description="数学定理搜索工具")
    parser.add_argument("query", type=str, help="搜索查询（定理名或数学陈述）")
    parser.add_argument("--num", "-n", type=int, default=10, help="返回结果数量 (默认 10)")
    parser.add_argument("--pretty", "-p", action="store_true", help="美化输出格式")

    args = parser.parse_args()
    result = search_theorems(args.query, num_results=args.num)

    if args.pretty:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        # 紧凑输出，方便 DeerFlow 解析
        output = result
        if result.get("error"):
            output["error"] = result["error"]
        print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
