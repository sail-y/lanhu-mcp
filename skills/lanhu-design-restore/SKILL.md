---
name: lanhu-design-restore
description: 用蓝湖( lanhu-mcp )数据做像素级前端还原的正确取数方法。当需要"按设计稿还原前端页面/核对样式"、且数据源是 lanhu-mcp 时使用。解决"analyze 拍平散件只有位置、细节全错"的问题。触发词：蓝湖还原、设计稿还原、lanhu 取数、设计稿细节。
agent_created: true
---

# 蓝湖(lanhu-mcp)设计稿数据正确用法

## 总纲：工程化优先，还原只是输入

**最终目的是工程化生产实现，不是"看起来像"的还原。** 如果只为视觉一致，100% 绝对定位最快；但我们是做项目、部署 demo，必须符合生产系统开发标准。

- **还原数据（sketch 树）是输入**：保证视觉正确（坐标/间距/颜色/圆角/字体精确），仅此而已。
- **生产实现是输出**：实现方式必须满足工程标准，视觉精度通过"数据覆盖样式"达成，而不是通过绝对定位/魔法值堆出"看起来一样"。

**本项目（aiViewer: Vue 3 + TS + Element Plus）生产标准（每区域必守）**：
1. `<script setup lang="ts">` + 完整 TS 类型（VO/DTO 来自 `src/api/projectSetting.ts` 契约）
2. 组件复用优先（Element Plus / BaseDialog / IconSvg / c6-* / 页面样式锚点），覆盖样式而非重造
3. **flex 响应式布局**，禁绝对定位堆布局；浮层控件（收起按钮/角标）例外
4. 数据对接后端 API，不写死假数据（除明确占位并标注 TODO）
5. 组件拆分、props/emits 单向数据流；命名规范（多词组件、语义类名）
6. ESLint / vue-tsc 静态校验通过；注释标注数据来源（如 `/* 设计稿 elN/容器xxx L=.. */`）
7. 语义化 DOM、可访问性基础；不优雅 hack（transform scale 整页、负 margin 布局等）

## 核心认知（务必先读）

`lanhu_get_ai_analyze_design_result` 返回的是 **"标注降级模式"的拍平散件**：
- 触发条件：D2C 通道(`get_design_schema_json` → DDS `store_schema_revise`)失败，server 自动降级到 Sketch annotation fallback。
- 特点：每图层一个绝对定位 div + data-css，**只有坐标和简单 css**。
- **丢失**：①组件分组 ②背景形状(合进整图) ③渐变/精确 border/shadow ④字体 letterSpacing。
- 结论：**"位置对、细节全错"是必然的**，不能用它做像素级还原。

**权威数据源 = `get_sketch_json`（原始图层树）**，里面有全部结构信息：
- 完整容器层级（如 容器3669 → title_style1 → tab组 → 文本+下划线）
- 形状独立节点带 fills（含**渐变 stops**）、borders、shadows
- 文本节点带字体(font name/type/size/**letterSpacing**/align/color)
- 设计师命名（面包屑box / title_style1 / subnav / 选择框 inputBox / Button…）

**视觉模型定位（用户定调 2026-08-16）**：有完整结构化数据时还原是**纯数据驱动**，不需要视觉理解；视觉（多模态看图/像素处理）只承担两个角色——①**质检**（看图找偏差，如缝隙/边框可见边）；②**兜底**（设计稿只有图、无结构化数据时才是唯一通道）。**视觉不参与取数/取值**——散件、像素采样都是干扰源（曾把被面板盖住的 #F6F9FE 采成白）。`lanhu_get_ai_analyze_design_result` 输出拍平散件是"工具把数据毁了"，绕过它直读 sketch 树即可。

D2C 通道失败报 `store_schema_revise 失败: 版本数据不存在` 是**正常降级**，蓝湖官方 D2C 仅私有部署且须 MasterGo（公开套餐不含），**不需要为还原去开通 D2C**。

## 前置条件（唯一外部依赖，满足即可开干）

1. **lanhu-mcp 已配置**：`~/.workbuddy/mcp.json` 的 `lanhu-mcp.env` 含 `LANHU_COOKIE`（+ 可选代理 `http_proxy/https_proxy`）。
2. **lanhu_mcp_server.py 可访问**：默认探测 `<skill>上级/lanhu-mcp/lanhu_mcp_server.py`，可用 `--server` 或环境变量 `LANHU_MCP_SERVER` 指定。
3. **运行环境**：脚本需在装有 server 依赖（httpx/fastmcp 等）的 Python 环境跑（本项目 `<repo>/.venv`）。

## 标准取数流程

0. **【结构盘点，必做】还原前先打印整棵树的容器层级**（name + frame + fill + border + children），从根容器一路看到叶子，先看懂"大容器→留白→子区域"的骨架再动手。教训：之前跳过了这步、按用户反馈局部查，导致把被覆盖的 3670(#F6F9FE) 误当页面底色（真正页面底是 3713 #FFF）——**数据一直在，是没系统性消费**。
1. `lanhu_get_designs(url)` 拿设计图列表（name/index/id）。
2. 拉原始图层树：`scripts/fetch_sketch.py <project_id> <image_id> <out.json> [--team_id TEAM_ID] [--server PATH]`（自动读 mcp.json 的 cookie/代理，注入 stub 绕过 IDE 的 codex_stdio_bridge 依赖；server 在 import 时一次性读 cookie）。
3. 跑 `scripts/extract_layers.py <sketch.json> <out.json>` 转成结构化 JSON（递归输出 name/type/frame/style[fills/gradients/borders/shadows/radius]/text[font/letterSpacing]，把 sketch 色值转 rgba()）。核心逻辑在 `lanhu/tools/layer_extractor.py`。
4. **提取后必跑验证器**：`scripts/verify_layers.py <out.json> [sketch.json]`（仓库 `scripts/verify_layers.py`）。6 项检查：文本 color 缺失=0、渐变含 gradientType/from/to、border 含 lineAlignment、shadow 含 inset、rotationDeg≠0 列表（人工确认）、传 sketch.json 时抽查文本 color/fontWeight 与原始一致。**全部 PASS 才算提取合格**。
5. 还原时以结构化 JSON 为准：
   - `frame.left/top/width/height` → 布局与间距
   - 组件树层级 → margin/padding 语义（子层 left 差值 = 间距）
   - `style.fills` → 背景/渐变（**不要**用 PNG 像素采样取色：会采到文字/抗锯齿/渐变中点；还会采到"盖在上层的面板颜色"误判底层，如 3670 #F6F9FE 被白面板盖住→采样得白→误判页面底为白）
   - `style.borders` → 边框（含 thickness；**可见边用像素扫描 1px 确认**，path 描边≠四边）
   - `text.letterSpacing` → 字距（如 tab active 4.5% / inactive 1.8%）
6. PNG 像素扫描**只用于验证**（边框可见边、缝隙、被覆盖层的真实渲染），**不用于取色**。
7. 蓝湖网页标注 CSS 与 sketch 数据同源，可作为快速核对基准。

## 三个必查（每个区域动手前的标准动作）

1. **间距语义定位**：算出区域容器 frame（右缘=left+width），列出每个子元素 frame，**逐个**算子元素相对父的左右间距，再归类：
   - 所有子元素都贴某边 → 用父容器 `padding`
   - 只有个别元素不贴边 → 用该元素自身 `margin`（**不能用父 padding 一刀切**）
   - 实例：面板 3671 右缘 403，树容器「目录」右缘 403（贴右→padding-right 0），但新增组织按钮右缘 391（距右 12→**margin-right 12 只加按钮**）。曾因面板 padding-right 改 0 误伤按钮间距。
   - **决策表**：所有子项统一缩进→父 padding；兄弟均匀间距→父 gap；单个元素独有→子 margin；间距区要显示父背景/可点击→padding；纯页面留白→margin；垂直间距优先 padding/gap（防 margin 折叠）；组件内部（文字与边框）→组件 padding；组件之间→父 gap 或子 margin。**"一致"用 padding/gap，"个别"用 margin；要背景用 padding，纯留白用 margin。**
2. **影响面检查**：改父级样式（padding/width/border）前，列出它所有子元素，逐个确认该改动是否适用——尤其"收窄"改动（padding 有→0、宽度减小）最容易误伤。
3. **层级归属**：每个视觉元素先问"它属于哪个容器、容器边界在哪"，再动手；2 层容器=留白意图（用 padding/margin 合并），path=单线描边（边框边数按扫描定）。
4. **逐图核对（防跨图推断）**：同一页面有多个 tab/状态（如角色管理=权限设置/关联人员两张图），**每个 tab 对应一张独立设计图，必须逐图核对容器样式（fills/borders/shadows/radius/padding 全维度）**，**禁止把一张图的结论推断到另一张图**。实例：角色管理内容卡 3693 权限设置图有 border #E6E6E6 + shadow rgba(0,0,0,0.05)、关联人员图两者皆无——曾两次漏（先漏 border 统一加框、再漏 shadow）。共用部分（导航/外壳/左右面板骨架）可复用结论，**内容区必须逐图核对**。

## venv 调用骨架（cookie 从 mcp.json 注入）

```python
import os, json, importlib.util
cfg = json.load(open(r'~/.workbuddy/mcp.json (Codex 用户也可能是 ~/.codex/mcp.json)', encoding='utf-8'))
for k, v in cfg['mcpServers']['lanhu-mcp']['env'].items():
    os.environ.setdefault(k, v)
spec = importlib.util.spec_from_file_location('lh', '<repo>/lanhu_mcp_server.py' (脚本会通过 _find_repo() / LANHU_MCP_REPO 自动定位))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
# await m.LanhuExtractor().get_sketch_json(image_id, team_id, project_id)
```

## 已知坑

- **边框别盲目套四边**：Sketch 里 `paths[].type` 为 `"path"` 时 border 只沿路径描边（一条线），只有 `"rect"` 才是四边边框。实例：左面板 3671 是 path（右缘竖线）→ 渲染图只有右侧 1px #E0E0E0，左/上/下无边框。**判断边框用像素扫描（1px 步长）确认实际可见边**。
- **"2 层容器" = 留白意图**：大容器 + 小面板（如 3670 大层 + 3671 面板）本质是 margin/padding 留白，实现时合并成一个容器 + padding/margin，不要复刻两层。
- **圆角在 `paths[].radius`（{topLeft,topRight,bottomLeft,bottomRight}），不在节点级 `node.radius`（那常是空数组）！** 之前误判"直角"就是这个原因。`extract_layers.py` 已修正（style_to_css 读 paths）。蓝湖网页标注显示的 border-radius 与 paths.radius 一致（如收起按钮 8px、保存按钮 6px、下拉/导入/新增按钮 4px、复选框 4px、tab 下划线圆头条 8px、标题图标 9×9 直角 0）。
- **阴影字段映射（extract_layers.py 曾踩坑）**：sketch 阴影原始字段是 `x`/`y`（偏移）、`blur`、`spread`、**`inset`（方向标记）**——不是 `offsetX/offsetY/blurRadius`。曾因读错字段名导致 layers.json 里 offset/blur 全为 null、inset 没读，从而把内容卡阴影（真实 `inset 0 4px 10px rgba(0,0,0,0.05)`）误判成"数据缺失"猜成外阴影。**读阴影必须含 inset 字段，inset:true → `box-shadow: inset ...`**。实例：内容卡 3693 = `x0 y4 blur10 spread0 inset:true` → `inset 0 4px 10px rgba(0,0,0,0.05)`；复选框矩形543 = `x0 y1 blur2 inset:true` → `inset 0 1px 2px rgba(0,0,0,0.161)`（曾错写外阴影 0 0 4px）。
- **文本颜色在 `text.style.color`，不在 `font.color`（extract_layers.py 曾全丢）**：曾读 `font.get('color')` 导致 58/58 文本色值全 None——此前所有文字颜色都在"猜"。已改读 `style.color`。**任何文本色值必须先查 layers.json 的 text.color，禁止凭视觉/经验猜**。
- **渐变方向要提取 `gradient.from/to/type`**：Sketch 渐变 fill 有 `from`/`to`（局部坐标，可推导方向，dy=0→水平、dx=0→垂直）和 `type`（0=linear 1=radial）。只取 stops 会丢失方向——曾把标题栏渐变方向当"猜"。线性渐变 CSS 写法由 from/to 推导角度。
- **border `lineAlignment`（inside/center/outside）**：sketch 边框有对齐字段（60 inside / 2 center 常见）；inside 在 border-box 下视觉一致，center 需注意（描边两侧各半）。
- **文本附加属性**：`fontWeight`（数值 400/500/700，比 fontType 字符串精确）、`verticalAlignment`、`underline`、`linethrough`、`lineSpacing` 均需提取。
- **transform/rotation 必须提取（frame 是旋转后包围盒）**：sketch 旋转节点 frame 是旋转后 bbox，会误导还原（如 9×9 方块旋转 45° 变菱形，bbox 是 13.41×13.41）。`extract_layers.py` 已从 transform 2x2 线性部分推导 `rotationDeg`（θ=atan2(b,a)）。实例：组织机构标题双色图标（矩形210/211 rotationDeg=45 菱形）、收起按钮箭头（-135/-45）、下拉/返回箭头（180 翻转）。**看到 rotationDeg≠0 必须按旋转实现（CSS transform: rotate），不能按 bbox 画成矩形**。
- **sharedStyle 是设计规范色值命名**（如 `填充/Primary2 #0076BC`、`填充/Primary 6 #E9F4FF`、`填充/BLACK 20% #333`、`填充/blue gray1`）——与 fills 同源，可作色值来源注释/验证。
- **无影响的字段（已验证，无需提）**：节点级 `radius`（仅 artboard 自身 0 值，真圆角在 paths[].radius）、`style.blurs`（0 个非空）、`blendMode`（全 0）、`text.value`（与 style.content 全等）、`text.styles` 多段（全单段）、`paths.booleanOperation/subpaths`（0）、`realFrame`（与 frame 差异仅旋转节点，transform 已覆盖）、fill/border/shadow 各自 `opacity`（全 1）、`visible=false` 节点（0 个）、`style.isEnabled`（全 true）、symbolInstence 的 symbolId/overrides（无）、text.styles[0] 与 text.style（仅 length/to 段落范围不同，字体/颜色一致）。
- **提取脚本抽验清单（改完 extract_layers.py 必须跑一遍）**：①文本 color 缺失数=0（曾 58/58 全丢）；②渐变节点含 from/to/gradientType；③border 含 lineAlignment；④阴影含 inset；⑤rotationDeg≠0 的节点列出核对；⑥随机抽 1 文本对比原始 sketch 的 style.color/fontWeight。
- 缓存位置：`<你的项目缓存目录>/design-data/`（sketch.json / layers.json / 渲染 png）。
- 切图(图标) `lanhu_get_design_slices` 依赖设计师在蓝湖标 slice；`total_slices:0` 表示未标，等设计师标记后拉真图，不要用 SVG/emoji 凑。
- 内容区/卡片背景、边框等"视觉形状"在标注模式里不存在（合进整图），**必须从 sketch 树 fills/borders 读**（实例：内容区底 #F6F9FE、左面板右缘 1px #E0E0E0 曾漏画/误判四边）。
- 1920×1080 画布坐标换算到响应式 flex 布局时，用组件容器 frame 的起点/宽度推间距，不要直接用文字图层坐标。
- **别把 `frame.left` 直接翻成固定左偏移 / `padding-left`**：设计稿画布宽度 ≠ 实际 APP 视口宽度。使用 `frame.left` 前，先算 `(artboard.width - frame.left - frame.width)`。若左右空白接近（如 242 vs 218），优先实现为 `max-width + margin: 0 auto` 居中；只有明显对应真实侧边栏/出血区时才用固定偏移。实例：配置项目内容区 `容器3698` 在 1920 画布中 left=242、width=1460，曾被误写成 `padding-left: 242px`，实际应居中。


## 辅助工具（MCP + CLI，均调用同一套 lanhu/tools）

除了手动读 JSON，现在可以直接用工具消费 layers.json：

### 1. 布局意图分析 `lanhu_analyze_layout` / `layout_intent.py`

在把 `frame.left` 转成 CSS 前，先跑一遍，避免把该居中的内容区做成 `padding-left: 242px`。

- MCP: `lanhu_analyze_layout(layers_path, container_name)`
 - CLI: `python scripts/layout_intent.py <layers.json> [容器名]`
- 输出: `{artboard, container, margins: {left, right, top}, intent, css_recommendation}`
- 决策规则:
  - 左右空白差 ≤ 24px → `center` → `max-width + margin: 0 auto`
  - 宽度接近满屏 → `full-width` → `width: 100% + padding`
  - 其余 → `fixed-left` → `margin-left + width`

### 2. 页面规格摘要 `lanhu_summarize_page` / `summarize_page.py`

快速拿到一个页面的“取值溯源表”输入：卡片、输入框、按钮、开关、图标、字体分组。

- MCP: `lanhu_summarize_page(layers_path, page_name)`
 - CLI: `python scripts/summarize_page.py <layers.json> [page_name]`
- 输出字段: `page / layout / cards / inputs / buttons / switches / icons / text_styles`
- 用法：先扫 `text_styles` 和 `cards` 建立全局样式锚点，再逐块细化。

### 3. 图标自动裁剪 `lanhu_crop_icons` / `crop_icons.py`

设计师未标 slice 时，从蓝湖渲染图按 layers.json 的 frame 自动裁剪图标。

- MCP: `lanhu_crop_icons(layers_path, png_path, output_dir, name_map_json, fmt='webp')`
- CLI: `python scripts/crop_icons.py <layers.json> <render.png> <out_dir> [name_map.json] [webp|png]`
- 渲染图通常是 2x（如 3840×2160），工具会自动按 `png.width / artboard.width` 缩放坐标。
- 默认 `webp`；WebP 保存失败时自动回退 `png`。
- 命名映射 `name_map.json` 示例：`{"icon_Bridge": "icon-bridge"}`。

### 推荐流水线（新版）

```
get_sketch_json
    → scripts/extract_layers.py
    → scripts/verify_layers.py
    → scripts/layout_intent.py（先确认居中/左对齐/全宽）
    → scripts/summarize_page.py（拿页面规格）
    → scripts/crop_icons.py（导图标）
    → 人工写 Vue 组件（数值来自 layer_annotations，禁止截图估算）
```

## 还原验收 checklist（每个区域完成后逐项勾选）

按下面的顺序自查，任何一项不确定就回到数据核对，不要凭视觉判断：

- [ ] **数据源**：本区域所有取值来自 `sketch_json`/`layers.json`，没用 analyze 散件
- [ ] **结构盘点**：打印过该区域整棵容器层级（父→子 name+frame+fill+border），容器边界明确
- [ ] **逐图核对**：本页面每个 tab/状态的设计图都独立核对过容器样式（尤其 border/背景），没把一张图的结论推断到另一张图
- [ ] **间距归类**：每个间距已按决策表归到正确层级——"一致"用父 padding/gap、"个别"用子 margin；垂直间距优先 padding/gap
- [ ] **影响面**：改过父级样式（padding/width/border）时，逐个确认其子元素都适用（尤其"收窄"改动）
- [ ] **背景/渐变**：从 `style.fills` 读（含渐变 stops），没用像素采样取色；被覆盖层（如 3670 被面板盖住）不误当可见底色
- [ ] **边框**：`style.borders` 读了 thickness+color；**可见边**用 1px 像素扫描确认过（path 描边≠四边）
- [ ] **圆角**：从 `paths[].radius` 读（不是 node.radius），蓝湖网页标注可交叉核对
- [ ] **字体**：font name/size/weight/letterSpacing/align 都设置（如 tab 字距 active 4.5%/inactive 1.8%）
- [ ] **阴影**：`style.shadows` 读了 offset/blur/spread/color
- [ ] **切图**：图标若为占位（设计师未标 slice），代码注释已标注"待切图"，没造假
- [ ] **组件复用**：优先复用了 Element Plus / BaseDialog / IconSvg / c6-* / userManagement 样式锚点，没重复造轮子；复用后已按设计稿覆盖样式
- [ ] **布局**：flex 实现，无绝对定位堆布局（浮层控件如收起按钮除外）
- [ ] **静态校验**：ESLint 通过（仅允许 index.vue 历史命名告警）


## Vue 3 还原输出规范（从 lanhu-vue-plan 合并，已修正数据源）

以下规则仅适用于目标技术栈为 **Vue 3 + Element Plus** 且数据已按上面流程从 `get_sketch_json` → `extract_layers.py` 取出的场景。

### 1. 文件格式

- 默认产出 **Vue 3 单文件组件**（SFC）：`<template>` + `<script setup lang="ts">` + `<style scoped lang="scss">`。
- 禁止输出 React / RN / Flutter / XML / Compose / Tailwind / Less / CSS-in-JS，除非用户显式要求。

### 2. 数据读取优先级（硬）

| 属性 | 来源字段 | 禁止来源 |
|------|---------|---------|
| 坐标/尺寸 | `frame.left/top/width/height` | 绝对定位 div 坐标 |
| 背景/渐变 | `style.fills`（含 stops） | PNG 像素采样 |
| 边框 | `style.borders` | 截图目测 |
| 圆角 | `paths[].radius`（topLeft/topRight/bottomLeft/bottomRight） | `node.radius` / 截图 |
| 阴影 | `style.shadows` | 截图估算 |
| 字体 | `text.font/name/size/letterSpacing/align/color` | 截图目测 |
| 间距 | 子层 `frame` 差值（如 child.left - parent.left = padding） | 标注模式的 measurements |

### 3. 布局与定位

- 主信息流必须用 **flex**；仅在角标、浮层、重叠装饰、悬浮手势等场景允许 `position: absolute`。
- 页面根节点优先 `min-height: 100vh`。
- 主内容区优先 `max-width` + `margin: 0 auto` 控制版心。
- **禁止整页 `transform: scale(...)`**。
- 大屏：居中主栏 + 最大宽度约束；横屏：重排容器，不缩放。
- 滚动容器：只要垂直内容有超出风险，优先正常文档流或局部滚动；禁止把底部按钮写死到视口外。
- 移动 H5 吸底区域必须补 `env(safe-area-inset-bottom)`。

### 4. 资源与切图

- 所有切图/图标统一落盘：`src/assets/lanhu/<screen>/`。
- 命名语义化，例如：`ic-close.png`、`bg-card.png`、`btn-save.webp`。
- 默认格式 `webp`；透明或质量异常可回退 `png`，在资源清单标注原因。
- **icon / 复杂图形优先使用 `lanhu_get_design_slices` 返回的真实切图**，禁止用 CSS/SVG/emoji 手画近似版，除非设计师明确未标 slice 且图形是“纯色填充的基础几何形”。
- 常规资源使用 `import` 或 `new URL(..., import.meta.url).href`。

### 5. 文本与样式

- 必须保留文本层级、强调态、弱化态、删除线、换行与截断策略。
- 长文本必须给出多行截断或换行策略；辅助态不得静默省略。
- 颜色用 sketch 树里的 `text.color` 或 `style.fills` 的 rgba()，禁止 PNG 采样取色。
- 字距直接读取 `text.letterSpacing`，写到 CSS `letter-spacing`。**Sketch 的 `PERCENT` 单位必须用 em 表达（如 4.5% → `0.045em`、0.9% → `0.009em`），禁止直接写 CSS 百分比字面量 `letter-spacing: 4.5%`**——CSS 百分比 letter-spacing 属 CSS Text Level 4（Chrome 114+/Safari 17+/FF 125+），老环境静默失效；em 相对自身字号，语义与 PERCENT 完全一致且兼容所有浏览器。
- 禁止为单个元素创建额外 CSS class；完全相同字体属性在同一界面出现 ≥2 次才允许抽成共享 class。

### 6. 输出结构（可选）

复杂页面建议按以下四段输出，保持可追溯：

- A) 审计区：数据源、image_id、来源模式（`sketch_primary`）、关键尺寸来源。
- B) 规格表：组件/层级、frame、fills、borders、圆角、阴影、字体、资源策略。
- C) Vue SFC 代码。
- D) 资源清单：文件路径、格式、来源、是否使用原生绘制。

### 7. 禁止项

- 禁止用 `lanhu_get_ai_analyze_design_result` 或 `lanhu_get_design_annotations` 的坐标/尺寸做像素级还原。
- 禁止用 PNG 像素采样取色、测距、测圆角。
- 禁止用 `"看起来差不多"`、`"大约"` 等估算替代 sketch 树数值。

### 8. 组件复用原则（项目有现成组件时优先复用）

**默认倾向复用**：设计稿元素能映射到 Element Plus 或项目现有组件/样式资产时，优先复用并覆盖样式，不新造轮子。

**本项目现成资产清单（先用 grep 查证再决定）**：
- Element Plus 组件：`el-table`（用 CSS 变量 `--el-table-*` 覆盖表头/行高/边框色）、`el-tree`（`indent`/`node-content` deep 覆盖行高/选中态）、`el-dropdown`、`el-button`（覆盖尺寸/圆角/色）、`el-checkbox`（deep `__inner` 覆盖 16px/圆角）、`el-pagination`、`el-form`/`el-input`。
- 项目自定义组件：`@/components/dialogCommon/BaseDialog.vue`（弹窗）、`@/components/knowledgeLib/searchForm.vue`/`baseForm.vue`（搜索表单+FormItem 类型）、`IconSvg`（按 name 取图标，如 `userManagement-folder`）。
- 样式类资产：`c6-*` 系列（`c6-table-container`、`c6-action-btn`、`c6-el-button`/`c6-cancel-btn`/`c6-confirm-btn`、`c6-img-prefix-title` 标题前缀 icon）。
- 页面样式锚点：`views/userManagement/UserList.vue`（`.user-list-page/.layout-container/.left-panel/.right-panel/.org-tree-panel/.user-table-panel/.section-title/.action-bar/.pagination-bar`）、`RoleManagement.vue`、`components/RolePermissions.vue`（权限树）、`RoleUsers.vue`（关联表格）。

**执行规则**：
1. 动手前先 grep 项目现有组件/类名，有直接对应的就复用；复用方式 = 组件/props/CSS 变量/deep 覆盖，对齐设计稿数值。
2. 同一视觉模式（如卡片面板、弹窗、动作按钮）与现有页面一致时，copy 现有类名结构，保持全站视觉统一。
3. **不硬凑**：现成组件与设计稿结构差异过大（如自定义复杂表格、特殊树形）时可自写，但要在输出里说明"为何不复用"。
4. 复用≠不改样式：复用的组件仍必须按设计稿数值覆盖（表格行高/表头底色/圆角/边框），不能直接沿用默认样式。
- 禁止忽略树层级自行猜测父子关系。
