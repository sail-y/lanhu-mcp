"""从蓝湖 sketch.json 提取结构化图层树，输出含 fills/borders/shadows/radius/text 的 layers.json。

默认写到 .lanhu 工作区（按 project_id + image_id 定位）；也可传位置参数 sketch/out 走显式路径。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lanhu.tools.layer_extractor import extract_layers
from lanhu.tools.workspace import (
    resolve_workdir,
    sketch_path,
    layers_path,
    manifest_path,
    touch_image,
)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Extract structured layers from sketch.json")
    parser.add_argument("sketch", nargs="?", help="sketch.json path (or use --project-id/--image-id)")
    parser.add_argument("out", nargs="?", help="layers.json output (or standard .lanhu path)")
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--image-id", default=None)
    parser.add_argument("--workdir", default=None)
    args = parser.parse_args()

    workdir = resolve_workdir(args.workdir)

    if args.project_id and args.image_id:
        src = Path(args.sketch) if args.sketch else sketch_path(workdir, args.project_id, args.image_id)
        dst = Path(args.out) if args.out else layers_path(workdir, args.project_id, args.image_id)
    else:
        if not args.sketch or not args.out:
            print("用法: python extract_layers.py <sketch.json> <out.json>  "
                  "[或 --project-id PID --image-id IID --workdir DIR]")
            sys.exit(2)
        src, dst = Path(args.sketch), Path(args.out)

    total = extract_layers(str(src), str(dst))
    print(f"节点总数: {total}")
    print(f"已输出: {dst}")

    if args.project_id and args.image_id:
        touch_image(workdir, args.project_id, args.image_id, layers=True)
        print(f"[INFO] manifest updated: {manifest_path(workdir, args.project_id)}")


if __name__ == "__main__":
    main()
