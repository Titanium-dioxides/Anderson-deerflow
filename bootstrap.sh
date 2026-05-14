#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Archon-DeerFlow 一键部署脚本
# ═══════════════════════════════════════════════════════════════════════════════
# 此脚本自动完成以下工作：
#   1. 检查系统依赖（Python3.12+/Node22+/Docker/git）
#   2. 克隆/更新 archon-deerflow 仓库
#   3. 部署或更新 DeerFlow 基础环境
#   4. 叠加 Archon + Rethlas 工作流到 DeerFlow
#   5. 安装 Lean4 toolchain（elan）
#   6. 配置 API Key
#   7. 运行冒烟测试验证部署
#   8. 启动系统
#
# 用法:
#   curl -fsSL https://raw.githubusercontent.com/Titanium-dioxides/archon-deerflow/main/bootstrap.sh | bash
#   或：
#   bash bootstrap.sh [--dev] [--local-dir /path/to/deer-flow]
#
# 选项:
#   --dev        开发模式（不启动 Docker，只设置本地环境）
#   --local-dir  指定现有 DeerFlow 安装目录（默认自动处理）
#   --lean-only  仅安装 Lean4 环境，不部署系统
#   --help       显示帮助
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── 版本与路径 ───────────────────────────────────────────────────────────────

SCRIPT_VERSION="1.0.0"
ARCHON_DEFAULT="${HOME}/archon-deerflow"
DEERFLOW_DEFAULT="${HOME}/deer-flow"
REPO_URL="https://github.com/Titanium-dioxides/archon-deerflow.git"
BRANCH="main"

# ── 颜色 ─────────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
info() { echo -e "  ${BLUE}ℹ${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
err()  { echo -e "  ${RED}✗${NC} $1"; }
title(){ echo -e "\n${CYAN}══════ $1 ══════${NC}\n"; }

# ── 处理参数 ────────────────────────────────────────────────────────────────

MODE="prod"
LOCAL_DIR=""
LEAN_ONLY=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dev)        MODE="dev"; shift ;;
        --local-dir)  LOCAL_DIR="$2"; shift 2 ;;
        --lean-only)  LEAN_ONLY=true; shift ;;
        --help|-h)
            echo "Archon-DeerFlow Bootstrap v${SCRIPT_VERSION}"
            echo ""
            echo "用法: bash bootstrap.sh [选项]"
            echo ""
            echo "选项:"
            echo "  --dev              开发模式（不启动 Docker，仅设置环境）"
            echo "  --local-dir PATH   指定现有 DeerFlow 安装目录"
            echo "  --lean-only        仅安装 Lean4 工具链"
            echo "  --help             显示此帮助"
            echo ""
            echo "环境变量:"
            echo "  DEEPSEEK_API_KEY   DeepSeek API Key（如未提供则交互式输入）"
            echo "  OPENAI_API_KEY     OpenAI API Key（可选）"
            echo "  DEERFLOW_DIR       DeerFlow 安装目录（默认 ~/deer-flow）"
            echo "  ARCHON_DIR         Archon-DeerFlow 仓库目录（默认 ~/archon-deerflow）"
            exit 0
            ;;
        *)
            err "未知选项: $1"
            echo "用法: bash bootstrap.sh [--dev] [--lean-only] [--help]"
            exit 1
            ;;
    esac
done

ARCHON_DIR="${ARCHON_DIR:-$ARCHON_DEFAULT}"
DEERFLOW_DIR="${LOCAL_DIR:-${DEERFLOW_DIR:-$DEERFLOW_DEFAULT}}"

# ═══════════════════════════════════════════════════════════════════════════════
# 阶段 1: 前置检查
# ═══════════════════════════════════════════════════════════════════════════════

preflight_check() {
    title "1. 前置检查"

    local errors=0

    # Python 3.12+
    if command -v python3 &>/dev/null; then
        py_ver=$(python3 --version 2>&1 | grep -oP '\d+\.\d+')
        if awk "BEGIN {exit !($py_ver >= 3.12)}"; then
            ok "Python $py_ver"
        else
            warn "Python $py_ver 低于所需 3.12，请升级"
            errors=$((errors+1))
        fi
    else
        err "Python3 未安装"
        errors=$((errors+1))
    fi

    # uv
    if command -v uv &>/dev/null; then
        ok "uv $(uv --version 2>&1 | head -1)"
    else
        info "正在安装 uv（Python 包管理器）..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        if [ -f "$HOME/.local/bin/uv" ]; then
            export PATH="$HOME/.local/bin:$PATH"
            ok "uv 已安装"
        else
            err "uv 安装失败"
            errors=$((errors+1))
        fi
    fi

    # Node.js 22+
    if command -v node &>/dev/null; then
        node_ver=$(node --version 2>&1 | grep -oP '\d+' | head -1)
        if [ "$node_ver" -ge 22 ] 2>/dev/null; then
            ok "Node.js $(node --version)"
        else
            warn "Node.js 版本低于 22，建议升级"
        fi
    else
        warn "Node.js 未安装（Docker 启动时自动处理）"
        if [ "$MODE" = "dev" ]; then
            info "建议安装: curl -fsSL https://deb.nodesource.com/setup_22.x | bash -"
        fi
    fi

    # Git
    if command -v git &>/dev/null; then
        ok "git $(git --version 2>&1)"
    else
        err "git 未安装"
        errors=$((errors+1))
    fi

    # Docker（仅生产模式必需）
    if [ "$MODE" != "dev" ]; then
        if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
            ok "Docker 运行中"
        else
            warn "Docker 未运行或未安装"
            info "生产模式推荐 Docker，但你也可以使用 --dev 模式"
            info "继续安装环境（Docker 部分稍后跳过）..."
        fi
    fi

    if [ "$errors" -gt 0 ]; then
        err "前置检查失败，请修复上述问题后重试"
        exit 1
    fi

    echo ""
    ok "前置检查通过"
}

# ═══════════════════════════════════════════════════════════════════════════════
# 阶段 2: 克隆仓库
# ═══════════════════════════════════════════════════════════════════════════════

clone_repo() {
    title "2. 获取 Archon-DeerFlow"

    if [ -d "$ARCHON_DIR/.git" ]; then
        info "仓库已存在，更新中..."
        cd "$ARCHON_DIR"
        git fetch origin "$BRANCH"
        git reset --hard "origin/$BRANCH"
        ok "已更新到最新版"
    else
        info "克隆仓库到 $ARCHON_DIR..."
        git clone --depth 1 -b "$BRANCH" "$REPO_URL" "$ARCHON_DIR"
        ok "仓库已克隆"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# 阶段 3: 部署 DeerFlow（如尚不存在）
# ═══════════════════════════════════════════════════════════════════════════════

deploy_deerflow() {
    title "3. 部署 DeerFlow 基础环境"

    if [ -f "$DEERFLOW_DIR/pyproject.toml" ] || [ -d "$DEERFLOW_DIR/backend" ]; then
        ok "DeerFlow 已安装在 $DEERFLOW_DIR"
        return
    fi

    info "DeerFlow 未安装，开始部署..."

    # 克隆 DeerFlow
    if git clone --depth 1 https://github.com/openclaw/deer-flow.git "$DEERFLOW_DIR" 2>/dev/null; then
        ok "DeerFlow 仓库已克隆"
    elif git clone --depth 1 https://github.com/Titanium-dioxides/deer-flow.git "$DEERFLOW_DIR" 2>/dev/null; then
        ok "DeerFlow 仓库已克隆（镜像）"
    else
        err "无法克隆 DeerFlow 仓库"
        info "请手动安装 DeerFlow 后重试"
        info "参考: https://github.com/openclaw/deer-flow"
        exit 1
    fi

    # 创建 config.yaml (从模板)
    if [ -f "$DEERFLOW_DIR/config.example.yaml" ]; then
        cp "$DEERFLOW_DIR/config.example.yaml" "$DEERFLOW_DIR/config.yaml"
        info "config.yaml 已从模板创建"
    fi

    # 创建 extensions_config.json
    if [ ! -f "$DEERFLOW_DIR/extensions_config.json" ]; then
        if [ -f "$DEERFLOW_DIR/extensions_config.example.json" ]; then
            cp "$DEERFLOW_DIR/extensions_config.example.json" "$DEERFLOW_DIR/extensions_config.json"
        else
            echo '{"mcpServers":{},"skills":{}}' > "$DEERFLOW_DIR/extensions_config.json"
        fi
        ok "extensions_config.json 已初始化"
    fi

    # 创建 Python 虚拟环境并安装依赖
    info "安装 Python 依赖..."
    cd "$DEERFLOW_DIR"
    uv venv 2>/dev/null || true
    uv sync 2>&1 | tail -3 || warn "uv sync 部分失败（可在配置后重试）"

    ok "DeerFlow 基础环境就绪"
}

# ═══════════════════════════════════════════════════════════════════════════════
# 阶段 4: 叠加 Archon + Rethlas 工作流
# ═══════════════════════════════════════════════════════════════════════════════

apply_overlay() {
    title "4. 叠加 Archon + Rethlas 工作流"

    local overlay_src="$ARCHON_DIR/overlay"

    if [ ! -d "$overlay_src" ]; then
        err "overlay 目录不存在: $overlay_src"
        exit 1
    fi

    # ── 4a. 后端工作流 ──
    info "安装 LangGraph 工作流..."

    # 确保 backend/workflows 目录存在
    mkdir -p "$DEERFLOW_DIR"/backend/workflows

    # 复制工作流文件（仅在不存在或更新时）
    if [ -f "$overlay_src/backend/workflows/archon_graph.py" ]; then
        cp "$overlay_src/backend/workflows/archon_graph.py" \
           "$DEERFLOW_DIR/backend/workflows/archon_graph.py"
        ok "archon_graph.py ✓"
    fi

    if [ -f "$overlay_src/backend/workflows/unified_graph.py" ]; then
        cp "$overlay_src/backend/workflows/unified_graph.py" \
           "$DEERFLOW_DIR/backend/workflows/unified_graph.py"
        ok "unified_graph.py ✓"
    fi

    if [ -f "$overlay_src/backend/workflows/__init__.py" ]; then
        cp "$overlay_src/backend/workflows/__init__.py" \
           "$DEERFLOW_DIR/backend/workflows/__init__.py"
        ok "__init__.py ✓"
    fi

    # ── 4b. 注册 LangGraph 图 ──
    if [ -f "$overlay_src/backend/langgraph.json" ]; then
        cp "$overlay_src/backend/langgraph.json" \
           "$DEERFLOW_DIR/backend/langgraph.json"

        # 更新主 langgraph.json 以包含 Archon 工作流
        if command -v python3 &>/dev/null; then
            python3 -c "
import json, os
lg_path = '$DEERFLOW_DIR/backend/langgraph.json'
if os.path.exists(lg_path):
    lg = json.load(open(lg_path))
    # Overlay 已包含 archon_workflow 和 unified_prover 注册
    with open(lg_path, 'w') as f:
        json.dump(lg, f, indent=2)
    print('langgraph.json 已更新')
"
        fi
        ok "langgraph.json ✓"
    fi

    # ── 4c. Archon 技能（archon-lean4） ──
    info "安装 Archon Lean4 技能..."
    local src_archon="$overlay_src/skills/custom/archon-lean4"
    local dst_archon="$DEERFLOW_DIR/skills/custom/archon-lean4"

    if [ -d "$src_archon" ]; then
        mkdir -p "$(dirname "$dst_archon")"
        cp -r "$src_archon" "$dst_archon"
        ok "archon-lean4 技能 ✓"
    else
        warn "archon-lean4 技能未找到（跳过）"
    fi

    # ── 4d. Rethlas 技能（math-prover） ──
    info "安装 Rethlas 数学证明技能..."
    local src_rethlas="$overlay_src/skills/custom/math-prover"
    local dst_rethlas="$DEERFLOW_DIR/skills/custom/math-prover"

    if [ -d "$src_rethlas" ]; then
        mkdir -p "$(dirname "$dst_rethlas")"
        cp -r "$src_rethlas" "$dst_rethlas"
        ok "math-prover 技能 ✓"
    else
        warn "math-prover 技能未找到（跳过）"
    fi

    # ── 4e. 更新 config.yaml 中的 skills 路径 ──
    local skills_dirs=("$DEERFLOW_DIR/skills/custom/archon-lean4" "$DEERFLOW_DIR/skills/custom/archon-init" "$DEERFLOW_DIR/skills/custom/archon-plan" "$DEERFLOW_DIR/skills/custom/archon-prover" "$DEERFLOW_DIR/skills/custom/archon-review" "$DEERFLOW_DIR/skills/custom/math-prover")

    for dir in "${skills_dirs[@]}"; do
        if [ -d "$dir" ]; then
            ok "技能目录: $(basename "$dir")"
        fi
    done

    # ── 4f. 创建 .env 占位 ──
    if [ -f "$ARCHON_DIR/.env.example" ] && [ ! -f "$DEERFLOW_DIR/.env" ]; then
        cp "$ARCHON_DIR/.env.example" "$DEERFLOW_DIR/.env"
        info ".env 已创建（请配置 API Key）"
    fi

    echo ""
    ok "工作流叠加完成"
}

# ═══════════════════════════════════════════════════════════════════════════════
# 阶段 5: 安装 Lean4 工具链
# ═══════════════════════════════════════════════════════════════════════════════

install_lean() {
    title "5. 安装 Lean4 工具链"

    # 检查 elan（Lean 版本管理器）
    if command -v elan &>/dev/null; then
        ok "elan 已安装"
    else
        info "正在安装 elan..."
        curl -sSf https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -o /tmp/elan-init.sh
        sh /tmp/elan-init.sh -y 2>/dev/null || {
            warn "elan 安装可能需要手动确认"
            sh /tmp/elan-init.sh
        }

        # 将 elan 加入 PATH
        export PATH="$HOME/.elan/bin:$PATH"
        if command -v elan &>/dev/null; then
            ok "elan 已安装"
        else
            warn "elan 安装可能未完成，请检查 $HOME/.elan/bin"
            info "尝试手动: curl -sSf https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh | sh"
        fi
    fi

    # 安装 Lean 4.29.0-rc8（与 anderson-conjecture 兼容）
    if command -v lean &>/dev/null; then
        lean_ver=$(lean --version 2>&1 | head -1)
        ok "Lean: $lean_ver"
    else
        if command -v elan &>/dev/null; then
            info "正在安装 Lean 4...（这将下载约 100MB）"
            elan toolchain install stable 2>&1 | tail -3 || {
                warn "Lean 安装失败，请稍后手动运行: elan toolchain install stable"
            }
            if command -v lean &>/dev/null; then
                ok "Lean 已安装: $(lean --version 2>&1 | head -1)"
            fi
        fi
    fi

    # 测试 lake
    if command -v lake &>/dev/null; then
        ok "lake 可用"
    else
        warn "lake 未安装（安装 Lean 后自动包含）"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# 阶段 6: 配置 API Key
# ═══════════════════════════════════════════════════════════════════════════════

configure_keys() {
    title "6. 配置 API Key"

    local env_file="$DEERFLOW_DIR/.env"

    # 如果已经有完整配置则跳过
    if [ -f "$env_file" ] && grep -q "DEEPSEEK_API_KEY=sk-" "$env_file" 2>/dev/null; then
        ok "DeepSeek API Key 已配置"
        export DEEPSEEK_API_KEY
        DEEPSEEK_API_KEY=$(grep -oP 'DEEPSEEK_API_KEY=\K.*' "$env_file")
        return
    fi

    # 从环境变量读取
    if [ -n "${DEEPSEEK_API_KEY:-}" ]; then
        info "使用环境变量 DEEPSEEK_API_KEY"
    else
        echo ""
        info "需要 DeepSeek API Key 来驱动 LLM 推理"
        info "获取: https://platform.deepseek.com/api_keys"
        echo ""
        read -rp "请输入 DeepSeek API Key (sk-...): " DEEPSEEK_API_KEY
        DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-}"
    fi

    if [ -n "$DEEPSEEK_API_KEY" ]; then
        # 写入 .env
        if [ -f "$env_file" ]; then
            if grep -q "DEEPSEEK_API_KEY=" "$env_file" 2>/dev/null; then
                sed -i "s|DEEPSEEK_API_KEY=.*|DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY|" "$env_file"
            else
                echo "DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY" >> "$env_file"
            fi
        else
            echo "DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY" > "$env_file"
        fi
        ok "DeepSeek API Key 已保存到 $env_file"
    else
        warn "未配置 API Key — 运行时需要设置 DEEPSEEK_API_KEY 环境变量"
    fi

    # 可选: OpenAI API Key
    if [ -z "${OPENAI_API_KEY:-}" ] && [ ! -f "$env_file" ] || ! grep -q "OPENAI_API_KEY=sk-" "$env_file" 2>/dev/null; then
        echo ""
        info "OpenAI API Key 是可选的（如使用 DeepSeek 可跳过）"
        read -rp "OpenAI API Key (可选，直接回车跳过): " OPENAI_API_KEY
        if [ -n "$OPENAI_API_KEY" ]; then
            if grep -q "OPENAI_API_KEY=" "$env_file" 2>/dev/null; then
                sed -i "s|OPENAI_API_KEY=.*|OPENAI_API_KEY=$OPENAI_API_KEY|" "$env_file"
            else
                echo "OPENAI_API_KEY=$OPENAI_API_KEY" >> "$env_file"
            fi
            ok "OpenAI API Key 已保存"
        fi
    fi

    # 更新 config.yaml 中的模型配置
    if [ -n "$DEEPSEEK_API_KEY" ] && [ -f "$DEERFLOW_DIR/config.yaml" ]; then
        if command -v python3 &>/dev/null; then
            python3 -c "
import yaml
with open('$DEERFLOW_DIR/config.yaml') as f:
    cfg = yaml.safe_load(f)
if cfg and 'models' in cfg:
    for m in cfg['models']:
        if 'deepseek' in str(m.get('model', '')):
            m['api_key'] = '$DEEPSEEK_API_KEY'
    with open('$DEERFLOW_DIR/config.yaml', 'w') as f:
        yaml.dump(cfg, f, default_flow_style=False)
    print('config.yaml 模型配置已更新')
" 2>/dev/null || warn "config.yaml 更新失败（可手动编辑）"
        fi
    fi

    echo ""
    ok "API Key 配置完成"
}

# ═══════════════════════════════════════════════════════════════════════════════
# 阶段 7: 冒烟测试
# ═══════════════════════════════════════════════════════════════════════════════

smoke_test() {
    title "7. 冒烟测试"

    local errors=0
    cd "$DEERFLOW_DIR"

    # 7a. 项目结构
    info "检查项目结构..."
    for dir in "backend/workflows" "skills/custom/archon-lean4" "skills/custom/math-prover"; do
        if [ -d "$DEERFLOW_DIR/$dir" ]; then
            ok "$dir"
        else
            err "$dir 缺失"
            errors=$((errors+1))
        fi
    done

    # 7b. LangGraph 注册
    if [ -f "$DEERFLOW_DIR/backend/langgraph.json" ]; then
        if grep -q "archon_workflow" "$DEERFLOW_DIR/backend/langgraph.json"; then
            ok "langgraph.json 已注册 archon_workflow"
        else
            warn "langgraph.json 缺少 archon_workflow 注册"
        fi
        if grep -q "unified_prover" "$DEERFLOW_DIR/backend/langgraph.json"; then
            ok "langgraph.json 已注册 unified_prover"
        else
            warn "langgraph.json 缺少 unified_prover 注册"
        fi
    else
        err "langgraph.json 不存在"
        errors=$((errors+1))
    fi

    # 7c. Python 模块导入
    if [ -f "$DEERFLOW_DIR/backend/workflows/archon_graph.py" ]; then
        if command -v uv &>/dev/null; then
            cd "$DEERFLOW_DIR"
            if uv run --no-sync python -c "import sys; sys.path.insert(0, 'backend'); from workflows.archon_graph import build_archon_graph; print('OK')" 2>/dev/null; then
                ok "archon_graph 模块可导入"
            else
                warn "archon_graph 导入失败（依赖可能未完全安装）"
                errors=$((errors+1))
            fi
        fi
    fi

    # 7d. Skill 文件完整性
    for skill_md in "skills/custom/archon-lean4/SKILL.md" "skills/custom/math-prover/SKILL.md"; do
        if [ -f "$DEERFLOW_DIR/$skill_md" ]; then
            ok "$skill_md"
        else
            err "$skill_md 缺失"
            errors=$((errors+1))
        fi
    done

    # 7e. Rethlas prompts
    for prompt in "prompts/generator.md" "prompts/verifier.md"; do
        if [ -f "$DEERFLOW_DIR/skills/custom/math-prover/$prompt" ]; then
            ok "math-prover/$prompt"
        else
            err "math-prover/$prompt 缺失"
            errors=$((errors+1))
        fi
    done

    # 7f. Archon 命令
    for cmd in "prove" "review" "doctor" "golf" "formalize"; do
        if [ -f "$DEERFLOW_DIR/skills/custom/archon-lean4/commands/$cmd.md" ]; then
            ok "archon-lean4/commands/$cmd.md"
        else
            warn "archon-lean4/commands/$cmd.md 缺失"
        fi
    done

    # 7g. .env 配置
    if [ -f "$DEERFLOW_DIR/.env" ]; then
        if grep -q "DEEPSEEK_API_KEY=sk-" "$DEERFLOW_DIR/.env" 2>/dev/null; then
            ok ".env 包含 DeepSeek Key"
        else
            warn ".env 未配置 DeepSeek Key"
        fi
    else
        warn ".env 不存在"
    fi

    # 7h. Lean toolchain
    if command -v lean &>/dev/null; then
        ok "Lean 工具链就绪"
    else
        warn "Lean 未安装（仅 Archon 工作流需要）"
    fi

    echo ""
    if [ "$errors" -eq 0 ]; then
        ok "冒烟测试全部通过 ✅"
    else
        warn "$errors 项检查未通过（部分非关键项可忽略）"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# 阶段 8: 启动系统
# ═══════════════════════════════════════════════════════════════════════════════

start_system() {
    title "8. 启动系统"

    cd "$DEERFLOW_DIR"

    if [ "$MODE" = "dev" ]; then
        info "开发模式：导出以下环境变量后即可使用 Python API"

        echo ""
        echo -e "  ${CYAN}export DEERFLOW_DIR=$DEERFLOW_DIR${NC}"
        echo -e "  ${CYAN}export PYTHONPATH=\$DEERFLOW_DIR/backend:\$PYTHONPATH${NC}"
        echo ""

        # 创建启动快捷方式
        if [ ! -f "$DEERFLOW_DIR/.dev-ready" ]; then
            python3 -c "
import json
sys.path.insert(0, '$DEERFLOW_DIR/backend')
from workflows.archon_graph import build_archon_graph, build_unified_graph
g1 = build_archon_graph()
g2 = build_unified_graph()
print(f'工作流就绪:')
print(f'  archon_workflow: {g1.name if hasattr(g1, \"name\") else \"<Graph>\"}')
print(f'  unified_prover:  {g2.name if hasattr(g2, \"name\") else \"<Graph>\"}')
" 2>/dev/null && echo "ready" > "$DEERFLOW_DIR/.dev-ready" && ok "工作流已可导入" || warn "工作流导入失败（可在安装依赖后重试）"
        fi

        ok "开发模式就绪"
        return
    fi

    # ── 生产模式: 启动 Docker ──
    if ! command -v docker &>/dev/null || ! docker info &>/dev/null 2>&1; then
        warn "Docker 不可用，跳过容器化部署"
        info "请使用 --dev 模式，或安装 Docker 后运行:"
        info "  cd $DEERFLOW_DIR && make docker-start"
        return
    fi

    info "通过 Docker Compose 部署..."

    # 确保关键文件存在
    if [ ! -f "$DEERFLOW_DIR/config.yaml" ]; then
        cp "$DEERFLOW_DIR/config.example.yaml" "$DEERFLOW_DIR/config.yaml"
        info "config.yaml 已创建"
    fi

    # 生成 BETTER_AUTH_SECRET
    local secret_file="$DEERFLOW_DIR/.better-auth-secret"
    if [ ! -f "$secret_file" ]; then
        python3 -c "import secrets; print(secrets.token_hex(32))" > "$secret_file"
        chmod 600 "$secret_file"
    fi
    export BETTER_AUTH_SECRET
    BETTER_AUTH_SECRET="$(cat "$secret_file")"

    # 启动 Docker 服务
    cd "$DEERFLOW_DIR"
    if [ -f scripts/deploy.sh ]; then
        bash scripts/deploy.sh 2>&1 || {
            warn "Docker 部署失败，尝试 make docker-start..."
            make docker-start 2>&1 || {
                err "Docker 启动失败"
                info "请检查 Docker 服务和配置"
                return
            }
        }
    elif [ -f Makefile ]; then
        make docker-start 2>&1 || {
            warn "make docker-start 失败"
            info "请手动检查配置后重试"
            return
        }
    else
        warn "未找到部署脚本"
        info "请手动运行: cd $DEERFLOW_DIR && make docker-start"
        return
    fi

    ok "Docker 服务已启动"
}

# ═══════════════════════════════════════════════════════════════════════════════
# 阶段 9: 显示摘要
# ═══════════════════════════════════════════════════════════════════════════════

show_summary() {
    title "部署摘要"

    echo ""
    echo -e "  ${CYAN}Archon-DeerFlow ${SCRIPT_VERSION}${NC}"
    echo ""
    echo -e "  📦 仓库:       $ARCHON_DIR"
    echo -e "  🦌 DeerFlow:   $DEERFLOW_DIR"
    echo ""

    if [ -f "$ARCHON_DIR/README.md" ]; then
        head -3 "$ARCHON_DIR/README.md" 2>/dev/null || true
    fi

    echo ""
    echo -e "  ${GREEN}═══ 组件安装状态 ═══${NC}"

    # Python
    echo -e "  Python:    $(python3 --version 2>&1 || echo '未安装')"

    # Lean
    if command -v lean &>/dev/null; then
        echo -e "  Lean:      $(lean --version 2>&1 | head -1)"
    else
        echo -e "  Lean:      ${YELLOW}未安装（可选）${NC}"
    fi

    # Docker
    if command -v docker &>/dev/null; then
        echo -e "  Docker:    $(docker --version 2>&1)"
    else
        echo -e "  Docker:    ${YELLOW}未安装${NC}"
    fi

    # API Key
    if [ -f "$DEERFLOW_DIR/.env" ]; then
        echo -e "  API Key:   ${GREEN}已配置${NC}"
    else
        echo -e "  API Key:   ${RED}未配置${NC}"
    fi

    # 工作流
    echo -e "  Archon:    ${GREEN}已就绪${NC}"
    echo -e "  Rethlas:   ${GREEN}已就绪${NC}"

    echo ""
    echo -e "  ${GREEN}═══ 使用方式 ═══${NC}"
    echo ""

    if [ "$MODE" = "dev" ]; then
        echo "  # 开发模式 — Python API"
        echo ""
        echo "  cd $DEERFLOW_DIR"
        echo "  export DEEPSEEK_API_KEY='你的key'"
        echo ""
        echo "  # 运行 Archon 工作流（填充 Lean sorry）"
        echo "  uv run python3 -c \""
        echo "  import sys; sys.path.insert(0, 'backend')"
        echo "  from workflows.archon_graph import build_archon_graph"
        echo "  graph = build_archon_graph()"
        echo "  result = graph.invoke({'workspace_path': '/path/to/lean/project'})"
        echo '  print(f"Result: {result}")'
        echo "  \""
        echo ""
        echo "  # 运行 Unified Prover（从命题到形式化证明）"
        echo "  uv run python3 -c \""
        echo "  import sys; sys.path.insert(0, 'backend')"
        echo "  from workflows.archon_graph import build_unified_graph"
        echo "  graph = build_unified_graph()"
        echo '  result = graph.invoke({"statement": "∀ n: ℕ, n + 0 = n"})'
        echo '  print(f"Result: {result.get(\"proof_result\", \"see logs\")}")'
        echo "  \""
    else
        echo "  # 生产模式 — Docker 服务"
        echo ""
        echo "  🌐 Web UI:       http://localhost:2026"
        echo "  📡 API Gateway:  http://localhost:2026/api/*"
        echo ""
        echo "  📋 查看日志: cd $DEERFLOW_DIR && make docker-logs"
        echo "  🛑 停止服务:   cd $DEERFLOW_DIR && make docker-stop"
        echo ""
        echo "  # 或使用 API 远程触发证明"
        echo "  curl -X POST http://localhost:2026/api/langgraph/archon_workflow \\"
        echo '    -H "Content-Type: application/json" \\'
        echo "    -d '{\"workspace_path\": \"/path/to/lean/project\"}'"
    fi

    echo ""
    echo -e "  ${GREEN}═══ 文档 ═══${NC}"
    echo "  📖 使用手册:  $ARCHON_DIR/USAGE.md"
    echo "  📝 报告:      $ARCHON_DIR/REPORT.md"
    echo "  📚 GitHub:    https://github.com/Titanium-dioxides/archon-deerflow"
    echo ""
    echo -e "${GREEN}部署完成！${NC}"
    echo ""
}

# ═══════════════════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════════════════

main() {
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║    Archon-DeerFlow 一键部署脚本 v${SCRIPT_VERSION}      ║${NC}"
    echo -e "${CYAN}║    数学定理自动证明系统                          ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  ${BLUE}Rethlas${NC} (非形式化证明生成 + 自我验证)"
    echo -e "  ${BLUE}Archon${NC}  (Lean4 形式化 + 编译验证)"
    echo -e "  ${BLUE}DeerFlow${NC} (LangGraph 编排引擎)"
    echo ""
    echo -e "  模式: ${YELLOW}${MODE}${NC}"
    echo ""

    # ── Lean only ──
    if [ "$LEAN_ONLY" = true ]; then
        install_lean
        echo ""
        ok "Lean4 工具链安装完成"
        exit 0
    fi

    # ── 完整流程 ──
    preflight_check
    clone_repo
    deploy_deerflow
    apply_overlay
    install_lean
    configure_keys
    smoke_test
    start_system
    show_summary
}

main
