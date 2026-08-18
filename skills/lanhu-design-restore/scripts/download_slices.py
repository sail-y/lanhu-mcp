"""从缓存的 sketch.json 提取设计师标注的切图（slice）并下载到 .lanhu 的 slices/。

切图是蓝湖上设计师显式导出的资源（位图/图标真图，通常 2x）。本脚本读取
``raw/sketch.json``（fetch_sketch 产物），按 slice 提取规则找出所有切图并
下载到 ``.lanhu/projects/<PID>/images/<IID>/slices/``。

提取规则与 lanhu_mcp_server.get_design_slices_info 一致：
- Figma/新版：artboard.layers[]，bitmapLayer + hasExportImage=True，image.imageUrl / svgUrl
- 旧版 Sketch：info[]，ddsImage.imageUrl
- Photoshop：type=ps，assets[]（isSlice/isAsset），对应图层 images.png_xxxhd / svg

无 slice（total_slices: 0）时提示改用 crop_icons.py 从渲染图裁剪占位图。
"""
import argparse
import json
import re
import sys
from pathlib import Path

try:
    import httpx
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Please install httpx: pip install httpx>=0.27.0") from exc

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lanhu.tools.config import load_dotenv, get_cookie, ENV_FILE  # noqa: E402
from lanhu.tools.workspace import (  # noqa: E402
    resolve_workdir,
    sketch_path,
    slices_dir,
    manifest_path,
    touch_image,
)

_INVALID_FS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _sanitize_name(name: str) -> str:
    """将图层名转为安全文件名；空名或纯符号时回退 slice。"""
    clean = _INVALID_FS.sub("_", name).strip().strip(".")
    return clean or "slice"


def _decode_body(content: bytes, fmt: str) -> bytes:
    """还原切图响应体。

    蓝湖 MasterSlice 的 SVG 响应体被整体包成 JSON 字符串（首字节 ``"``、尾字节
    ``"``，内部 ``"`` 转义为 ``\\"``，即 ``"<svg ...>"``）。若直接落盘会得到非法
    XML，任何 SVG 查看器都打不开。此处检测并解包，正常 SVG（以 ``<`` 开头）则原样返回。
    PNG 等二进制不受影响。
    """
    if fmt != "svg":
        return content
    text = content.decode("utf-8", errors="replace").strip()
    if text.startswith('"') and text.endswith('"'):
        try:
            unwrapped = json.loads(text)
        except Exception:
            return content
        if isinstance(unwrapped, str):
            return unwrapped.encode("utf-8")
    return content


def _find_slices(sketch: dict) -> list[dict]:
    """递归提取切图列表（元数据 + 下载地址），兼容新旧结构与 Photoshop。"""
    meta = sketch.get("meta") or {}
    is_figma = (meta.get("host") or {}).get("name") == "figma"
    is_ps = str(sketch.get("type") or "").lower() == "ps"
    slices: list[dict] = []

    def walk(obj, parent_name="", layer_path=""):
        if not isinstance(obj, dict):
            return
        name = obj.get("name", "")
        path = f"{layer_path}/{name}" if layer_path else name

        # Figma/新版：bitmapLayer + hasExportImage=True 才是真切图
        image = obj.get("image")
        if image and isinstance(image, dict) and (image.get("imageUrl") or image.get("svgUrl")):
            if is_figma and not obj.get("hasExportImage"):
                pass  # 图片填充层，不是切图
            else:
                url = image.get("imageUrl") or image.get("svgUrl")
                fmt = "png" if image.get("imageUrl") else "svg"
                frame = obj.get("frame") or obj.get("bounds") or {}
                slices.append({
                    "id": obj.get("id"),
                    "name": _sanitize_name(name),
                    "download_url": url,
                    "format": fmt,
                    "position": {"x": int(frame.get("x") or frame.get("left", 0)),
                                 "y": int(frame.get("y") or frame.get("top", 0))},
                    "layer_path": path,
                })
        # 旧版 Sketch：ddsImage.imageUrl（Figma 的 ddsImage 是填充层，跳过）
        elif obj.get("ddsImage") and isinstance(obj["ddsImage"], dict) \
                and obj["ddsImage"].get("imageUrl") and not is_figma:
            slices.append({
                "id": obj.get("id"),
                "name": _sanitize_name(name),
                "download_url": obj["ddsImage"]["imageUrl"],
                "format": "png",
                "position": {"x": int(obj.get("left", 0)), "y": int(obj.get("top", 0))},
                "layer_path": path,
            })

        for key in ("layers", "children"):
            for child in obj.get(key) or []:
                walk(child, name, path)

    if sketch.get("artboard") and sketch["artboard"].get("layers"):
        for layer in sketch["artboard"]["layers"]:
            walk(layer)
    elif sketch.get("info"):
        for item in sketch["info"]:
            walk(item)

    # Photoshop：导出资源登记在 assets[]，地址在对应 id 图层的 images.png_xxxhd/svg
    if is_ps:
        by_id = {}

        def index_ps(obj):
            if not isinstance(obj, dict):
                return
            if obj.get("id") is not None:
                by_id[obj["id"]] = obj
            for key in ("layers", "children"):
                for c in obj.get(key) or []:
                    index_ps(c)

        board = sketch.get("board")
        if isinstance(board, dict):
            index_ps(board)
        for sec in sketch.get("info") or []:
            if isinstance(sec, dict):
                index_ps(sec)

        existing = {s.get("id") for s in slices}
        for asset in sketch.get("assets") or []:
            if not isinstance(asset, dict):
                continue
            lid = asset.get("id")
            if lid is None or lid in existing:
                continue
            layer = by_id.get(lid)
            if not isinstance(layer, dict):
                continue
            if not (asset.get("isSlice") or asset.get("isAsset")
                    or layer.get("isSlice") or layer.get("isAsset")):
                continue
            imgs = layer.get("images") or {}
            url = imgs.get("png_xxxhd") or imgs.get("svg")
            if not url:
                continue
            slices.append({
                "id": lid,
                "name": _sanitize_name(asset.get("name") or layer.get("name") or "slice"),
                "download_url": url,
                "format": "png" if imgs.get("png_xxxhd") else "svg",
                "layer_path": f"/{layer.get('name', '')}",
            })

    return slices


def download_slices(sketch: dict, out_dir: Path, cookie: str | None = None) -> dict:
    """下载 sketch 中所有切图到 out_dir，返回统计与失败列表。

    返回: {status, total, downloaded, failed: [{name, url, error}]}
    """
    items = _find_slices(sketch)
    if not items:
        return {"status": "no_slices", "total": 0, "downloaded": 0, "failed": []}

    headers = {"User-Agent": "Mozilla/5.0"}
    if cookie:
        headers["Cookie"] = cookie

    out_dir.mkdir(parents=True, exist_ok=True)
    seen: dict[str, int] = {}
    downloaded, failed = 0, []

    with httpx.Client(headers=headers, follow_redirects=True, timeout=60.0) as client:
        for item in items:
            base = seen.get(item["name"], 0) + 1
            seen[item["name"]] = base
            fname = item["name"] if base == 1 else f"{item['name']}_{base}"
            target = out_dir / f"{fname}.{item['format']}"
            if target.exists():
                downloaded += 1
                continue
            try:
                resp = client.get(item["download_url"])
                resp.raise_for_status()
                target.write_bytes(_decode_body(resp.content, item["format"]))
                downloaded += 1
            except Exception as exc:  # noqa: BLE001
                failed.append({"name": item["name"], "url": item["download_url"], "error": str(exc)})

    status = "success" if not failed else "partial"
    return {"status": status, "total": len(items), "downloaded": downloaded, "failed": failed}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download designer-marked slices from cached sketch.json into .lanhu slices/"
    )
    parser.add_argument("--project-id", required=True, help="Lanhu project_id")
    parser.add_argument("--image-id", required=True, help="Design image_id")
    parser.add_argument("--workdir", default=None, help="Working directory holding .lanhu (default: cwd)")
    parser.add_argument("--no-dotenv", action="store_true", help="Do not read the skill-local .env file")
    args = parser.parse_args()

    if not args.no_dotenv and load_dotenv():
        print(f"[INFO] Loaded config from {ENV_FILE}")

    workdir = resolve_workdir(args.workdir)
    sketch_p = sketch_path(workdir, args.project_id, args.image_id)
    if not sketch_p.exists():
        raise SystemExit(
            f"[FAIL] sketch.json not found: {sketch_p}\n"
            f"       请先运行 scripts/fetch_sketch.py <project_id> <image_id>。"
        )

    sketch = json.loads(sketch_p.read_text(encoding="utf-8"))
    items = _find_slices(sketch)
    if not items:
        print(json.dumps({"status": "no_slices",
                          "msg": "sketch 中无设计师标注的 slice（total_slices=0），"
                                 "改用 crop_icons.py 从渲染图裁剪占位图"},
                         ensure_ascii=False, indent=2))
        sys.exit(0)

    out_dir = slices_dir(workdir, args.project_id, args.image_id)
    result = download_slices(sketch, out_dir, cookie=get_cookie())

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["downloaded"]:
        touch_image(workdir, args.project_id, args.image_id, slices=True)
        print(f"[INFO] slices saved: {out_dir}")
        print(f"[INFO] manifest updated: {manifest_path(workdir, args.project_id)}")
    if result["failed"]:
        print(f"[WARN] {len(result['failed'])} 个切图下载失败，见上方 failed 列表")
    sys.exit(0 if result["status"] == "success" else 1)


if __name__ == "__main__":
    main()
