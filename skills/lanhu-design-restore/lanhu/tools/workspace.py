"""统一的过程文件存放约定：<workdir>/.lanhu/

所有蓝湖取数 / 分析的中间产物都按 (project_id, image_id) 确定性地落在
``<workdir>/.lanhu/projects/<project_id>/images/<image_id>/`` 下，保证同一张
图的 sketch / layers / icons / 分析结果可跨会话复用。

目录布局：
    <workdir>/.lanhu/
      projects/
        <project_id>/
          manifest.json                 # 项目清单：每张图的 fetch/analyze 状态
          images/
            <image_id>/
              raw/
                sketch.json             # fetch_sketch 原始 API 返回
                render.png              # 蓝湖渲染图（用户提供 / 下载）
              layers.json               # extract_layers 提取的结构化图层树
              icons/                    # crop_icons 输出（webp/png）
              analysis/
                layout_intent.json      # layout_intent
                page_summary.json       # summarize_page
                spacing.json            # check_spacing
                verify.json             # verify_layers
      tasks/
        <task_name>/
          images.txt                    # 关联 image_id 列表（可选，按需手工维护）
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ANALYSIS_KINDS = {
    "layout_intent": "layout_intent.json",
    "page_summary": "page_summary.json",
    "spacing": "spacing.json",
    "verify": "verify.json",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def resolve_workdir(explicit: Optional[str] = None) -> Path:
    """解析工作目录：当前工作目录（或 --workdir 显式覆盖）。

    所有取数 / 分析产物落到其下的 ``.lanhu/`` 固定子目录，跨项目隔离、同项目可跨会话复用。
    """
    base = Path(explicit).expanduser() if explicit else Path.cwd()
    base = base.resolve()
    # 护栏：禁止把 .lanhu 写进 skill 自身目录
    skill_root = Path(__file__).resolve().parent.parent.parent
    if skill_root == base or skill_root in base.parents:
        raise SystemExit(
            "[ERROR] 解析到的工作目录落在 skill 自身目录内（%s）。\n"
            "这会把缓存写进 skill 安装路径，无法跨项目复用，且下次 skill 更新会丢失。\n"
            "请确认调用脚本时的当前目录是你正在工作的项目根目录，"
            "或在调用时显式传 --workdir <项目根目录>。" % base
        )
    return base


def lanhu_root(workdir: Path) -> Path:
    return workdir / ".lanhu"


def project_dir(workdir: Path, project_id: str) -> Path:
    return lanhu_root(workdir) / "projects" / project_id


def image_dir(workdir: Path, project_id: str, image_id: str) -> Path:
    return project_dir(workdir, project_id) / "images" / image_id


def raw_dir(workdir: Path, project_id: str, image_id: str) -> Path:
    return image_dir(workdir, project_id, image_id) / "raw"


def icons_dir(workdir: Path, project_id: str, image_id: str) -> Path:
    return image_dir(workdir, project_id, image_id) / "icons"


def analysis_dir(workdir: Path, project_id: str, image_id: str) -> Path:
    return image_dir(workdir, project_id, image_id) / "analysis"


def sketch_path(workdir: Path, project_id: str, image_id: str) -> Path:
    return raw_dir(workdir, project_id, image_id) / "sketch.json"


def render_path(workdir: Path, project_id: str, image_id: str) -> Path:
    return raw_dir(workdir, project_id, image_id) / "render.png"


def layers_path(workdir: Path, project_id: str, image_id: str) -> Path:
    return image_dir(workdir, project_id, image_id) / "layers.json"


def analysis_path(workdir: Path, project_id: str, image_id: str, kind: str) -> Path:
    if kind not in ANALYSIS_KINDS:
        raise KeyError(f"unknown analysis kind: {kind!r} (expected one of {list(ANALYSIS_KINDS)})")
    return analysis_dir(workdir, project_id, image_id) / ANALYSIS_KINDS[kind]


def task_dir(workdir: Path, task_name: str) -> Path:
    return lanhu_root(workdir) / "tasks" / task_name


def manifest_path(workdir: Path, project_id: str) -> Path:
    return project_dir(workdir, project_id) / "manifest.json"


def _new_record() -> dict:
    return {
        "fetched_at": None,
        "sketch_cached": False,
        "layers_extracted": False,
        "render_present": False,
        "icons_cropped": False,
        "analysis": {k: False for k in ANALYSIS_KINDS},
    }


def read_manifest(workdir: Path, project_id: str) -> dict:
    """读取项目 manifest；不存在时返回空骨架。"""
    p = manifest_path(workdir, project_id)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            data.setdefault("images", {})
            return data
        except Exception:
            pass
    return {"project_id": project_id, "updated_at": None, "images": {}}


def write_manifest(workdir: Path, project_id: str, manifest: dict) -> None:
    p = manifest_path(workdir, project_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    manifest["updated_at"] = _now_iso()
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def touch_image(
    workdir: Path,
    project_id: str,
    image_id: str,
    *,
    name: Optional[str] = None,
    fetched: bool = False,
    layers: bool = False,
    render: bool = False,
    icons: bool = False,
    analysis_kind: Optional[str] = None,
) -> dict:
    """更新某张图在 manifest 中的状态并落盘，返回该图记录。

    重复调用同一 (project_id, image_id) 只刷新状态、不覆盖已有结果文件。
    """
    manifest = read_manifest(workdir, project_id)
    rec = manifest["images"].setdefault(image_id, _new_record())
    if name is not None:
        rec["name"] = name
    if fetched:
        rec["sketch_cached"] = True
        if not rec.get("fetched_at"):
            rec["fetched_at"] = _now_iso()
    if layers:
        rec["layers_extracted"] = True
    if render:
        rec["render_present"] = True
    if icons:
        rec["icons_cropped"] = True
    if analysis_kind:
        if analysis_kind not in ANALYSIS_KINDS:
            raise KeyError(f"unknown analysis_kind: {analysis_kind!r}")
        rec.setdefault("analysis", {})
        rec["analysis"][analysis_kind] = True
    write_manifest(workdir, project_id, manifest)
    return rec
