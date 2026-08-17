# Vue 3 输出规范（目标技术栈为 Vue 3 + Element Plus 时）

以下规则适用于目标技术栈为 **Vue 3 + Element Plus**、且数据已按 §4 流程从 `get_sketch_json` → `extract_layers.py` 取出的场景。

## 1 文件格式

- 默认产出 Vue 3 单文件组件（SFC）：`<template>` + `<script setup lang="ts">` + `<style scoped lang="scss">`。
- 禁止输出 React / RN / Flutter / XML / Compose / Tailwind / Less / CSS-in-JS，除非用户显式要求。

## 2 布局与定位

- 主信息流必须用 flex；仅在角标、浮层、重叠装饰、悬浮手势等场景允许 `position: absolute`。
- 页面根节点优先 `min-height: 100vh`；主内容区优先 `max-width` + `margin: 0 auto` 控制版心。
- 禁止整页 `transform: scale(...)`。
- 大屏：居中主栏 + 最大宽度约束；横屏：重排容器，不缩放。
- 滚动容器：只要垂直内容有超出风险，优先正常文档流或局部滚动；禁止把底部按钮写死到视口外。
- 移动 H5 吸底区域必须补 `env(safe-area-inset-bottom)`。

## 3 资源与切图

- 所有切图 / 图标统一落盘：`src/assets/lanhu/<screen>/`；命名语义化（如 `ic-close.png`、`bg-card.png`、`btn-save.webp`）。
- 默认格式 `webp`；透明或质量异常可回退 `png`，并在资源清单标注原因。
- icon / 复杂图形优先使用真实切图：设计师在蓝湖标的 slice 取真图；未标时用 `crop_icons.py` 从渲染图自动裁剪占位图。禁止用 CSS/SVG/emoji 手画近似版，除非图形是纯色填充的基础几何形。
- 常规资源使用 `import` 或 `new URL(..., import.meta.url).href`。

## 4 文本与样式

- 保留文本层级、强调态、弱化态、删除线、换行与截断策略；长文本必须给出多行截断或换行策略，辅助态不得静默省略。
- 颜色用 sketch 树里的 `text.color` 或 `style.fills` 的 rgba()，禁止 PNG 采样取色。
- 字距读取 `text.letterSpacing` 并写到 CSS `letter-spacing`。Sketch 的 `PERCENT` 单位必须用 em 表达（如 4.5% → `0.045em`、0.9% → `0.009em`），禁止写 CSS 百分比字面量——CSS 百分比 letter-spacing 属 CSS Text Level 4，老环境静默失效；em 相对自身字号，语义与 PERCENT 一致且兼容所有浏览器。
- 禁止为单个元素创建额外 CSS class；完全相同字体属性在同一界面出现 ≥2 次才允许抽成共享 class。

## 5 输出结构（可选）

复杂页面建议按四段输出，保持可追溯：

- A) 审计区：数据源、image_id、来源模式（`sketch_primary`）、关键尺寸来源。
- B) 规格表：组件 / 层级、frame、fills、borders、圆角、阴影、字体、资源策略。
- C) Vue SFC 代码。
- D) 资源清单：文件路径、格式、来源、是否使用原生绘制。

## 6 组件复用原则

**默认倾向复用**：设计稿元素能映射到目标技术栈 UI 库或项目现有组件 / 样式资产时，优先复用并覆盖样式，不新造轮子。

1. 动手前先检索目标项目现有组件 / 类名，有直接对应的就复用；复用方式为组件 / props / CSS 变量 / deep 覆盖，并对齐设计稿数值。
2. 同一视觉模式（卡片面板、弹窗、动作按钮等）与现有页面一致时，沿用现有类名结构，保持全站视觉统一。
3. 现成组件与设计稿结构差异过大（如自定义复杂表格、特殊树形）时可自写，但须在输出中说明不复用原因。
4. 复用的组件仍须按设计稿数值覆盖（表格行高 / 表头底色 / 圆角 / 边框），不能直接沿用默认样式。

