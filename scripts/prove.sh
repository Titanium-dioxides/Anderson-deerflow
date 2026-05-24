#!/usr/bin/env bash
# ============================================================================
# archon-deerflow prove — 输入命题，输出 Lean 证明
#
# 用法:
#   ./scripts/prove.sh "命题文本"
#   ./scripts/prove.sh -f problem.txt
#   echo "1+1=2" | ./scripts/prove.sh
#   ./scripts/prove.sh -f statement.txt -n my-proof -c RETRIEVAL
#
# 输出在: workspace/<project>/formal/src/*.lean
#         workspace/<project>/outputs/
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── 参数解析 ──
STATEMENT=""
PROJECT="proof-$(date +%Y%m%d-%H%M%S)"
CATEGORY="SIMPLE"
FILE=""

usage() {
    echo "用法: prove.sh [选项] [命题文本]"
    echo ""
    echo "选项:"
    echo "  -f FILE        从文件读取命题"
    echo "  -n NAME        项目名称 (默认: proof-时间戳)"
    echo "  -c CATEGORY    问题类别: SIMPLE / RETRIEVAL / COMPLEX (默认: SIMPLE)"
    echo "  -h             显示帮助"
    echo ""
    echo "示例:"
    echo "  ./scripts/prove.sh 'Prove that there are infinitely many primes.'"
    echo "  ./scripts/prove.sh -f ./my-theorem.txt -n prime-proof -c RETRIEVAL"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -f) FILE="$2"; shift 2 ;;
        -n) PROJECT="$2"; shift 2 ;;
        -c) CATEGORY="$2"; shift 2 ;;
        -h) usage ;;
        *)  STATEMENT="$1"; shift ;;
    esac
done

# ── 获取命题 ──
if [[ -n "$FILE" ]]; then
    STATEMENT=$(cat "$FILE")
elif [[ -z "$STATEMENT" ]]; then
    # 从标准输入读取
    if [[ ! -t 0 ]]; then
        STATEMENT=$(cat)
    else
        usage
    fi
fi

THREAD_ID="thread-${PROJECT}"
echo "========================================"
echo " archon-deerflow: 数学定理证明"
echo "========================================"
echo "  项目:     ${PROJECT}"
echo "  类别:     ${CATEGORY}"
echo "  线程:     ${THREAD_ID}"
echo "  命题:     $(echo "${STATEMENT}" | head -1 | cut -c1-80)"
echo "========================================"

# ── 登录（如需要）──
COOKIE_FILE="/tmp/deerflow-cookies-${PROJECT}.txt"
if ! curl -s -o /dev/null -w "%{http_code}" http://localhost:2026/health | grep -q 200; then
    echo "Gateway 未运行，请先启动: docker compose up -d"
    exit 1
fi

# ── 调用 E2E workflow ──
echo ""
echo "正在运行端到端证明 pipeline ..."

RESULT=$(docker exec archon-deerflow-gateway python3 -c "
import sys, json, os
sys.path.insert(0, '/app/deer-flow/overlay/backend')
os.environ['ARCHON_DEERFLOW_RUNTIME_ROOT'] = '/app/deer-flow/.deerflow_runtime'
from workflows import run_e2e_workflow

result = run_e2e_workflow(
    thread_id='${THREAD_ID}',
    statement='''$(echo "${STATEMENT}" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))")'''',
    project_name='${PROJECT}',
    problem_id='$(echo "${PROJECT}" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9-_')',
    category='${CATEGORY}',
    max_loops=3,
    parallelism=1,
)
print(json.dumps({
    'stage': result.get('stage'),
    'all_checks_pass': result.get('all_checks_pass'),
    'per_phase': {p: {'passed': i['passed'], 'failed': i['failed'], 'stage': i['stage']}
                  for p, i in result.get('structural_report', {}).get('per_phase', {}).items()},
    'project_root': result.get('phase1_result', {}).get('project_root', '')
}, ensure_ascii=False))
" 2>&1)

echo ""
echo "----------------------------------------"
echo "$RESULT" | python3 -c "
import sys, json
r = json.load(sys.stdin)
print('结果:')
print(f'  总阶段: {r[\"stage\"]}')
for p, i in r.get('per_phase', {}).items():
    total = i['passed'] + i['failed']
    icon = '✓' if i['failed'] == 0 else '⚠'
    print(f'  {icon} {p}: {i[\"passed\"]}/{total} passed ({i[\"stage\"]})')
" 2>/dev/null || echo "$RESULT"

# ── 输出产物位置 ──
WORKSPACE="${REPO_ROOT}/workspace/${PROJECT}"
CONTAINER_WS="/app/deer-flow/.deerflow_runtime/threads/${THREAD_ID}/user-data/workspace/${PROJECT}"

echo ""
echo "========================================"
echo " 证明产物"
echo "========================================"

# 检查非形式化证明
if docker exec archon-deerflow-gateway test -f "${CONTAINER_WS}/informal/proofs/candidate_proof.md" 2>/dev/null; then
    echo ""
    echo "── 非形式化证明 (Phase 2) ──"
    docker exec archon-deerflow-gateway cat "${CONTAINER_WS}/informal/proofs/candidate_proof.md"
fi

# 检查 Lean 代码
echo ""
echo "── Lean 形式化代码 (Phase 3-4) ──"
for f in $(docker exec archon-deerflow-gateway find "${CONTAINER_WS}/formal/src" -name "*.lean" -type f 2>/dev/null); do
    echo ""
    echo "──── $f ────"
    docker exec archon-deerflow-gateway cat "$f"
done

# 检查最终报告
echo ""
echo "── Manifest ──"
docker exec archon-deerflow-gateway cat "${CONTAINER_WS}/manifests/phase5_polish.json" 2>/dev/null | python3 -c "
import sys, json
m = json.load(sys.stdin)
r = m.get('results', {})
print(f'  抱歉数: {r.get(\"sorry_axiom_check\", {}).get(\"total_sorry\", \"?\")}')
print(f'  公理数: {r.get(\"sorry_axiom_check\", {}).get(\"total_axiom\", \"?\")}')
print(f'  编译:   {r.get(\"compile_check\", {}).get(\"pass\", \"?\")}')
" 2>/dev/null || true

echo ""
echo "========================================"
echo " 完成"
echo "========================================"
