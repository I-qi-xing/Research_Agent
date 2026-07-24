"""
Research Agent Orchestrator - Multi-Agent Workflow Scheduler

Manages the 4-stage research analysis pipeline:
  Stage 1 - PDF Text Extraction (Python)
  Stage 2 - Single-Paper Analysis (opencode subagent, one per paper)
  Stage 3 - Literature Synthesis   (opencode subagent)
  Stage 4 - Research Breakthroughs  (opencode subagent)

Hash-based Cache Invalidation:
  - Tracks SHA256 of each PDF in .orchestrator_state.json
  - If a PDF is modified → its artifacts are auto-deleted, downstream stages invalidated
  - If a PDF is removed → its artifacts are cleaned up as orphans
  - If a new PDF is added → only that paper goes through extraction/analysis

Usage:
  python scripts/orchestrator.py --status      # Show current state
  python scripts/orchestrator.py --run         # Auto-advance to next stage
  python scripts/orchestrator.py --clean       # Delete all generated files and reset state
  python scripts/orchestrator.py --stage1      # Force run stage 1
"""

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

if sys.stdout.encoding is None or sys.stdout.encoding.upper() not in ('UTF-8', 'UTF8'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding is None or sys.stderr.encoding.upper() not in ('UTF-8', 'UTF8'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PAPERS_DIR = PROJECT_ROOT / "papers"
ANALYSIS_DIR = PROJECT_ROOT / "analysis"
REVIEW_DIR = PROJECT_ROOT / "review"
OUTPUT_DIR = PROJECT_ROOT / "output"
AGENTS_DIR = PROJECT_ROOT / "agents"
STATE_FILE = PROJECT_ROOT / ".orchestrator_state.json"

STAGE_NAMES = {
    1: "PDF文本提取",
    2: "单篇文献分析",
    3: "综述生成",
    4: "研究突破点发现",
}

BUF_SIZE = 64 * 1024


def _sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(BUF_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _count_by_suffix(directory: Path, suffix: str) -> int:
    if not directory.is_dir():
        return 0
    return len([f for f in os.listdir(directory) if f.endswith(suffix)])


def _read_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"papers": {}, "synthesis_valid": False, "discovery_valid": False}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _clean_generated_files() -> None:
    for d in [ANALYSIS_DIR, REVIEW_DIR, OUTPUT_DIR]:
        if d.is_dir():
            shutil.rmtree(d)
            d.mkdir(parents=True, exist_ok=True)
            print(f"  [清理] 已清空 {d.name}/")
    if STATE_FILE.exists():
        STATE_FILE.unlink()
        print(f"  [清理] 已删除状态文件")


def _sync_state_with_papers(state: dict) -> bool:
    """
    Sync state with actual papers/ directory. Returns True if any paper
    state changed (new, removed, or modified).
    """
    changed = False

    actual_pdfs = set()
    if PAPERS_DIR.is_dir():
        for f in os.listdir(PAPERS_DIR):
            if f.lower().endswith(".pdf"):
                actual_pdfs.add(f)

    orphan_papers = [name for name in state["papers"] if name not in actual_pdfs]
    for name in orphan_papers:
        changed = True
        print(f"  [清理] 移除孤儿论文: {name}")
        base = Path(name).stem
        for suffix in ["_raw.txt", "_analysis.md"]:
            p = ANALYSIS_DIR / f"{base}{suffix}"
            if p.exists():
                p.unlink()
                print(f"    -> 已删除 {p.name}")
        del state["papers"][name]

    for pdf_name in actual_pdfs:
        pdf_path = PAPERS_DIR / pdf_name
        current_hash = _sha256(pdf_path)

        if pdf_name not in state["papers"]:
            changed = True
            state["papers"][pdf_name] = {
                "sha256": current_hash,
                "extracted": False,
                "analyzed": False,
            }
            print(f"  [新增] 发现新论文: {pdf_name}")
        else:
            existing = state["papers"][pdf_name]
            stored_hash = existing.get("sha256")
            if stored_hash is None or stored_hash != current_hash:
                changed = True
                print(f"  [变更] 论文已修改: {pdf_name}")
                existing["sha256"] = current_hash
                existing["extracted"] = False
                existing["analyzed"] = False
                base = Path(pdf_name).stem
                for suffix in ["_raw.txt", "_analysis.md"]:
                    p = ANALYSIS_DIR / f"{base}{suffix}"
                    if p.exists():
                        p.unlink()
                        print(f"    -> 已删除过期的 {p.name}")

    if changed:
        state["synthesis_valid"] = False
        state["discovery_valid"] = False

    return changed


def detect_stage() -> dict:
    for d in [ANALYSIS_DIR, REVIEW_DIR, OUTPUT_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    state = _read_state()
    _sync_state_with_papers(state)
    _save_state(state)

    pdf_count = _count_by_suffix(PAPERS_DIR, ".pdf")

    if pdf_count == 0:
        return {"stage": 0, "label": "NO_PAPERS", "detail": "papers/ 目录为空", "progress": 0}

    unextracted = sum(1 for p in state["papers"].values() if not p.get("extracted"))
    unanalyzed = sum(1 for p in state["papers"].values() if not p.get("analyzed"))

    if unextracted > 0:
        return {"stage": 1, "label": "NEED_EXTRACT", "detail": f"待提取 {unextracted}/{pdf_count} 篇", "progress": 20}
    if unanalyzed > 0:
        return {"stage": 2, "label": "NEED_ANALYSIS", "detail": f"待分析 {unanalyzed}/{pdf_count} 篇", "progress": 40}
    if not state.get("synthesis_valid"):
        return {"stage": 3, "label": "NEED_SYNTHESIS", "detail": "综述报告需重新生成", "progress": 60}
    if not state.get("discovery_valid"):
        return {"stage": 4, "label": "NEED_DISCOVERY", "detail": "突破点报告需重新生成", "progress": 80}
    return {"stage": 5, "label": "COMPLETE", "detail": "全部完成", "progress": 100}


def print_status(info: dict) -> None:
    bar_len = 30
    filled = int(bar_len * info["progress"] / 100)
    bar = "█" * filled + "░" * (bar_len - filled)

    state = _read_state()
    pdf_count = _count_by_suffix(PAPERS_DIR, ".pdf")
    raw_count = _count_by_suffix(ANALYSIS_DIR, "_raw.txt")
    md_count = _count_by_suffix(ANALYSIS_DIR, "_analysis.md")
    syn_exists = (REVIEW_DIR / "synthesis_report.md").exists()
    opp_exists = (OUTPUT_DIR / "research_opportunities.md").exists()

    print()
    print("=" * 60)
    print("       Research Agent - Multi-Agent Workflow Status")
    print("=" * 60)
    print(f"  Progress: [{bar}] {info['progress']}%")
    print(f"  Phase:    {STAGE_NAMES.get(info['stage'], '完成')}")
    print(f"  Status:   {info['detail']}")
    print("-" * 60)
    print(f"  papers/   : {pdf_count} PDF(s)")
    print(f"  analysis/ : {raw_count} raw | {md_count} analysis")
    print(f"  review/   : {'OK' if syn_exists else '--'}")
    print(f"  output/   : {'OK' if opp_exists else '--'}")
    synth_ok = state.get("synthesis_valid", False)
    disc_ok = state.get("discovery_valid", False)
    print(f"  cache     : synthesis={'ok' if synth_ok else 'stale'}, "
          f"discovery={'ok' if disc_ok else 'stale'}")
    print("=" * 60)
    print()


def run_stage1() -> bool:
    print("[Orchestrator] Stage 1: PDF文本提取")
    state = _read_state()

    unextracted = [name for name, p in state["papers"].items() if not p.get("extracted")]
    if not unextracted:
        print("  所有PDF已提取，跳过")
        return True

    print(f"  待提取 {len(unextracted)} 篇: {', '.join(unextracted)}")

    script = PROJECT_ROOT / "scripts" / "batch_extract.py"
    if not script.exists():
        print(f"  [ERROR] {script} not found")
        return False

    result = subprocess.run([sys.executable, str(script)], cwd=str(PROJECT_ROOT))
    ok = result.returncode == 0
    if ok:
        for name in unextracted:
            state["papers"][name]["extracted"] = True
        report_path = ANALYSIS_DIR / "extraction_report.json"
        if report_path.exists():
            with open(report_path, "r", encoding="utf-8") as f:
                report = json.load(f)
            for pdf_name, result_info in report.items():
                if pdf_name in state["papers"]:
                    state["papers"][pdf_name]["extracted"] = result_info.get("status") == "ok"
        _save_state(state)
        print(f"  [OK] 提取完成 ({len(unextracted)} 篇)")
    else:
        print(f"  [FAIL] 提取失败")
    return ok


def collect_unanalyzed_papers() -> list[tuple[str, str]]:
    state = _read_state()
    tasks = []
    for name, paper_info in state["papers"].items():
        if paper_info.get("analyzed"):
            continue
        base = Path(name).stem
        raw_path = ANALYSIS_DIR / f"{base}_raw.txt"
        if raw_path.exists():
            tasks.append((base, str(raw_path)))
    return sorted(tasks)


def run_stage2_batch(batch_size: int = 3) -> bool:
    state = _read_state()
    unanalyzed = collect_unanalyzed_papers()
    if not unanalyzed:
        print("[Orchestrator] Stage 2: 所有文献已分析，跳过")
        return True

    print(f"[Orchestrator] Stage 2: 待分析 {len(unanalyzed)} 篇文献")

    all_ok = True
    for i in range(0, len(unanalyzed), batch_size):
        batch = unanalyzed[i:i + batch_size]
        print(f"\n  --- 批次 {i // batch_size + 1}: {len(batch)} 篇 ---")
        for name, raw_path in batch:
            ok = invoke_subagent("analyze", {
                "raw_file": raw_path,
                "output_name": name,
            }, f"分析文献: {name}")
            if ok:
                for pdf_name in state["papers"]:
                    if Path(pdf_name).stem == name:
                        state["papers"][pdf_name]["analyzed"] = True
                        break
                print(f"    [OK] {name}")
            else:
                print(f"    [FAIL] {name}")
                all_ok = False

    _save_state(state)
    return all_ok


def run_stage3() -> bool:
    print("[Orchestrator] Stage 3: 综述生成")
    state = _read_state()
    ok = invoke_subagent("synthesize", {}, "生成文献综述报告")
    if ok:
        state["synthesis_valid"] = True
        _save_state(state)
    return ok


def run_stage4() -> bool:
    print("[Orchestrator] Stage 4: 研究突破点发现")
    state = _read_state()
    ok = invoke_subagent("discover", {}, "生成研究突破点报告")
    if ok:
        state["discovery_valid"] = True
        _save_state(state)
    return ok


def invoke_subagent(agent_name: str, params: dict, description: str) -> bool:
    agent_prompt_file = AGENTS_DIR / f"{agent_name}.md"
    if not agent_prompt_file.exists():
        print(f"  [ERROR] Agent prompt not found: {agent_prompt_file}")
        return False

    with open(agent_prompt_file, "r", encoding="utf-8") as f:
        prompt_content = f.read()

    for k, v in params.items():
        prompt_content = prompt_content.replace(f"{{{{{k}}}}}", str(v))

    task_file = PROJECT_ROOT / ".opencode" / f"task_{agent_name}.md"
    task_file.parent.mkdir(parents=True, exist_ok=True)
    with open(task_file, "w", encoding="utf-8") as f:
        f.write(prompt_content)

    cmd = find_opencode()
    if cmd:
        print(f"  [Launch] opencode --agent {agent_name}")
        try:
            result = subprocess.run(
                [cmd, "--agent", agent_name, "-p", f"Execute the task defined in {task_file}"],
                cwd=str(PROJECT_ROOT),
                timeout=600
            )
            return result.returncode == 0
        except FileNotFoundError:
            print(f"  [WARN] opencode CLI not found, falling back to manual mode")
        except subprocess.TimeoutExpired:
            print(f"  [WARN] opencode timed out")
        except Exception as e:
            print(f"  [WARN] Failed to launch opencode: {e}")

    print(f"\n  === Manual Step: {description} ===")
    print(f"  1. Run: opencode --agent {agent_name}")
    print(f"  2. Or in opencode TUI, type: @{agent_name}")
    print(f"  3. The task prompt is saved at: {task_file}")
    print()
    return False


def find_opencode() -> Optional[str]:
    for cmd in ["opencode", "opencode.exe", "npx opencode"]:
        try:
            result = subprocess.run([cmd.split()[0], "--version"],
                                    capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return cmd
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def auto_advance() -> None:
    info = detect_stage()
    print_status(info)

    if info["stage"] == 0:
        print("[Orchestrator] 请将 PDF 文献放入 papers/ 目录后重试")
        return
    if info["stage"] == 5:
        print("[Orchestrator] 所有阶段已完成！")
        return

    proceed = input(f"\n  当前阶段: {STAGE_NAMES[info['stage']]}\n  是否自动推进? (Y/n): ").strip().lower()
    if proceed == "n":
        print("  已取消")
        return

    success = False
    if info["stage"] == 1:
        success = run_stage1()
    elif info["stage"] == 2:
        success = run_stage2_batch()
    elif info["stage"] == 3:
        success = run_stage3()
    elif info["stage"] == 4:
        success = run_stage4()

    if success:
        print("\n[Orchestrator] 阶段执行成功！")
    else:
        print("\n[Orchestrator] 阶段执行未完全成功，请检查上述输出")

    print_status(detect_stage())


def setup_opencode_agents() -> None:
    print()
    print("=" * 55)
    print("   OpenCode 多智能体设置指引")
    print("=" * 55)
    print()
    print("  本项目共定义 4 个 subagent，配置见 opencode.json:")
    print()
    print(f"    @orchestrator  - 主控智能体（默认）")
    print(f"    @analyze       - 单篇文献分析（可并行）")
    print(f"    @synthesize    - 综述报告生成")
    print(f"    @discover      - 研究突破点挖掘")
    print()
    print("  使用方式:")
    print("    1. 在 opencode TUI 中键入 @agent-name 调用")
    print("    2. 在 AGENTS.md 中通过 task 工具自动调度")
    print()
    print("  缓存机制:")
    print("    系统使用 SHA256 哈希跟踪每篇 PDF 的变更")
    print("    修改/新增/删除 PDF 后，相关缓存自动失效")
    print()
    print("  快速开始:")
    print("    python scripts/orchestrator.py --run")
    print("    python scripts/orchestrator.py --clean  # 重置所有产物")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Research Agent Orchestrator - Multi-Agent Workflow Scheduler"
    )
    parser.add_argument("--status", action="store_true", help="Show current workflow status")
    parser.add_argument("--run", action="store_true", help="Auto-advance to next stage")
    parser.add_argument("--clean", action="store_true", help="Delete all generated files and reset state")
    parser.add_argument("--stage1", action="store_true", help="Run PDF extraction")
    parser.add_argument("--stage2", action="store_true", help="Run paper analysis")
    parser.add_argument("--stage3", action="store_true", help="Run synthesis")
    parser.add_argument("--stage4", action="store_true", help="Run breakthrough discovery")
    parser.add_argument("--setup", action="store_true", help="Show subagent setup guide")

    args = parser.parse_args()

    if args.setup:
        setup_opencode_agents()
        return

    if args.clean:
        proceed = input("确定要删除所有生成文件并重置状态? (y/N): ").strip().lower()
        if proceed == "y":
            _clean_generated_files()
            print("[Orchestrator] 已清理完毕，可以重新开始")
        else:
            print("已取消")
        return

    if args.status:
        print_status(detect_stage())
        return

    if args.stage1:
        run_stage1()
        print_status(detect_stage())
        return

    if args.stage2:
        run_stage2_batch()
        print_status(detect_stage())
        return

    if args.stage3:
        run_stage3()
        print_status(detect_stage())
        return

    if args.stage4:
        run_stage4()
        print_status(detect_stage())
        return

    if args.run:
        auto_advance()
        return

    info = detect_stage()
    print_status(info)
    if info["stage"] == 0:
        print("  提示: 将 PDF 放入 papers/ 目录")
    elif info["stage"] < 5:
        print(f"  建议: 运行 python scripts/orchestrator.py --run 进入下一阶段")
    else:
        print("  所有阶段已完成！查看 review/ 和 output/ 目录获取结果")


if __name__ == "__main__":
    main()
