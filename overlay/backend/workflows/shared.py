"""
Archon DeerFlow — 共享 Lean 工具模块
========================================
DeerFlow 规范实践要点：
  - 纯函数：类型注解完整，不依赖 deerflow 运行时
  - I/O 函数：接受 sb=None 参数，sandbox 优先，回退本地

E1: 集中所有重复 I/O 函数，两 graph 文件统一调用
E5: _exec_with_sandbox 内置路径安全校验
"""

import datetime
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from contextlib import contextmanager

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# E5: Sandbox 基础设施（共享）
# ═══════════════════════════════════════════════════════════════════════

try:
    from deerflow.sandbox.sandbox_provider import get_sandbox_provider
    _SANDBOX_AVAILABLE = True
except Exception:
    _SANDBOX_AVAILABLE = False


# E5: 基本路径安全校验
_PATH_TRAVERSAL_PATTERN = re.compile(r'(?:^|[\/])[.][.](?:$|[\/])')


def _reject_path_traversal(path: str) -> None:
    """E5: 检查路径穿越攻击。如果 path 包含 '..' 段则抛出 ValueError。"""
    if _PATH_TRAVERSAL_PATTERN.search(path):
        raise ValueError(f"路径穿越检测: {path}")


@contextmanager
def sandbox_context(thread_hint: str = "archon"):
    """E1: 统一 sandbox 上下文管理器。
    
    确保 acquire/release 配对。
    """
    sb_provider = None
    sandbox_id = None
    sb = None
    if _SANDBOX_AVAILABLE:
        try:
            sb_provider = get_sandbox_provider()
            sandbox_id = sb_provider.acquire(thread_hint)
            sb = sb_provider.get(sandbox_id)
        except Exception as e:
            logger.warning("[sandbox] acquire 失败: %s", e)
    try:
        yield sb
    finally:
        if sandbox_id and sb_provider:
            try:
                sb_provider.release(sandbox_id)
            except Exception as e:
                logger.warning("[sandbox] release 失败: %s", e)


# ═══════════════════════════════════════════════════════════════════════
# E1: Sandbox 感知的 I/O 函数
# ═══════════════════════════════════════════════════════════════════════


def exec_with_sandbox(cmd: str, cwd: str, sb=None) -> subprocess.CompletedProcess:
    """E1: 在 sandbox 内或本地执行命令。
    
    E5: 对命令中的路径参数做基本穿越检测。
    """
    if sb is not None:
        try:
            # E5: 简单路径检查
            for token in cmd.split():
                if _PATH_TRAVERSAL_PATTERN.search(token):
                    logger.warning("[exec] 跳过含路径穿越的命令: %s", token)
            full_cmd = f"cd {cwd} 2>/dev/null; {cmd}" if cwd else cmd
            result = sb.execute_command(full_cmd)
            return subprocess.CompletedProcess(
                args=["sandbox", cmd],
                returncode=0 if not result.startswith("Error:") else 1,
                stdout=result if not result.startswith("Error:") else "",
                stderr=result if result.startswith("Error:") else "",
            )
        except Exception as e:
            logger.warning("[exec] sandbox 执行失败，回退本地: %s", e)
    PATH = f"{os.path.expanduser('~/.elan/bin')}:{os.environ.get('PATH', '')}"
    return subprocess.run(
        ["bash", "-c", cmd], cwd=cwd, capture_output=True, text=True,
        timeout=300, env={**os.environ, "PATH": PATH},
    )


def read_with_sandbox(ws: str, f: str, sb=None) -> str:
    """E1: 在 sandbox 或本地读取文件。"""
    if sb is not None:
        try:
            fp = str(Path(ws) / f)
            _reject_path_traversal(fp)
            return sb.read_file(fp)
        except Exception as e:
            logger.warning("[read] sandbox 读文件失败，回退本地: %s", e)
    p = Path(ws) / f
    return p.read_text() if p.exists() else ""


def write_with_sandbox(ws: str, f: str, content: str, sb=None) -> None:
    """E1: 在 sandbox 或本地写入文件。"""
    if sb is not None:
        try:
            fp = str(Path(ws) / f)
            _reject_path_traversal(fp)
            sb.write_file(fp, content)
            return
        except Exception as e:
            logger.warning("[write] sandbox 写文件失败，回退本地: %s", e)
    (Path(ws) / f).write_text(content)


def scan_sorries(ws: str, sb=None) -> list[dict]:
    """E1: 扫描 sorry（使用 sandbox bash 或本地 bash）。"""
    r = exec_with_sandbox(
        "grep -rn 'sorry' --include='*.lean' . | grep -v '.lake/'", ws, sb,
    )
    items = []
    for line in r.stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split(":", 2)
        if len(parts) >= 2:
            items.append({"file": parts[0], "line": parts[1], "context": line})
    return items


def count_sorries(ws: str, sb=None) -> int:
    """E1: 计算 sorry 数量。"""
    r = exec_with_sandbox(
        "grep -rn 'sorry' --include='*.lean' . | grep -v '.lake/' | wc -l", ws, sb,
    )
    try:
        return int(r.stdout.strip())
    except ValueError:
        return 0


def build_project(ws: str, sb=None) -> tuple[bool, str]:
    """E1: lake build。"""
    r = exec_with_sandbox("lake build 2>&1", ws, sb)
    return r.returncode == 0, r.stdout + r.stderr


def verify_file(ws: str, f: str, sb=None) -> tuple[bool, list[dict]]:
    """E1: 增量编译验证 `lake env lean`。"""
    r = exec_with_sandbox(f"lake env lean {f} 2>&1", ws, sb)
    if r.returncode == 0:
        return (True, [])
    return (False, parse_lean_errors(r.stderr if r.stderr else r.stdout))


# ═══════════════════════════════════════════════════════════════════════
# E1: 自动化策略级联
# ═══════════════════════════════════════════════════════════════════════


def try_tactics_cascade(ws: str, f: str, content: str, sb=None) -> tuple[bool, str]:
    """G11: 对单个 sorry 尝试自动化策略。"""
    if "sorry" not in content:
        return (True, "no_sorries")
    tactics = AUTO_TACTICS_EXTENDED if USE_EXTENDED_TACTICS else AUTO_TACTICS
    for tactic in tactics:
        new_content = content.replace("sorry", f"by {tactic}", 1)
        try:
            write_with_sandbox(ws, f, new_content, sb)
            ok, _ = verify_file(ws, f, sb)
            if ok:
                logger.info("[tactic] %s: `%s` 成功", f, tactic)
                return (True, tactic)
        except Exception as e:
            logger.warning("[tactic] %s 策略 `%s` 异常: %s", f, tactic, e)
    write_with_sandbox(ws, f, content, sb)
    return (False, "")


def try_tactics_cascade_all(ws: str, f: str, sb=None) -> tuple[bool, list[str]]:
    """对文件中所有 sorry 逐一尝试级联策略。"""
    content = read_with_sandbox(ws, f, sb)
    tactics_used = []
    while "sorry" in content:
        ok, tactic = try_tactics_cascade(ws, f, content, sb)
        if ok:
            tactics_used.append(tactic)
            content = read_with_sandbox(ws, f, sb)
        else:
            write_with_sandbox(ws, f, content, sb)
            return (False, tactics_used)
    return (True, tactics_used)


# ═══════════════════════════════════════════════════════════════════════
# E1: 模型 / 配置
# ═══════════════════════════════════════════════════════════════════════


def get_model_name() -> str:
    """从 DeerFlow 配置读取默认模型名。"""
    try:
        from deerflow.config.app_config import get_app_config
        return get_app_config().models[0].name
    except Exception:
        return "deepseek-v4"


def make_model(name=None, think=False):
    """创建聊天模型实例。"""
    if name is None:
        name = get_model_name()
    from deerflow.models import create_chat_model
    return create_chat_model(name, thinking_enabled=think)


# ═══════════════════════════════════════════════════════════════════════
# Phase 1: 结构化错误解析
# ═══════════════════════════════════════════════════════════════════════


def classify_error(msg: str) -> str:
    """Classify Lean compiler error type from error message."""
    m = msg.lower()
    if "type mismatch" in m:
        return "type_mismatch"
    if any(kw in m for kw in [
        "unknown identifier", "unknown constant", "unknown declaration",
        "unknown theorem", "unknown lemma", "unknown definition",
    ]):
        return "unknown_identifier"
    if "failed to synthesize" in m:
        return "failed_to_synthesize"
    if "don't know how to" in m:
        return "don_know_how"
    if "invalid" in m:
        return "invalid"
    if any(kw in m for kw in ["expected", "unexpected"]):
        return "syntax_error"
    if "ambiguous" in m:
        return "ambiguous"
    if "is not a" in m or "has type" in m:
        return "type_error"
    return "other"


def parse_lean_errors(stderr: str) -> list[dict]:
    """Parse Lean compiler stderr into structured error records.

    Returns: [{type, severity, file, line, col, message, raw}, ...]
    """
    errors = []
    current = None
    for line in stderr.split("\n"):
        m = re.match(r'^(.+?):(\d+):(\d+):\s*(error|warning):\s*(.*)$', line)
        if m:
            if current:
                errors.append(current)
            current = {
                "type": classify_error(m.group(5)),
                "severity": m.group(4),
                "file": m.group(1),
                "line": int(m.group(2)),
                "col": int(m.group(3)),
                "message": m.group(5).strip(),
                "raw": line,
            }
        elif current:
            current["message"] = current["message"].rstrip("\n") + "\n" + line
    if current:
        errors.append(current)
    return errors


def format_errors(errors: list[dict], max_lines: int = 40) -> str:
    """Format structured errors as LLM-readable text."""
    lines = []
    for e in errors[:5]:
        lines.append(f"{e['type']} at {e['file']}:{e['line']}:{e['col']}")
        for l in e['message'].split("\n")[:8]:
            lines.append(f"  {l}")
        lines.append("")
    combined = "\n".join(lines)
    if len(combined) > max_lines * 80:
        combined = combined[:max_lines * 80] + "\n... (truncated)"
    return combined


# ═══════════════════════════════════════════════════════════════════════
# Phase 2: 目标提取
# ═══════════════════════════════════════════════════════════════════════


def extract_goal(lines: list[str], target_line: int) -> dict:
    """Extract the theorem/lemma context around a sorry line.

    Returns: {"signature": str, "line": int, "source_lines": [str]}
    """
    decl_start = -1
    decl_pattern = re.compile(
        r'^\s*(theorem|lemma|def|example|instance|corollary|class|structure|abbrev)\b'
    )
    for i in range(min(target_line, len(lines)) - 1, -1, -1):
        if decl_pattern.match(lines[i]):
            decl_start = i
            break

    if decl_start == -1:
        return {"signature": "", "line": target_line, "source_lines": lines}

    decl_lines = []
    for i in range(decl_start, min(decl_start + 30, len(lines))):
        decl_lines.append(lines[i])
        if i >= target_line - 1:
            break
        if i > decl_start and decl_pattern.match(lines[i]):
            break

    signature = "\n".join(decl_lines).strip()
    ctx_before = lines[max(0, decl_start - 5):decl_start]
    ctx_after = lines[target_line:min(target_line + 5, len(lines))]

    return {
        "signature": signature,
        "line": target_line,
        "source_lines": ctx_before + ["--- [declaration] ---"] + decl_lines + ["--- [after sorry] ---"] + ctx_after,
    }


# ═══════════════════════════════════════════════════════════════════════
# Phase 3: 自动化策略级联
# ═══════════════════════════════════════════════════════════════════════


AUTO_TACTICS = ["rfl", "simp", "ring", "linarith", "omega", "aesop", "grind"]

# G11: 扩展 tactics（exact?/apply? — 可能超时，默认不启用）
AUTO_TACTICS_EXTENDED = ["rfl", "simp", "ring", "linarith", "omega", "aesop", "grind", "exact?", "apply?"]
USE_EXTENDED_TACTICS = False  # 设为 True 启用 exact?/apply?
def search_matlas(query: str, max_results: int = 10) -> list[dict]:
    '''G6: Matlas API — semantic search over 8.07M mathematical statements.
    POST https://matlas.ai/api/search
    Falls back to leansearch.net on failure.
    '''
    if max_results < 10:
        max_results = 10  # API requires >= 10
    try:
        import ssl, urllib.request
        ctx = ssl.create_default_context()
        req = urllib.request.Request(
            "https://matlas.ai/api/search",
            data=json.dumps({"query": query, "num_results": max_results}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            if isinstance(data, list) and data:
                logger.info("[matlas] %d results for: %s", len(data), query[:80])
                return data
    except Exception as e:
        logger.warning("[matlas] API 不可用: %s", e)
    return []
def save_memory(ws: str, state: dict) -> None:
    '''G7: 持久化 attempt_history 和关键状态到 .archon-journal/memory.json。'''
    import json as _json
    journal = Path(ws) / ".archon-journal"
    journal.mkdir(parents=True, exist_ok=True)
    data = {
        "attempt_history": state.get("attempt_history", []),
        "failure_modes": state.get("failure_modes", {}),
        "informal_hints": state.get("informal_hints", {}),
        "stage": state.get("stage", ""),
        "loop_count": state.get("loop_count", 0),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    with open(journal / "memory.json", "w") as f:
        _json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("[memory] saved %d attempts to memory.json", len(data["attempt_history"]))

def load_memory(ws: str) -> dict:
    '''G7: 从 .archon-journal/memory.json 加载持久化状态。'''
    import json as _json
    mem_path = Path(ws) / ".archon-journal" / "memory.json"
    if not mem_path.exists():
        return {}
    try:
        with open(mem_path) as f:
            data = _json.load(f)
        logger.info("[memory] loaded %d attempts from memory.json",
                    len(data.get("attempt_history", [])))
        return data
    except Exception as e:
        logger.warning("[memory] 加载失败: %s", e)
        return {}





# ═══════════════════════════════════════════════════════════════════════
# 失败模式分类
# ═══════════════════════════════════════════════════════════════════════


FAILURE_KEYWORDS = {
    "missing_infrastructure": [
        "unknown identifier", "unknown constant", "unknown declaration",
        "unknown theorem", "unknown lemma", "unknown definition",
        "not found in", "has no field", "unknown namespace",
    ],
    "typeclass": [
        "failed to synthesize", "typeclass", "instance",
        "no instances", "is not a type", "has no type class",
    ],
    "wrong_construction": [
        "type mismatch", "expected", "don't know how to",
        "argument", "has type", "is not a function",
        "not a type", "unexpected",
    ],
}


def classify_failure(attempt: dict) -> list[str]:
    """Return list of failure modes from an attempt record."""
    err = attempt.get("lean_error", "").lower()
    modes = []
    for mode, keywords in FAILURE_KEYWORDS.items():
        if any(kw in err for kw in keywords):
            modes.append(mode)
    if attempt.get("result") == "abandoned":
        modes.append("early_stopping")
    if attempt.get("result") == "build_failed":
        modes.append("compilation_error")
    return modes if modes else ["unknown"]


# ═══════════════════════════════════════════════════════════════════════
# 通用工具
# ═══════════════════════════════════════════════════════════════════════


def make_attempt(file: str, line: str, loop: int, strategy: str, result: str,
                 lean_error: str = "", failure_mode: str = "", **kw) -> dict:
    """Create an attempt record with auto-timestamp."""
    return {
        "file": file, "line": line, "loop": loop,
        "strategy": strategy, "result": result,
        "lean_error": lean_error, "failure_mode": failure_mode,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        **kw,
    }


def extract_code(text: str) -> str:
    """Extract Lean code from ```lean ... ``` blocks."""
    m = re.search(r'```(?:lean)?\s*\n?(.*?)```', text, re.DOTALL)
    return m.group(1).strip() if m else text.strip()


def extract_json(text: str) -> dict:
    """Extract first JSON object from text."""
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {}


def goal_context(goals: list[dict]) -> str:
    """Format extracted goals into an LLM-readable context block."""
    lines = ["## 单文件目标分解\n"]
    for i, g in enumerate(goals):
        if not g.get("signature"):
            continue
        file_ref = g.get("file", f"target_{i+1}")
        line_ref = g.get("line", 0)
        lines.append(f"### 目标 {i+1}: {file_ref}:{line_ref}")
        lines.append(f"```lean\n{g['signature']}\n```\n")
    return "\n".join(lines)
