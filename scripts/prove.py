#!/usr/bin/env python3
"""
archon-deerflow prove — 命令行定理证明工具

用法 (自动检测环境，透明路由到 Docker 容器):
    python3 scripts/prove.py "命题文本"
    python3 scripts/prove.py -f problem.txt
    echo "1+1=2" | python3 scripts/prove.py
    python3 scripts/prove.py -f statement.txt -c RETRIEVAL -o ./output

输出:
    informal_proof.md   → 非形式化证明
    formal/src/*.lean    → Lean 4 形式化代码
    report.json          → 最终报告
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


CONTAINER_NAME = "archon-deerflow-gateway"
OVERLAY_PATH = "/app/deer-flow/overlay/backend"
RUNTIME_ENV = "ARCHON_DEERFLOW_RUNTIME_ROOT=/app/deer-flow/.deerflow_runtime"


def _run_in_container(params_json: str) -> str:
    """Run the prove command inside the Docker container."""
    # Escape for safe bash passing
    import base64
    encoded = base64.b64encode(params_json.encode()).decode()
    script = f"""
import sys, json, os, base64
sys.path.insert(0, '{OVERLAY_PATH}')
os.environ['ARCHON_DEERFLOW_RUNTIME_ROOT'] = '/app/deer-flow/.deerflow_runtime'
from workflows import run_e2e_workflow

params = json.loads(base64.b64decode('{encoded}').decode())
result = run_e2e_workflow(**params)
print("__RESULT__" + json.dumps({{
    'stage': result.get('stage'),
    'all_checks_pass': result.get('all_checks_pass'),
    'per_phase': {{p: {{'passed': i['passed'], 'failed': i['failed'], 'stage': i['stage']}}
                  for p, i in result.get('structural_report', {{}}).get('per_phase', {{}}).items()}},
    'phase3_modules': result.get('phase3_result', {{}}).get('module_files', []),
    'phase4_stage': result.get('phase4_result', {{}}).get('stage'),
    'phase4_completed': result.get('phase4_result', {{}}).get('completed', []),
    'project_root': result.get('phase1_result', {{}}).get('project_root', ''),
}}, ensure_ascii=False))
"""
    cmd = ["docker", "exec", CONTAINER_NAME, "python3", "-c", script]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)  # 30 minutes
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        sys.exit(1)
    # Extract JSON after __RESULT__ marker
    for line in proc.stdout.splitlines():
        if line.startswith("__RESULT__"):
            return line[len("__RESULT__"):]
    print("ERROR: No result returned from container", file=sys.stderr)
    sys.exit(1)


def _export_artifacts(thread_id: str, project: str, output_dir: Path) -> list[str]:
    """Copy artifacts from the container to the host output directory."""
    src_base = f"/app/deer-flow/.deerflow_runtime/threads/{thread_id}/user-data/workspace/{project}"
    exported = []

    # Informal proof
    informal = f"{src_base}/informal/proofs/candidate_proof.md"
    cp = subprocess.run(["docker", "exec", CONTAINER_NAME, "test", "-f", informal], capture_output=True)
    if cp.returncode == 0:
        dst = output_dir / "informal_proof.md"
        subprocess.run(["docker", "cp", f"{CONTAINER_NAME}:{informal}", str(dst)], check=True)
        exported.append("informal_proof.md")

    # Lean files
    formal_src = f"{src_base}/formal/src"
    cp = subprocess.run(["docker", "exec", CONTAINER_NAME, "test", "-d", formal_src], capture_output=True)
    if cp.returncode == 0:
        files = subprocess.run(
            ["docker", "exec", CONTAINER_NAME, "find", formal_src, "-name", "*.lean", "-type", "f"],
            capture_output=True, text=True
        )
        for f in files.stdout.strip().splitlines():
            if f:
                rel = os.path.relpath(f, formal_src)
                dst = output_dir / "formal" / "src" / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(["docker", "cp", f"{CONTAINER_NAME}:{f}", str(dst)], check=True)
                exported.append(f"formal/src/{rel}")

    return exported


def main():
    parser = argparse.ArgumentParser(description="archon-deerflow 数学定理证明")
    parser.add_argument("statement", nargs="?", help="命题文本")
    parser.add_argument("-f", "--file", help="从文件读取命题")
    parser.add_argument("-n", "--name", default=None, help="项目名称")
    parser.add_argument("-c", "--category", default="SIMPLE",
                        choices=["SIMPLE", "RETRIEVAL", "COMPLEX"],
                        help="问题类别 (默认: SIMPLE)")
    parser.add_argument("-o", "--output", default=None, help="输出目录")
    parser.add_argument("--max-loops", type=int, default=3, help="最大证明轮次 (默认: 3)")
    parser.add_argument("--parallel", type=int, default=1, help="并行度 (默认: 1)")
    parser.add_argument("-q", "--quiet", action="store_true", help="安静模式 (只输出 JSON)")
    args = parser.parse_args()

    # ── 获取命题 ──
    statement = args.statement
    if args.file:
        statement = Path(args.file).read_text().strip()
    if not statement and not sys.stdin.isatty():
        statement = sys.stdin.read().strip()
    if not statement:
        parser.error("请提供命题文本。示例: python3 scripts/prove.py 'Prove that 1+1=2.'")

    project = args.name or f"proof-{int(time.time())}"
    thread_id = f"thread-{project.replace(' ', '-')}"
    output_dir = Path(args.output) if args.output else Path.cwd() / "workspace" / project
    output_dir.mkdir(parents=True, exist_ok=True)

    if not args.quiet:
        print("=" * 60)
        print(f"  命题:  {statement[:100]}{'...' if len(statement) > 100 else ''}")
        print(f"  项目:  {project}")
        print(f"  类别:  {args.category}")
        print(f"  输出:  {output_dir.resolve()}")
        print("=" * 60)
        print("\n运行中 (Phase 1→5, 约需 3-15 分钟，取决于 LLM 响应速度) ...\n", flush=True)

    # ── 运行 E2E workflow (在容器内) ──
    # 通过 JSON 安全传递参数
    params = {
        "thread_id": thread_id,
        "statement": statement,
        "project_name": project,
        "problem_id": project.lower().replace(" ", "-"),
        "category": args.category,
        "max_loops": args.max_loops,
        "parallelism": args.parallel,
    }
    params_json = json.dumps(params)

    try:
        result_json = _run_in_container(params_json)
    except subprocess.TimeoutExpired:
        print("超时: 证明未在 30 分钟内完成", file=sys.stderr)
        sys.exit(1)

    result = json.loads(result_json)

    # ── 导出产物 ──
    exported = _export_artifacts(thread_id, project, output_dir)

    # ── 写报告 ──
    report_data = {
        "statement": statement,
        "project": project,
        "thread_id": thread_id,
        "category": args.category,
        "stage": result.get("stage"),
        "all_checks_pass": result.get("all_checks_pass"),
        "per_phase": result.get("per_phase", {}),
        "phase4_stage": result.get("phase4_stage"),
        "phase4_completed": result.get("phase4_completed"),
        "phase3_modules": result.get("phase3_modules"),
        "files": exported,
    }
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report_data, ensure_ascii=False, indent=2))

    # ── 输出 ──
    if args.quiet:
        print(json.dumps(report_data, ensure_ascii=False))
    else:
        print("\n" + "=" * 60)
        print(" 结果")
        print("=" * 60)
        for phase, info in result.get("per_phase", {}).items():
            icon = "✓" if info["failed"] == 0 else "⚠"
            print(f"  {icon} {phase}: {info['passed']}/{info['passed'] + info['failed']} ({info['stage']})")
        print(f"\n Phase 4 状态: {result.get('phase4_stage', '?')}")
        print(f" 已完成文件:   {result.get('phase4_completed', [])}")
        print(f"\n产物 ({output_dir.resolve()}):")
        for f in exported:
            print(f"  {f}")

        # 打印 Lean 文件内容
        for f in exported:
            if f.endswith(".lean"):
                content = (output_dir / f).read_text()
                print(f"\n── {f} ──")
                for line in content.splitlines():
                    print(f"  {line}")

        print("\n" + "=" * 60)

    return 0 if result.get("all_checks_pass") else 1


if __name__ == "__main__":
    sys.exit(main())
