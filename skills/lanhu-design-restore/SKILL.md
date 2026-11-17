---
name: lanhu-design-restore
description: 从蓝湖（Lanhu）设计稿原始图层树（sketch JSON）取数，并按规范流程做像素级前端还原。当需要按蓝湖设计稿还原前端页面、核对样式，或发现 lanhu_get_ai_analyze_design_result 返回的拍平散件“只有位置、细节全错”时使用。触发词：蓝湖还原、设计稿还原、lanhu 取数、设计稿细节。
---

> 配置：环境变量 LANHU_COOKIE 或 skill 根目录 .env 文件；依赖安装见 requirements.txt。

# 蓝湖设计稿像素级还原

## 1. 使用条件

### 1.1 适用场景

在以下场景使用本 skill：

- 需要按蓝湖设计稿还原前端页面或核对样式，且存在可访问的蓝湖项目 / 设计页。
- 需要从设计稿获取精确的坐标、间距、颜色、渐变、边框、阴影、圆角、字体等结构数据。
- 需要以数据驱动方式产出符合工程标准的组件实现。

### 1.2 不适用场景

在以下场景不使用本 skill：

- 数据源不是蓝湖设计稿（无法取得 `project_id` / `image_id`）。
- 仅需粗略视觉近似，不要求数据精确。
- 已有结构化图层数据，仅需执行单一分析步骤（此时可直接调用对应 CLI 脚本，见 §10，无需完整流程）。

## 2. 核心原则

1. **数据驱动**：还原是纯数据驱动，视觉（多模态看图 / 像素处理）不参与取值，仅承担质检（确认缝隙、边框可见边等偏差）与兜底（仅有位图、无结构化数据时）两个角色。
2. **权威数据源唯一**：只有原始图层树（sketch JSON）可用于像素级还原；标注降级模式（拍平散件）禁止使用。
3. **数值可追溯**：每个样式值必须可追溯到 sketch 字段；禁止以估算、目测、像素采样代替。
4. **全文优先，摘要只做索引**：`layers.json` 是唯一完整数据源，**必须整份读取**（一个典型页面约 500–600 节点、70–160k tokens，现代长上下文模型一次可读完）。`page_summary.json` 只是六类元素的导航索引（cards/inputs/buttons/switches/icons/text_styles），**不含层级关系、也不含大多数节点的样式**——只读摘要会导致结构错漏，这是历史上还原出错的主要原因。

### 2.1 数据源对照

| 形态 | 数据来源 | 内容 | 结论 |
|------|---------|------|------|
| 标注降级（拍平散件） | `lanhu_get_ai_analyze_design_result` | 每图层一个绝对定位 div + data-css，仅坐标与简单 css | 丢失组件分组、背景形状、渐变 / 精确 border/shadow、字体 letterSpacing，**禁止用于像素级还原** |
| 原始图层树 | `get_sketch_json` + 上游 `lanhu_design.normalize` | 完整容器层级、fills（含渐变 stops）、borders、shadows、字体（name/size/letterSpacing/align/color），另加**稳定 node_id / 坐标归一 / gaps 诊断 / 素材变体** | **唯一权威数据源** |

> **取数引擎**：`extract_layers.py` 优先调用上游 `lanhu_design.normalize.normalize_design()`——稳定身份（源 id，重名降级为 pointer 哈希）、坐标归一（Figma 混合原点）、三格式支持（sketch 扁平 `info[]` / figma `artboard` / photoshop `board`）、`gaps[]` 诊断、素材变体（区分 designer export 与 render fallback）都来自它。
> 产物形状仍是本 skill 的 `layers.json`（`style` 已解释成 CSS、`text` 已整理成字段），并新增 `node_id` / `source_frame` / 根节点 `_meta`。上游包不可用时自动回退到本地 `walk`（`_meta.engine = "legacy_walk"`）。

### 2.2 降级与视觉定位

- D2C 通道失败（报 `store_schema_revise 失败: 版本数据不存在`）属正常降级。蓝湖官方 D2C 仅私有部署且依赖 MasterGo，公开套餐不含，无需为还原开通。
- 像素采样是干扰源：可能采到文字、抗锯齿、渐变中点，或被上层覆盖面板的颜色误导，禁止用于取色。
- 视觉形状（内容区 / 卡片背景、边框等）在标注模式中已合入整图，必须从 sketch 树的 fills / borders 读取。

## 3. 前置条件（启动前确认）

1. **蓝湖 Cookie**：`LANHU_COOKIE` 有效。环境变量优先；或在 skill 根目录创建 `.env` 填入 `LANHU_COOKIE=...`；运行脚本可加 `--no-dotenv` 跳过 `.env`。
2. **运行环境**：Python 3.10+，执行 `pip install -r requirements.txt`（httpx、Pillow）。
3. **工作目录**：在目标项目根目录执行，所有产物落于 `<项目根>/.lanhu/` 固定子目录，不依赖环境变量。跨项目天然隔离，同项目可跨会话复用；需要其他落点时显式传 `--workdir <DIR>`；解析到 skill 自身安装目录时报错退出。

## 4. 执行流程（按序执行，每阶段有门禁）

流程分三阶段；**门禁检查点未通过不得进入下一阶段**。

### 阶段 A：取数与提取

**A0. 结构盘点（必做）**

打印整棵树的容器层级（name + frame + fill + border + children），从根容器到叶子，建立“大容器→留白→子区域”的骨架认知后再动手。跳过此步而按局部反馈排查，可能把被覆盖层误判为页面底色。

**A1. 获取设计图标识**

从蓝湖项目 / 设计页 URL 读取 `project_id` 与 `image_id`（链接参数可见）。

**A2. 拉取原始图层树**

```bash
python scripts/fetch_sketch.py <project_id> <image_id> [--team_id TEAM_ID] [--version-id VID] [--workdir <DIR>] [--render <render.png>]
```

输出 `.lanhu/projects/<PID>/images/<IID>/raw/sketch.json`，写 `manifest.json` 标记 `fetched`；`--render` 将本地渲染图拷入 `raw/render.png`。

**版本固定**：不传 `--version-id` 时取最新版，但无论是否指定，都会把 `version_id / version_name / sha256 / json_url` 写入 `raw/sketch.meta.json`，并在 `layers.json._meta.source_version` 里带出。同一条命令两次跑出不同数值时，先比对这个文件——分得清是稿子改了还是代码改了。要复现历史结果就显式传 `--version-id`。

**A3. 结构化提取**

```bash
python scripts/extract_layers.py --project-id <PID> --image-id <IID> [--workdir <DIR>]
```

输出 `layers.json`（name/type/**node_id**/frame/**source_frame**/style[fills/gradients/borders/shadows/radius]/text[font/letterSpacing]，色值转 rgba()），根节点带 `_meta`：
`engine`（`upstream_normalize` / `legacy_walk`）、`coordinate_mapping`（`verified` / `strategy`）、`gaps` + `gaps_summary`、`assets`（含 `kind`: `exported_asset` 或渲染兜底）、`source_version`。标记 `layers_extracted`。亦支持显式路径 `extract_layers.py <sketch.json> <out.json>`。

**定位一律优先用 `node_id`**：`frame` 是坐标归一后的值（画板本地空间），`source_frame` 是原始值，需要追溯时用后者。

**A4. 提取校验（门禁）**

```bash
python scripts/verify_layers.py --project-id <PID> --image-id <IID> [--workdir <DIR>]
```

检查项，**全部 PASS 方为提取合格**：

1. 文本 color 缺失数为 0。
2. 渐变节点含 gradientType/from/to。
3. border 含 lineAlignment 与 thickness（粗细来自原始 `width` 字段，`width=0` 表示无边框）。
4. 阴影含 inset。
5. rotationDeg≠0 的节点列表（人工确认）。
6. 传入 sketch.json 时抽查文本 color/fontWeight 与原始一致。
7. `node_id` 齐全且唯一（缺 id / 重复 = 0）。
8. `_meta.coordinate_mapping.verified` 为 true；为 false 时区域裁图与素材导出都不可信，须先查 `unresolved_node_ids`。
9. `_meta.gaps_summary` 无阻断项（`nonzero_canvas_origin_unverified` / `unsupported_source_structure` / `missing_canvas_dimensions`）；`transform_preserved_not_applied` 属已知行为，不算失败。

失败时修复提取逻辑并重跑 A3–A4，**不得携带缺失数据进入阶段 B**。

**A5. 读取全文（必做，取数主路径）**

把 `layers.json` **整份读进上下文**，它是后续所有数值的唯一来源。按页面规模选一种读法：

| 规模 | 读法 |
|------|------|
| ≤ 800 节点（多数页面） | 一次读完整份 `layers.json` |
| > 800 节点 | **两级读**：① 先读骨架（只取 `name/type/frame` 与 `children` 结构，约 15–20k tokens）确认整页骨架；② 再按组件读子树（每个容器 7–10k tokens），边实现边读 |

- 只读 `page_summary.json` 或只看自己关心的几个容器**不算读过全文**；未读过全文就动手实现，视为流程违规。
- 读全文后先列出「页面骨架清单」（根容器 → 一级区块 → 各区块内的卡片/表单/表格），作为 C1 实现的施工顺序。
- 若模型上下文确实放不下（超长报表页），按区块分批读，但**每个区块必须读完整子树**，不得跨区块拼凑。

### 阶段 B：分析与校验

**B1. 布局意图分析（可选）**

```bash
python scripts/layout_intent.py --project-id <PID> --image-id <IID> [容器名] [--workdir <DIR>]
```

输出 `analysis/layout_intent.json`，判断版心策略（center / full-width / fixed-left），避免把应居中的内容区实现为固定 `padding-left`。

**B2. 页面规格摘要（可选，仅作导航索引）**

```bash
python scripts/summarize_page.py --project-id <PID> --image-id <IID> [page_name] [--workdir <DIR>]
```

输出 `analysis/page_summary.json`（cards / inputs / buttons / switches / icons / text_styles），用于**快速建立「这页有哪些卡片/表单/按钮」的索引**、发现容易漏掉的元素。

- ✅ 可用作：元素清单核对、全局样式锚点（主色/圆角/字号分布）、MCP 工具入参。
- ❌ 不得用作：数值来源、结构来源。摘要是有损投影——六类以外不覆盖、层级关系不保留。任何写进代码的值必须回到 `layers.json`（A5）核对。

**B3. 图标 / 切图获取（按需，含决策链）**

资源按以下顺序获取：**先复用既有图标库 → 再设计师切图 → 最后从设计稿裁占位图；严禁手绘自造**。

0. **先查既有图标库（第一步，必做）**：在项目存量资源里找与设计稿同款的图标——
   雪碧图 `src/assets/icons/**`（`IconSvg` 按 `icon-[dir]-[name]` 引用）、图片 `src/assets/images/**`、既有页面的图标用法。
   - **比对必须并排渲染核对**：把候选既有图标与设计稿裁图同屏渲染、截图比对（名字相同不代表同款——`AI_edit_blue` 是"铅笔+横线"，与设计稿的"笔+圆角方框"并非同款）。
   - 命中的**直接复用，不新增文件**；同一构造只保留一份（如两页共用的标题小标）。
1. 无可复用时，检测 sketch 树是否含设计师标注的 slice（`total_slices > 0`）：
   ```bash
   python scripts/download_slices.py --project-id <PID> --image-id <IID> [--workdir <DIR>]
   ```
   有 slice → 下载真图到 `slices/`（png/svg，通常 2x），标记 `slices_downloaded`；无 slice → 脚本提示改用下一步。
2. 以上都没有，才从渲染图裁剪**占位图**：
   ```bash
   python scripts/crop_icons.py --project-id <PID> --image-id <IID> [--workdir <DIR>] [--fmt webp|png] [--name-map x.json]
   ```
   输出 `icons/*.webp`（默认 webp，失败自动回退 png），标记 `icons_cropped`。
   同时写 `icons/icons_manifest.json`，其中 `source: "render_placeholder"` + `provenance` 标明「非原始素材」；`saved[].source` 也会逐张打标，供后续核对。
   需要在具体框位精裁（如卡片标题小标、菜单项图标）时，用 `raw/render.png` + 设计框 × 渲染倍率（通常 2x）自裁：
   ```python
   im = Image.open('<IID>/raw/render.png'); scale = im.size[0] / <artboard.width>
   im.crop(tuple(int(v * scale) for v in (left, top, right, bottom))).save(out, 'WEBP', quality=95)
   ```
   ⚠️ 裁图与复用都要在**代码里注明来源**：裁图注明「设计师未切图，暂用设计稿渲染图裁的占位图」，复用注明取自既有哪个图标——正式切图到位后只替换文件、不改代码。

> **可选：上游 MCP 的真原件交付**。若 MCP 端为上游 1.8.0+（含 `lanhu_export_design_assets`），它下载的是设计师导出的原始文件并校验像素/哈希，比本 skill 的 slice 下载更严（区分 designer export 与 render fallback、支持 `prefer_svg`）。
> 有该工具时**优先用它取素材**，`download_slices.py` 作为离线/无 MCP 时的等价路径，`crop_icons.py` 只在两者都拿不到时兜底。

**B4. 容器间距校验（门禁）**

```bash
python scripts/check_spacing.py --project-id <PID> --image-id <IID> [容器名] [--workdir <DIR>]
```

输出 `analysis/spacing.json`。跨页同构容器（如不同页面的同名左面板 / 内容区）必须用 `--compare` 比对 width 与 padding。**偏差报告无异常方可进入阶段 C**。

### 阶段 C：实现与交付

**C1. 实现**：按 §7 取值约束、§8 布局规则与 §12 输出规范实现组件；数值一律取自 `layers.json` / `analysis/*`，禁止截图估算。

**C2. 静态校验**：ESLint / vue-tsc 通过，无命名 / 类型警告。

**C3. 最终检查**：逐项通过 §11 检查清单后交付。

## 5. 目录约定（.lanhu）

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
          slices/                   # download_slices 输出（设计师标注的真图）
          icons/                    # crop_icons 输出（裁剪渲染图的占位图）
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

## 6. 取值约束（属性 → 来源，硬性）

每个属性只允许一种来源，禁止来源一律不得使用。

| 属性 | 来源字段 | 禁止来源 |
|------|---------|---------|
| 节点身份 | `node_id`（稳定，重名也不冲突） | 仅靠 `name`（实测一个 584 节点页面有 68 组重名、涉及 414 个节点） |
| 坐标 / 尺寸 | `frame.left/top/width/height`（已归一）；追溯原始值用 `source_frame` | 绝对定位 div 坐标 |
| 背景 / 渐变 | `style.fills`（含 stops） | PNG 像素采样 |
| 边框 | `style.borders` | 截图目测 |
| 圆角 | `paths[].radius`（topLeft/topRight/bottomLeft/bottomRight） | `node.radius`（常见空数组）/ 截图 |
| 阴影 | `style.shadows` | 截图估算 |
| 字体 | `text.font/name/size/letterSpacing/align/color` | 截图目测 |
| 间距 | 子层 `frame` 差值（如 child.left - parent.left = padding） | 标注模式的 measurements |

## 7. 字段映射细则

- **圆角**：位于 `paths[].radius`，而非节点级 `node.radius`（常为空数组）。蓝湖网页标注的 border-radius 与 `paths.radius` 一致。
- **阴影**：sketch 原始字段为 `x`/`y`（偏移）、`blur`、`spread`、`inset`（方向标记），非 `offsetX/offsetY/blurRadius`。`inset: true` → `box-shadow: inset ...`。示例：`x0 y4 blur10 spread0 inset:true` → `inset 0 4px 10px rgba(0,0,0,0.05)`。
- **文本颜色**：位于 `text.style.color`，非 `font.color`。任何文本色值必须查 `layers.json` 的 `text.color`。
- **渐变**：fill 含 `from`/`to`（局部坐标，dy=0→水平、dx=0→垂直）与 `type`（0=linear、1=radial）。线性渐变 CSS 角度由 from/to 推导。
- **边框**：含 `lineAlignment`（inside/center/outside）与 `thickness`（对应原始字段 `width`；`width=0` = 无边框，须如实区分，勿统一补边框）。inside 在 border-box 下视觉一致；center 描边两侧各半。`paths[].type` 为 `"path"` 时 border 仅沿路径描边（单线），`"rect"` 才是四边边框；可见边须以像素扫描（1px 步长）确认。
- **变换 / 旋转**：旋转节点的 `frame` 是旋转后包围盒（如 9×9 方块旋转 45° 后 bbox 为 13.41×13.41）。`rotationDeg` 由 transform 2×2 线性部分推导（θ=atan2(b,a)）。
- **文本附加属性**：`fontWeight`（数值，较 fontType 精确）、`verticalAlignment`、`underline`、`linethrough`、`lineSpacing` 均需提取。
- **sharedStyle**：设计规范色值命名（如 `填充/Primary2`），与 fills 同源，可作色值来源注释与验证。
- **无需提取的字段**：节点级 `radius`（仅 artboard 自身 0 值）、`style.blurs`、`blendMode`、`text.value`（与 style.content 全等）、`text.styles` 多段（全单段）、`paths.booleanOperation/subpaths`、`realFrame`（差异仅旋转节点，transform 已覆盖）、fill/border/shadow 各自 opacity（全 1）、`visible=false` 节点、`style.isEnabled`、symbolInstance 的 symbolId/overrides。
- **提取脚本修改后的自检清单**：①文本 color 缺失数为 0；②渐变节点含 from/to/gradientType；③border 含 lineAlignment 与 thickness；④阴影含 inset；⑤列出 rotationDeg≠0 节点核对；⑥随机抽取 1 个文本对比原始 sketch 的 style.color/fontWeight。

## 8. 布局与间距规则

1. **间距语义定位**：由区域容器 frame（右缘 = left + width）与各子元素 frame，逐项计算子元素相对父的左右间距后归类：
   - 全部子元素贴某边 → 父容器 `padding`。
   - 仅个别元素不贴边 → 该元素自身 `margin`（禁止用父 padding 一刀切）。
   - 决策表：统一缩进 → 父 padding；兄弟均匀间距 → 父 gap；单个元素独有 → 子 margin；间距区需显示父背景或可点击 → padding；纯页面留白 → margin；垂直间距优先 padding/gap（防 margin 折叠）；组件内部 → 组件 padding；组件之间 → 父 gap 或子 margin。
2. **影响面检查**：修改父级样式（padding/width/border）前，先列出全部子元素并逐项确认改动适用性；“收窄”类改动（padding 置 0、宽度减小）风险最高。
3. **层级归属**：每个视觉元素先确认所属容器及其边界。两层容器（大容器 + 小面板）本质是留白意图，应合并为一个容器 + padding/margin；`path` 为单线描边（边框边数按像素扫描确认）。
4. **逐图核对**：同一页面存在多个 tab / 状态 / 弹窗时，每个状态对应一张独立设计图，必须逐图核对容器样式（fills/borders/shadows/radius/padding 全维度），禁止将一张图的结论推断到另一张图。共用骨架（导航、外壳、左右面板）可复用结论，内容区必须逐图核对。
5. **坐标换算**：设计稿画布坐标换算到响应式布局时，用组件容器 frame 的起点与宽度推导间距，不使用文字图层坐标。`frame.left` 不得直接转成固定左偏移 / `padding-left`：先计算 `(artboard.width - frame.left - frame.width)`；左右空白接近时优先 `max-width + margin: 0 auto` 居中，仅当明显对应真实侧边栏 / 出血区时才用固定偏移。
6. **坐标空间**：取数走上游 normalize 时，`layers.json._meta.coordinate_mapping` 给出 `verified` / `strategy`，`layout_intent.json` 的 `coordinate_space` 会标 `upstream_normalized` 并带出该标记——**`verified=false` 时不要信任何区域裁图/导出**。走本地回退引擎（`legacy_walk`）时才会用采样越界量判定（`space` / `dx` / `dy` / `evidence`）；任何情况下都别用单个节点的 `left < 0` 去猜，浮点噪声（`-0.000244`）会把它带偏 100+ 像素。

## 9. 禁止条例（硬性红线，违反即返工）

1. 禁止使用 `lanhu_get_ai_analyze_design_result` 或 `lanhu_get_design_annotations` 的坐标 / 尺寸做像素级还原。
2. 禁止使用 PNG 像素采样取色、测距、测圆角。
3. 禁止使用“看起来差不多”“大约”等估算替代 sketch 树数值。
4. 禁止将一张设计图的结论推断到另一张图；每个 tab / 状态必须逐图核对。
5. 禁止把 `frame.left` 直接实现为固定左偏移 / `padding-left`（先计算画布余量再决策，见 §8.5）。
6. 禁止只读 `page_summary.json`（或只看自己感兴趣的容器）就动手实现——必须先按 A5 读全文/读完区块子树。
6. 禁止按旋转后 bbox 绘制旋转元素（`rotationDeg≠0` 必须 CSS `transform: rotate`）。
7. 禁止为单个元素创建额外 CSS class；禁止整页 `transform: scale(...)`。
8. 禁止忽略树层级自行猜测父子关系。
9. 禁止把 sketch.json / layers.json / 渲染 png 散落在工作目录或临时目录（必须落 `.lanhu/`）。
10. **禁止手绘 / 自造近似图标**（含用 CSS、emoji、自写 SVG 拼一个"大致像"的图标）。图标只能来自三者之一：**既有图标库复用、设计师 slice、设计稿裁图**；三者都无来源时先与用户确认，不得自造交付。
11. **禁止重复添加资源**：新增任何图标 / 切图前，先检索既有资源库与本次已引入的资源，同款复用同一份文件；清理阶段删掉未被引用的新增资源。

## 10. CLI 工具参考

以下脚本调用 `lanhu/tools` 下的纯函数，无需任何 MCP 协议或 MCP 客户端配置即可独立运行。所有脚本均支持 `--workdir <DIR>`；不传 `--project-id/--image-id` 时退化为显式路径模式（仅打印、不落盘）。

| 脚本 | 用途 | 标准调用（.lanhu 模式） |
|------|------|------------------------|
| `fetch_sketch.py` | 拉取原始图层树 + 版本固定 | `python scripts/fetch_sketch.py <PID> <IID> [--version-id VID] [--workdir <DIR>] [--render x.png]` |
| `extract_layers.py` | 提取结构化图层树 | `python scripts/extract_layers.py --project-id <PID> --image-id <IID> [--workdir <DIR>]` |
| `verify_layers.py` | 提取完整性校验 | `python scripts/verify_layers.py --project-id <PID> --image-id <IID> [--workdir <DIR>]` |
| `layout_intent.py` | 布局意图分析 | `python scripts/layout_intent.py --project-id <PID> --image-id <IID> [容器名] [--workdir <DIR>]` |
| `summarize_page.py` | 页面规格摘要 | `python scripts/summarize_page.py --project-id <PID> --image-id <IID> [page_name] [--workdir <DIR>]` |
| `download_slices.py` | 下载设计师标注的切图（真图） | `python scripts/download_slices.py --project-id <PID> --image-id <IID> [--workdir <DIR>]`；无 slice 时提示改用 crop_icons |
| `crop_icons.py` | 从渲染图裁剪图标（无 slice 时的占位图） | `python scripts/crop_icons.py --project-id <PID> --image-id <IID> [--workdir <DIR>] [--fmt webp\|png]` |
| `check_spacing.py` | 容器间距校验 / 跨页对比 | `python scripts/check_spacing.py --project-id <PID> --image-id <IID> [容器名 | --container 容器名] [--workdir <DIR>]`；跨页：`--compare <a.json> <b.json> --name <容器名>` |

### 推荐流水线

```
fetch_sketch.py   --project-id PID --image-id IID            # → raw/sketch.json (+ raw/render.png)
extract_layers.py --project-id PID --image-id IID            # → layers.json
verify_layers.py  --project-id PID --image-id IID            # → analysis/verify.json（门禁）
# ★ 整份读取 layers.json（见 A5）—— 取数主路径，不可跳过
layout_intent.py  --project-id PID --image-id IID            # → analysis/layout_intent.json
summarize_page.py --project-id PID --image-id IID            # → analysis/page_summary.json（仅索引，非数值来源）
# ↓ 图标：先复用既有图标库（无命令，检索 src/assets/icons|images + 并排渲染比对），命中则跳过下面两步
download_slices.py --project-id PID --image-id IID           # → slices/*（设计师真图，优先）
crop_icons.py     --project-id PID --image-id IID            # → icons/*.webp（无 slice 时兜底，来源标 render_placeholder）
check_spacing.py  --project-id PID --image-id IID '容器名'    # → analysis/spacing.json（门禁）
check_spacing.py  --compare a.json b.json --name '容器名'    # 跨页对比（显式路径）
    → 依据 layers.json / analysis/* 实现目标技术栈组件（数值一律取自结构化数据，禁止截图估算）
```

每一步的输出均按 `PID/IID` 落在 `.lanhu` 下并在 `manifest.json` 标记完成状态；重跑同一张图直接命中缓存，无需重新请求蓝湖。

## 11. 最终检查清单（交付前逐项确认）

按优先级执行；任何不确定项应回退到数据核对，而非目测判断。

- [ ] **数据源**：所有尺寸 / 样式取值来自 `sketch.json` / `layers.json`，未使用 `lanhu_get_ai_analyze_design_result` 的拍平散件。
- [ ] **读过全文**：已按 A5 整份读取 `layers.json`（或按区块读完每个子树），未仅依赖 `page_summary.json` 就动手实现；页面骨架清单已列出。
- [ ] **定位方式**：定位容器/元素用 `node_id`（而非仅用 name）；若报告或日志里出现同名多个，已回 `layers.json` 用 id 消歧。
- [ ] **结构盘点**：已打印整棵树的容器层级（name + frame + fill + border + children），理解“大容器→留白→子区域”骨架。
- [ ] **多图比对（可选，仅当页面存在多个 tab / 状态 / 弹窗时）**：每个状态对应一张独立设计图，已分别核对样式，未将一张图的结论推断到另一张图。
- [ ] **间距归属**：每个间距已按决策表归到正确层级——“一致”用父 padding/gap、“个别”用子 margin；垂直间距优先 padding/gap；组件内部用 padding，组件之间用 gap 或子 margin。
- [ ] **硬算 / 测量**：每个区域关键尺寸通过 frame 计算（right = left + width），无子元素越界或留白异常。
- [ ] **容器间距校验（强制，未通过不得进入下一区域 / 下一页）**：本区域关键容器已跑 `check_spacing.py`，padding/margin/gap 来自 sketch 帧；偏差报告无异常。跨页同构容器已对比 width 与 padding。示例：
  `python check_spacing.py --compare <pageA_layers.json> <pageB_layers.json> --name "<容器名称/ID>"`
  （`pageA_layers.json` 即 `.lanhu/projects/<PID>/images/<IID>/layers.json`）
- [ ] **底色 / 背景**：通过 `style.fills` 读取渐变 stops，未用 PNG 采样取色；被上层覆盖的底层颜色已确认实际可见色。
- [ ] **边框**：`style.borders` 读取 thickness + color，可见线条用 1px 扫描确认，已区分 path 描边与实边框。
- [ ] **圆角**：使用 `paths[].radius`，未按 bbox 画矩形。
- [ ] **字体**：font name/size/weight/letterSpacing/align 已对应；letter-spacing 已按 em 表达（见 §12.5）。
- [ ] **阴影**：`style.shadows` 读取 offset/blur/spread/color，inset 已标注。
- [ ] **图标来源（强制）**：逐个图标标注来源——「既有库复用（写明取自哪个图标）/ 设计师 slice / 上游 export 原件 / 设计稿裁图（占位）」；**无手绘自造**；已输出两份清单：复用了哪些既有图标、新增了哪些资源，二者无重复项。用了 `crop_icons.py` 时已确认 `icons/icons_manifest.json` 里 `source=render_placeholder`，且代码注释写明占位。
- [ ] **切图（可选，仅当存在图标 / 占位图且设计师未提供 slice 时）**：无既有可复用项的图标已切为占位图，并在代码中标注“设计师未切图，暂用占位图”。
- [ ] **组件适配**：优先使用目标技术栈的 UI 库与项目已有组件（覆盖样式而非重造）；**先查目标项目根目录 `.zcode/skills/` 是否有项目级 UI 规约 skill（如 aiViewer 的 `aiviewer-ui-conventions`），有则按其映射表执行**；需覆盖样式时用 `:deep()` 或组件提供的样式 hook，不污染全局。
- [ ] **布局**：flex 实现，无绝对定位 div 拼凑；关键元素（按钮、icon）未被压缩或隐藏。
- [ ] **静态校验**：ESLint / vue-tsc 通过，无命名 / 类型警告。

## 12. Vue 3 输出规范

若目标技术栈为 **Vue 3 + Element Plus**，实现交付阶段（§4-C）需遵守对应组件、布局与资源规范。
详见 [references/vue3-frontend-guide.md](references/vue3-frontend-guide.md)。

## 13. 程序化调用（Python API）

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

## 14. 故障排查

| 现象 | 处理 |
|------|------|
| D2C 通道报 `store_schema_revise 失败: 版本数据不存在` | 正常降级，无需处理；继续用 sketch 树取数 |
| 请求返回 401 / Cookie 无效 | 检查 `LANHU_COOKIE` 是否有效、是否过期；确认 `.env` 或环境变量已正确加载 |
| 渲染图坐标偏移 | 渲染图通常为 2x，`crop_icons.py` 按 `png.width / artboard.width` 自动缩放，无需手动处理 |
| 验证器失败 | 按 §A4 六项逐项定位（多为字段名映射错误），修复提取逻辑后重跑 A3–A4 |
| 脚本报“无法导入 lanhu.tools” | 确认在 skill 根目录下运行，或按 §13 通过 `sys.path.insert` 引导 |


## 附录

- **Vue 3 + Element Plus 输出规范**：见 [references/vue3-frontend-guide.md](references/vue3-frontend-guide.md)。
- **可选 MCP Server 桥接**：见 [references/mcp-bridge.md](references/mcp-bridge.md)。

