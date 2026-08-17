---
name: lanhu-design-restore
description: 从蓝湖（Lanhu）设计稿原始图层树（sketch JSON）取数，并按规范流程做像素级前端还原的方法与工具链。当需要按设计稿还原前端页面、核对样式，且数据源为蓝湖设计稿时使用。适用于解决标注降级模式下拍平散件“只有位置、细节全错”的问题。触发词：蓝湖还原、设计稿还原、lanhu 取数、设计稿细节。
agent_created: true
---

> 安装与配置见 [INSTALL.md](INSTALL.md)。本 skill 自包含，不依赖任何特定 AI 助手或客户端配置。

# 蓝湖设计稿像素级还原

## 1. 适用范围

本 skill 提供从蓝湖设计稿取数、校验并产出前端实现的规范化流程：

- **取数**：直接读取蓝湖原始图层树（sketch JSON），获取坐标、间距、颜色、渐变、边框、阴影、圆角、字体等全部结构信息。
- **校验**：对提取结果做字段完整性校验（`verify_layers`），对容器间距做推导与跨页比对（`check_spacing`）。
- **产出**：按目标技术栈（默认 Vue 3 + Element Plus）输出符合工程标准的组件实现。

还原的本质是**数据驱动**：有完整结构化数据时，还原不需要视觉理解。视觉只承担**质检**（确认缝隙、边框可见边等偏差）与**兜底**（仅有位图、无结构化数据时的唯一通道）两个角色，不参与取数与取值。

## 2. 数据源选择

蓝湖存在两种数据形态，必须使用正确的一种：

| 形态 | 数据来源 | 内容 | 结论 |
|------|---------|------|------|
| 标注降级（拍平散件） | `lanhu_get_ai_analyze_design_result` | 每图层一个绝对定位 div + data-css，仅坐标与简单 css | 丢失组件分组、背景形状、渐变 / 精确 border/shadow、字体 letterSpacing，**禁止用于像素级还原** |
| 原始图层树 | `get_sketch_json` | 完整容器层级、fills（含渐变 stops）、borders、shadows、字体（name/size/letterSpacing/align/color） | **唯一权威数据源** |

要点：

- 拍平散件在 D2C 通道失败时由服务端自动降级产生，属正常现象。“位置对、细节全错”是其固有特征，禁止使用其坐标 / 尺寸做还原。
- D2C 通道报 `store_schema_revise 失败: 版本数据不存在` 属正常降级。蓝湖官方 D2C 仅私有部署且依赖 MasterGo，公开套餐不含，无需为还原开通。
- 像素采样是干扰源：可能采到文字、抗锯齿、渐变中点，或被上层覆盖面板的颜色误导（如被面板盖住的底层色可能被采成面板色），禁止用于取色。
- 视觉形状（内容区 / 卡片背景、边框等）在标注模式中已合入整图，必须从 sketch 树的 fills / borders 读取。

## 3. 前置条件

1. **蓝湖 Cookie**：需要有效的 `LANHU_COOKIE`。配置方式二选一：环境变量 `LANHU_COOKIE`（推荐），或 skill 根目录 `.env` 文件（复制 `.env.example` 填写）。
2. **Python 3.10+ 与依赖**：`pip install -r requirements.txt`（httpx、Pillow）。
3. **工作目录**：所有中间产物落在**当前工作目录下的 `.lanhu/` 固定子目录**，不依赖环境变量；跨项目天然隔离，同项目可跨会话复用。需要其他落点时显式传 `--workdir <DIR>`；若解析到 skill 自身安装目录则报错退出（护栏）。

## 4. 目录约定（.lanhu）

所有取数 / 分析产物按 `(project_id, image_id)` 确定性落盘，不散落于工作目录或临时目录。脚本均优先按 `--project-id <PID> --image-id <IID> [--workdir <DIR>]` 定位文件；不传 ID 时退化为「显式路径 + 仅打印」模式（不落盘）。

```
<workdir>/.lanhu/
  projects/
    <project_id>/
      manifest.json                 # 项目清单：每张图的 fetch/analyze 状态（可复用标记）
      images/
        <image_id>/
          raw/
            sketch.json             # fetch_sketch 原始 API 返回
            render.png              # 蓝湖渲染图（用户提供 / --render 拷贝）
          layers.json               # extract_layers 提取的结构化图层树
          icons/                    # crop_icons 输出（webp/png）
          analysis/
            layout_intent.json      # layout_intent
            page_summary.json       # summarize_page
            spacing.json            # check_spacing（单容器）
            verify.json             # verify_layers
  tasks/
    <task_name>/
      images.txt                    # 关联 image_id 列表（可选，按任务归集）
```

复用规则：

- 同一张图的全部产物落在同一 `<image_id>/` 下；重跑仅刷新状态，不覆盖已有结果；`manifest.json` 记录每张图已完成的步骤，可据此跳过重复取数。
- `tasks/<task_name>/images.txt` 用于任务级归集：将若干 `image_id` 列出，即可跨多张图复用各自已缓存的 analysis（如跨页同构容器对比）。
- `.lanhu/` 为纯本地缓存，不进版本库（仓库 `.gitignore` 已忽略），且不被任何 MCP 客户端读取。

## 5. 标准取数流程

0. **结构盘点（必做）**：先打印整棵树的容器层级（name + frame + fill + border + children），从根容器到叶子，建立“大容器→留白→子区域”的骨架认知后再动手。跳过此步而按局部反馈排查，可能把被覆盖层误判为页面底色——数据始终存在，需系统性消费。
1. 取设计图标识：从蓝湖项目 / 设计页 URL 读取 `project_id` 与 `image_id`（链接参数可见）。
2. 拉取原始图层树：
   `scripts/fetch_sketch.py <project_id> <image_id> [--team_id TEAM_ID] [--workdir <DIR>] [--render <render.png>]`
   → 输出 `.lanhu/projects/<PID>/images/<IID>/raw/sketch.json`，写 `manifest.json` 标记 `fetched`；`--render` 将本地渲染图拷入 `raw/render.png`。
3. 结构化提取：
   `scripts/extract_layers.py --project-id <PID> --image-id <IID> [--workdir <DIR>]`
   → 输出 `layers.json`（name/type/frame/style[fills/gradients/borders/shadows/radius]/text[font/letterSpacing]，色值转 rgba()），标记 `layers_extracted`。亦支持显式路径 `extract_layers.py <sketch.json> <out.json>`。
4. **提取后必跑验证器**：
   `scripts/verify_layers.py --project-id <PID> --image-id <IID> [--workdir <DIR>]`
   → 输出 `analysis/verify.json`，标记 `analysis.verify`。检查项：①文本 color 缺失数为 0；②渐变含 gradientType/from/to；③border 含 lineAlignment；④shadow 含 inset；⑤rotationDeg≠0 的节点列表（需人工确认）；⑥传入 sketch.json 时抽查文本 color/fontWeight 与原始一致。**全部 PASS 方为提取合格**。
5. 还原取值规则见 §6，间距推导见 §7。
6. PNG 像素扫描仅用于验证（边框可见边、缝隙、被覆盖层的真实渲染），不用于取色。
7. 蓝湖网页标注 CSS 与 sketch 数据同源，可作为快速核对基准。

## 6. 字段取值规则

- **圆角**：位于 `paths[].radius`（topLeft/topRight/bottomLeft/bottomRight），而非节点级 `node.radius`（常为空数组）。蓝湖网页标注的 border-radius 与 `paths.radius` 一致，提取脚本据此输出。
- **阴影**：sketch 原始字段为 `x`/`y`（偏移）、`blur`、`spread`、`inset`（方向标记），非 `offsetX/offsetY/blurRadius`。`inset: true` → `box-shadow: inset ...`。示例：`x0 y4 blur10 spread0 inset:true` → `inset 0 4px 10px rgba(0,0,0,0.05)`。
- **文本颜色**：位于 `text.style.color`，非 `font.color`。任何文本色值必须查 `layers.json` 的 `text.color`，禁止凭视觉或经验猜测。
- **渐变**：fill 含 `from`/`to`（局部坐标，dy=0→水平、dx=0→垂直）与 `type`（0=linear、1=radial）。线性渐变 CSS 角度由 from/to 推导。
- **边框**：含 `lineAlignment`（inside/center/outside）。inside 在 border-box 下视觉一致；center 描边两侧各半，需注意。`paths[].type` 为 `"path"` 时 border 仅沿路径描边（单线），`"rect"` 才是四边边框；可见边须以像素扫描（1px 步长）确认。
- **变换 / 旋转**：旋转节点的 `frame` 是旋转后包围盒（如 9×9 方块旋转 45° 后 bbox 为 13.41×13.41）。`rotationDeg` 由 transform 2×2 线性部分推导（θ=atan2(b,a)）。`rotationDeg≠0` 时必须按 CSS `transform: rotate` 实现，禁止按 bbox 绘制。
- **文本附加属性**：`fontWeight`（数值，较 fontType 精确）、`verticalAlignment`、`underline`、`linethrough`、`lineSpacing` 均需提取。
- **sharedStyle**：设计规范色值命名（如 `填充/Primary2`），与 fills 同源，可作色值来源注释与验证。
- **无需提取的字段**：节点级 `radius`（仅 artboard 自身 0 值）、`style.blurs`、`blendMode`、`text.value`（与 style.content 全等）、`text.styles` 多段（全单段）、`paths.booleanOperation/subpaths`、`realFrame`（差异仅旋转节点，transform 已覆盖）、fill/border/shadow 各自 opacity（全 1）、`visible=false` 节点、`style.isEnabled`、symbolInstance 的 symbolId/overrides。
- **提取脚本修改后的自检清单**：①文本 color 缺失数为 0；②渐变节点含 from/to/gradientType；③border 含 lineAlignment；④阴影含 inset；⑤列出 rotationDeg≠0 节点核对；⑥随机抽取 1 个文本对比原始 sketch 的 style.color/fontWeight。

## 7. 布局与间距规则

1. **间距语义定位**：由区域容器 frame（右缘 = left + width）与各子元素 frame，逐项计算子元素相对父的左右间距后归类：
   - 全部子元素贴某边 → 父容器 `padding`。
   - 仅个别元素不贴边 → 该元素自身 `margin`（禁止用父 padding 一刀切）。
   - 决策表：统一缩进 → 父 padding；兄弟均匀间距 → 父 gap；单个元素独有 → 子 margin；间距区需显示父背景或可点击 → padding；纯页面留白 → margin；垂直间距优先 padding/gap（防 margin 折叠）；组件内部 → 组件 padding；组件之间 → 父 gap 或子 margin。
2. **影响面检查**：修改父级样式（padding/width/border）前，先列出全部子元素并逐项确认改动适用性；“收窄”类改动（padding 置 0、宽度减小）风险最高。
3. **层级归属**：每个视觉元素先确认所属容器及其边界。两层容器（大容器 + 小面板）本质是留白意图，应合并为一个容器 + padding/margin；`path` 为单线描边（边框边数按像素扫描确认）。
4. **逐图核对**：同一页面存在多个 tab / 状态 / 弹窗时，每个状态对应一张独立设计图，必须逐图核对容器样式（fills/borders/shadows/radius/padding 全维度），禁止将一张图的结论推断到另一张图。共用骨架（导航、外壳、左右面板）可复用结论，内容区必须逐图核对。
5. **坐标换算**：设计稿画布坐标换算到响应式布局时，用组件容器 frame 的起点与宽度推导间距，不使用文字图层坐标。`frame.left` 不得直接转成固定左偏移 / `padding-left`：先计算 `(artboard.width - frame.left - frame.width)`；左右空白接近时优先 `max-width + margin: 0 auto` 居中，仅当明显对应真实侧边栏 / 出血区时才用固定偏移。

## 8. 辅助工具（CLI）

以下脚本调用 `lanhu/tools` 下的纯函数，无需任何 MCP 协议或 MCP 客户端配置即可独立运行。

### 8.1 布局意图分析 `layout_intent.py`

- 用途：将 `frame.left` 转为 CSS 前判断版心策略，避免把应居中的内容区实现为固定 `padding-left`。
- CLI：`python layout_intent.py --project-id <PID> --image-id <IID> [容器名] [--workdir <DIR>]`（输出 `analysis/layout_intent.json`）；或显式路径 `python layout_intent.py <layers.json> [容器名]`（仅打印）。
- 输出：`{artboard, container, margins: {left, right, top}, intent, css_recommendation}`。
- 决策规则：
  - 左右空白差 ≤ 24px → `center` → `max-width + margin: 0 auto`
  - 宽度接近满屏 → `full-width` → `width: 100% + padding`
  - 其余 → `fixed-left` → `margin-left + width`

### 8.2 页面规格摘要 `summarize_page.py`

- 用途：生成页面的取值溯源表：卡片、输入框、按钮、开关、图标、字体分组。
- CLI：`python summarize_page.py --project-id <PID> --image-id <IID> [page_name] [--workdir <DIR>]`（输出 `analysis/page_summary.json`）；或显式路径（仅打印）。
- 输出字段：`page / layout / cards / inputs / buttons / switches / icons / text_styles`。
- 用法：先扫 `text_styles` 与 `cards` 建立全局样式锚点，再逐块细化。

### 8.3 图标自动裁剪 `crop_icons.py`

- 用途：设计师未标注 slice 时，按 layers.json 的 frame 从渲染图裁剪图标。`total_slices: 0` 表示未标 slice，应使用本工具产出占位图，禁止用 SVG / emoji 近似。
- CLI：`python crop_icons.py --project-id <PID> --image-id <IID> [--workdir <DIR>] [--fmt webp|png] [--name-map x.json]`（渲染图默认取 `raw/render.png`，输出 `icons/`，标记 `icons_cropped`）；或显式路径 `python crop_icons.py <layers.json> <render.png> <out_dir> [name_map.json] [webp|png]`。
- 渲染图通常为 2x（如 3840×2160），工具按 `png.width / artboard.width` 缩放坐标；默认 `webp`，保存失败自动回退 `png`。

### 8.4 容器间距校验 `check_spacing.py`

- 用途：由 sketch 帧推导容器 padding、子元素 margin 与兄弟间距，并支持跨页同构容器差异比对。
- CLI：
  - 单容器：`python check_spacing.py --project-id <PID> --image-id <IID> [容器名] [--workdir <DIR>]`（输出 `analysis/spacing.json`）
  - 显式路径：`python check_spacing.py <layers.json> [容器名]`（仅打印）
  - 跨页对比：`python check_spacing.py --compare <a.json> <b.json> --name <容器名>`（不落盘）
- 输出：
  - `container.frame`：容器 left/top/width/height
  - `container.padding`：由多数子元素贴边距离推导的父容器 padding
  - `container.deviations`：四边上偏离多数值的子元素（即该子元素自身 margin）
  - `container.horizontal_gaps / vertical_gaps`：相邻子元素间距
  - `summary.flagged`：跨页对比时 frame 尺寸或 padding 不一致的项

### 8.5 推荐流水线

```
fetch_sketch.py   --project-id PID --image-id IID            # → raw/sketch.json (+ raw/render.png)
extract_layers.py --project-id PID --image-id IID            # → layers.json
verify_layers.py  --project-id PID --image-id IID            # → analysis/verify.json
layout_intent.py  --project-id PID --image-id IID            # → analysis/layout_intent.json
summarize_page.py --project-id PID --image-id IID            # → analysis/page_summary.json
crop_icons.py     --project-id PID --image-id IID            # → icons/*.webp
check_spacing.py  --project-id PID --image-id IID '容器名'    # → analysis/spacing.json
check_spacing.py  --compare a.json b.json --name '容器名'    # 跨页对比（显式路径）
    → 依据 layers.json / analysis/* 实现目标技术栈组件（数值一律取自结构化数据，禁止截图估算）
```

每一步的输出均按 `PID/IID` 落在 `.lanhu` 下并在 `manifest.json` 标记完成状态；重跑同一张图直接命中缓存，无需重新请求蓝湖。

## 9. 程序化调用（Python API）

脚本也可作为库调用。示例骨架：

```python
import os
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "scripts"))
from fetch_sketch import fetch_sketch
from lanhu.tools.workspace import resolve_workdir, sketch_path, touch_image

os.environ.setdefault("LANHU_COOKIE", "your_lanhu_cookie_string")

PROJECT_ID, IMAGE_ID = "...", "..."
WORKDIR = resolve_workdir()  # 默认 cwd；也可传显式目录
sketch = fetch_sketch(project_id=PROJECT_ID, image_id=IMAGE_ID)
out = sketch_path(WORKDIR, PROJECT_ID, IMAGE_ID)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(sketch, ensure_ascii=False), encoding="utf-8")
touch_image(WORKDIR, PROJECT_ID, IMAGE_ID, fetched=True)
# 后续步骤：python scripts/extract_layers.py --project-id PID --image-id IID
```

## 10. 还原验收清单

按优先级执行；任何不确定项应回退到数据核对，而非目测判断。

- [ ] **数据源**：所有尺寸 / 样式取值来自 `sketch.json` / `layers.json`，未使用 `lanhu_get_ai_analyze_design_result` 的拍平散件。
- [ ] **结构盘点**：还原前已打印整棵树的容器层级（name + frame + fill + border + children），理解“大容器→留白→子区域”骨架。
- [ ] **多图比对（可选，仅当页面存在多个 tab / 状态 / 弹窗时）**：每个状态对应一张独立设计图，已分别核对样式（border/阴影/字距等），未将一张图的结论推断到另一张图。
- [ ] **间距归属**：每个间距已按决策表归到正确层级——“一致”用父 padding/gap、“个别”用子 margin；垂直间距优先 padding/gap；组件内部用 padding，组件之间用 gap 或子 margin。
- [ ] **硬算 / 测量**：每个区域关键尺寸通过 frame 计算（right = left + width），无子元素越界或留白异常。
- [ ] **容器间距校验（强制，未通过不得进入下一区域 / 下一页）**：本区域关键容器已跑 `check_spacing.py`，padding/margin/gap 来自 sketch 帧；偏差报告无异常。跨页同构容器（如不同页面的同名左面板 / 内容区）已对比 width 与 padding。示例：
  `python check_spacing.py --compare <pageA_layers.json> <pageB_layers.json> --name "<容器名称/ID>"`
  （`pageA_layers.json` 即 `.lanhu/projects/<PID>/images/<IID>/layers.json`）
- [ ] **底色 / 背景**：通过 `style.fills` 读取渐变 stops，未用 PNG 采样取色；被上层覆盖的底层颜色已确认实际可见色。
- [ ] **边框**：`style.borders` 读取 thickness + color，可见线条用 1px 扫描确认，已区分 path 描边与实边框。
- [ ] **圆角**：使用 `paths[].radius`，未按 bbox 画矩形。
- [ ] **字体**：font name/size/weight/letterSpacing/align 已对应；letter-spacing 已按 em 表达（见 §11.5）。
- [ ] **阴影**：`style.shadows` 读取 offset/blur/spread/color，inset 已标注。
- [ ] **切图（可选，仅当存在图标 / 占位图且设计师未提供 slice 时）**：图标已切为占位图，并在代码中标注“设计师未切图，暂用占位图”。
- [ ] **组件适配**：优先使用目标技术栈的 UI 库与项目已有组件（覆盖样式而非重造）；需覆盖样式时用 `:deep()` 或组件提供的样式 hook，不污染全局。
- [ ] **布局**：flex 实现，无绝对定位 div 拼凑；关键元素（按钮、icon）未被压缩或隐藏。
- [ ] **静态校验**：ESLint / vue-tsc 通过，无命名 / 类型警告。

## 11. Vue 3 输出规范（目标技术栈为 Vue 3 + Element Plus 时）

以下规则适用于目标技术栈为 **Vue 3 + Element Plus**、且数据已按 §5 流程从 `get_sketch_json` → `extract_layers.py` 取出的场景。

### 11.1 文件格式

- 默认产出 Vue 3 单文件组件（SFC）：`<template>` + `<script setup lang="ts">` + `<style scoped lang="scss">`。
- 禁止输出 React / RN / Flutter / XML / Compose / Tailwind / Less / CSS-in-JS，除非用户显式要求。

### 11.2 数据读取优先级

| 属性 | 来源字段 | 禁止来源 |
|------|---------|---------|
| 坐标 / 尺寸 | `frame.left/top/width/height` | 绝对定位 div 坐标 |
| 背景 / 渐变 | `style.fills`（含 stops） | PNG 像素采样 |
| 边框 | `style.borders` | 截图目测 |
| 圆角 | `paths[].radius`（topLeft/topRight/bottomLeft/bottomRight） | `node.radius` / 截图 |
| 阴影 | `style.shadows` | 截图估算 |
| 字体 | `text.font/name/size/letterSpacing/align/color` | 截图目测 |
| 间距 | 子层 `frame` 差值（如 child.left - parent.left = padding） | 标注模式的 measurements |

### 11.3 布局与定位

- 主信息流必须用 flex；仅在角标、浮层、重叠装饰、悬浮手势等场景允许 `position: absolute`。
- 页面根节点优先 `min-height: 100vh`；主内容区优先 `max-width` + `margin: 0 auto` 控制版心。
- 禁止整页 `transform: scale(...)`。
- 大屏：居中主栏 + 最大宽度约束；横屏：重排容器，不缩放。
- 滚动容器：只要垂直内容有超出风险，优先正常文档流或局部滚动；禁止把底部按钮写死到视口外。
- 移动 H5 吸底区域必须补 `env(safe-area-inset-bottom)`。

### 11.4 资源与切图

- 所有切图 / 图标统一落盘：`src/assets/lanhu/<screen>/`；命名语义化（如 `ic-close.png`、`bg-card.png`、`btn-save.webp`）。
- 默认格式 `webp`；透明或质量异常可回退 `png`，并在资源清单标注原因。
- icon / 复杂图形优先使用真实切图：设计师在蓝湖标的 slice 取真图；未标时用 `crop_icons.py` 从渲染图自动裁剪占位图。禁止用 CSS/SVG/emoji 手画近似版，除非图形是纯色填充的基础几何形。
- 常规资源使用 `import` 或 `new URL(..., import.meta.url).href`。

### 11.5 文本与样式

- 保留文本层级、强调态、弱化态、删除线、换行与截断策略；长文本必须给出多行截断或换行策略，辅助态不得静默省略。
- 颜色用 sketch 树里的 `text.color` 或 `style.fills` 的 rgba()，禁止 PNG 采样取色。
- 字距读取 `text.letterSpacing` 并写到 CSS `letter-spacing`。Sketch 的 `PERCENT` 单位必须用 em 表达（如 4.5% → `0.045em`、0.9% → `0.009em`），禁止写 CSS 百分比字面量——CSS 百分比 letter-spacing 属 CSS Text Level 4，老环境静默失效；em 相对自身字号，语义与 PERCENT 一致且兼容所有浏览器。
- 禁止为单个元素创建额外 CSS class；完全相同字体属性在同一界面出现 ≥2 次才允许抽成共享 class。

### 11.6 输出结构（可选）

复杂页面建议按四段输出，保持可追溯：

- A) 审计区：数据源、image_id、来源模式（`sketch_primary`）、关键尺寸来源。
- B) 规格表：组件 / 层级、frame、fills、borders、圆角、阴影、字体、资源策略。
- C) Vue SFC 代码。
- D) 资源清单：文件路径、格式、来源、是否使用原生绘制。

### 11.7 禁止项

- 禁止用 `lanhu_get_ai_analyze_design_result` 或 `lanhu_get_design_annotations` 的坐标 / 尺寸做像素级还原。
- 禁止用 PNG 像素采样取色、测距、测圆角。
- 禁止用“看起来差不多”“大约”等估算替代 sketch 树数值。
- 禁止忽略树层级自行猜测父子关系。

### 11.8 组件复用原则

**默认倾向复用**：设计稿元素能映射到目标技术栈 UI 库或项目现有组件 / 样式资产时，优先复用并覆盖样式，不新造轮子。

执行规则：

1. 动手前先检索目标项目现有组件 / 类名，有直接对应的就复用；复用方式为组件 / props / CSS 变量 / deep 覆盖，并对齐设计稿数值。
2. 同一视觉模式（卡片面板、弹窗、动作按钮等）与现有页面一致时，沿用现有类名结构，保持全站视觉统一。
3. 现成组件与设计稿结构差异过大（如自定义复杂表格、特殊树形）时可自写，但须在输出中说明不复用原因。
4. 复用的组件仍须按设计稿数值覆盖（表格行高 / 表头底色 / 圆角 / 边框），不能直接沿用默认样式。

## 附录：可选 MCP Server 桥接

本节为可选扩展，不属于 skill 核心能力。skill 本身独立可用，无需阅读本节即可正常使用。

仓库内另含一个独立的 MCP Server 工程（`lanhu_mcp_server.py`），可将同一套 `lanhu/tools` 纯函数暴露为 MCP 工具，供支持 MCP 的客户端调用。关系如下：

- **共享逻辑**：MCP Server 复用 `lanhu/tools/*.py` 的纯函数，不重复实现。
- **配置分离**：MCP Server 的配置来自其自身 `.env` / `.mcp.json`，与 skill 的 `.env` 互不读取。
- **skill 不依赖 MCP**：无论是否部署 MCP Server，本 skill 的 CLI 脚本均可独立运行。

CLI 脚本与 MCP 工具名映射（仅供参考，不是 skill 使用前提）：

| CLI 脚本 | 等效 MCP 工具名 |
|----------|----------------|
| `scripts/fetch_sketch.py` | `lanhu_get_sketch_json` |
| `scripts/extract_layers.py` | `lanhu_extract_layers` |
| `scripts/verify_layers.py` | `lanhu_verify_layers` |
| `scripts/layout_intent.py` | `lanhu_analyze_layout` |
| `scripts/summarize_page.py` | `lanhu_summarize_page` |
| `scripts/crop_icons.py` | `lanhu_crop_icons` |
| `scripts/check_spacing.py` | `lanhu_check_spacing` |
