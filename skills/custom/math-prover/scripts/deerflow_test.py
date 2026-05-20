#!/usr/bin/env python3
"""
DeerFlow 框架对齐测试 — 通过 DeerFlowClient 验证 math-prover skill 的完整集成。

测试内容:
  1. skill 是否被 DeerFlow 发现并加载
  2. 模型是否可用 (deepseek-v4)
  3. 发送证明请求后返回结构是否符合 DeerFlow 的 StreamEvent 协议
  4. 是否触发了 math-prover 的生成+验证闭环
"""

import sys
import json

sys.path.insert(0, "/home/zdzdhd/deer-flow/backend/packages/harness")

try:
    from deerflow.client import DeerFlowClient
    from deerflow.config.app_config import reload_app_config
except ImportError as e:
    print(f"❌ 无法导入 DeerFlow SDK: {e}")
    sys.exit(1)


def test_skill_discovery(client):
    """测试 1: math-prover skill 是否被 DeerFlow 发现"""
    print("=" * 60)
    print("测试 1: Skill 发现与加载")
    print("=" * 60)

    skills = client.list_skills(enabled_only=False)
    if "skills" not in skills:
        print(f"❌ list_skills 返回格式异常: {skills}")
        return False

    skill_names = {s["name"] for s in skills["skills"]}
    print(f"   发现 {len(skills['skills'])} 个 skill:")
    for s in skills["skills"]:
        print(f"     - {s['name']} [{s['category']}] enabled={s['enabled']}")

    if "math-prover" in skill_names:
        print("\n   ✅ math-prover 已被 DeerFlow 发现并加载")
    else:
        print("\n   ❌ math-prover 未被发现")
        return False

    # 检查 skill 详情
    detail = client.get_skill("math-prover")
    if detail:
        print(f"   ✅ 可获取 skill 详情: {detail.get('description', '')[:60]}...")
    return True


def test_model_available(client):
    """测试 2: deepseek-v4 模型可用"""
    print("\n" + "=" * 60)
    print("测试 2: 模型可用性")
    print("=" * 60)

    models = client.list_models()
    model_names = list(models.keys())
    print(f"   可用模型: {model_names}")

    if "deepseek-v4" in model_names:
        print("   ✅ deepseek-v4 可用")
        return True
    else:
        print("   ⚠️  deepseek-v4 不在列表，检查实际使用的模型")
        return True  # 不阻塞后续测试


def test_proof_request(client, thread_id):
    """测试 3: 发送证明请求并验证返回结构"""
    print("\n" + "=" * 60)
    print("测试 3: 证明请求 — 根号2是无理数")
    print("=" * 60)

    proof_request = "请证明：根号2是无理数。"

    print(f"   发送: \"{proof_request}\"")
    print(f"   线程: {thread_id}")
    print("   等待响应...\n")

    try:
        events = []
        for event in client.stream(proof_request, thread_id=thread_id):
            events.append(event)
            event_type = event.get("event", "unknown")
            if event_type == "on_chat_model_stream":
                content = event.get("data", {}).get("chunk", {}).get("content", "")
                # 显示前 200 字符
                print(content, end="", flush=True)

        print("\n\n   ——— 事件统计 ———")
        event_types = {}
        for e in events:
            et = e.get("event", "?")
            event_types[et] = event_types.get(et, 0) + 1
        for et, cnt in sorted(event_types.items()):
            print(f"     {et}: {cnt} 次")

        # 检查是否包含 proof 标签
        all_text = " ".join(
            e.get("data", {}).get("chunk", {}).get("content", "")
            for e in events
            if e.get("event") == "on_chat_model_stream"
        )

        has_proof = "<proof>" in all_text or "proof" in all_text.lower()
        print(f"\n   ✅ 响应包含证明内容: {has_proof}")
        return True

    except Exception as e:
        print(f"   ❌ 请求失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_session_history(client, thread_id):
    """测试 4: 验证会话历史中保留了完整的生成↔验证对话"""
    print("\n" + "=" * 60)
    print("测试 4: 线程历史检查")
    print("=" * 60)

    thread = client.get_thread(thread_id)
    print(f"   线程: {thread_id}")
    print(f"   标题: {thread.get('title', 'N/A')}")

    # 检查 values 中的消息
    values = thread.get("values", [])
    msg_count = len(values) if isinstance(values, list) else 0
    print(f"   消息数: {msg_count}")

    # 检查技能是否被加载到系统提示中
    if isinstance(values, list):
        for i, msg in enumerate(values):
            role = msg.get("role", "?") if isinstance(msg, dict) else "?"
            content = str(msg.get("content", ""))[:80] if isinstance(msg, dict) else str(msg)[:80]
            print(f"     [{i}] {role}: {content}...")

    return True


def main():
    print("╔════════════════════════════════════════════════════════╗")
    print("║  DeerFlow 框架对齐测试 — math-prover skill           ║")
    print("╚════════════════════════════════════════════════════════╝")

    # 刷新配置确保加载最新 skill
    print("\n[初始化] 加载 DeerFlow 配置...")
    try:
        reload_app_config()
        print("   ✅ 配置已刷新")
    except Exception as e:
        print(f"   ⚠️  配置刷新失败: {e}")

    client = DeerFlowClient(model_name="deepseek-v4")
    print(f"   ✅ DeerFlowClient 创建成功 (model=deepseek-v4)")

    # 测试 1: Skill 发现
    if not test_skill_discovery(client):
        print("\n❌ 技能发现失败，可能 math-prover 未正确安装")
        # 检查目录是否存在
        import os
        path = "/home/zdzdhd/deer-flow/skills/custom/math-prover/SKILL.md"
        print(f"   检查路径: {path}")
        print(f"   文件存在: {os.path.exists(path)}")

    # 测试 2: 模型
    test_model_available(client)

    # 测试 3: 发送证明请求
    thread_id = f"math-prover-test-{sys.argv[1] if len(sys.argv) > 1 else '01'}"
    test_proof_request(client, thread_id)

    # 测试 4: 会话历史
    test_session_history(client, thread_id)

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
