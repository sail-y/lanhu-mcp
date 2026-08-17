"""校验 layers.json 提取质量，输出文本颜色/渐变/边框/阴影/旋转等字段检查结论。

默认按 project_id + image_id 从 .lanhu 读 layers.json，校验结论写到 analysis/verify.json；也可传位置参数 <layers.json> [sketch.json] 仅打印。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lanhu.tools.layer_verifier import verify_layers
from lanhu.tools.workspace import (
    resolve_workdir,
    layers_path,
    analysis_path,
    touch_image,
)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Verify layers.json extraction quality")
    parser.add_argument("layers", nargs="?", help="layers.json path (or use --project-id/--image-id)")
    parser.add_argument("sketch", nargs="?", help="sketch.json path (optional, for cross-check)")
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--image-id", default=None)
    parser.add_argument("--workdir", default=None)
    args = parser.parse_args()

    workdir = resolve_workdir(args.workdir)

    if args.project_id and args.image_id:
        lp = layers_path(workdir, args.project_id, args.image_id)
        sketch_p = args.sketch
        result = verify_layers(str(lp), sketch_p)
        out = analysis_path(workdir, args.project_id, args.image_id, "verify")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        touch_image(workdir, args.project_id, args.image_id, analysis_kind="verify")
        print(f"[OK] analysis saved: {out}")
    else:
        if not args.layers:
            print("用法: python verify_layers.py <layers.json> [sketch.json]  "
                  "[或 --project-id PID --image-id IID --workdir DIR]")
            sys.exit(2)
        result = verify_layers(args.layers, args.sketch)

    print(f'===== 验证: {Path(args.layers).name if args.layers else "image"} =====')
    for c in result["checks"]:
        flag = "PASS" if c["ok"] else "FAIL"
        print(f'  [{flag}] {c["name"]}: {c["detail"]}')
        if c["extra"]:
            print(f"         {c['extra']}")
    if "sketch_mismatches" in result:
        if result["sketch_mismatches"]:
            print("  [FAIL] 与原始 sketch 抽查不一致:")
            for m in result["sketch_mismatches"][:10]:
                print(f"         {m}")
        else:
            print(f'  [PASS] 与原始 sketch 抽查文本一致（{result["total_texts"]} 个）')
    print()
    print("结论:", "全部通过 ✅" if result["all_pass"] else "存在失败项 ❌")
    sys.exit(0 if result["all_pass"] else 1)


if __name__ == "__main__":
    main()
