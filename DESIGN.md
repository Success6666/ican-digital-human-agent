# ICAN Digital Human Console Design

## Direction

面向长时间使用的控制台。物理场景是：平台工程师在明亮办公室的桌面浏览器里，同时盯着一个实时数字人会话和几块诊断面板。视觉选择浅蓝灰工作区、白色内容面和一枚蓝色行动色，让状态和数据比装饰更突出。

## Color Tokens

使用 OKLCH 近似值，统一定义在 apps/web/src/shared/styles/theme.css。

- --canvas: oklch(0.965 0.018 250)，全局工作区背景
- --surface: oklch(0.995 0.004 250)，主要面板
- --surface-muted: oklch(0.975 0.012 250)，侧栏/次级区
- --ink: oklch(0.23 0.025 255)，标题与正文
- --ink-muted: oklch(0.50 0.035 255)，辅助说明
- --line: oklch(0.88 0.018 250)，分隔线
- --brand: oklch(0.59 0.19 258)，主操作与选中态
- --brand-soft: oklch(0.94 0.055 258)，浅蓝背景
- --success: oklch(0.66 0.15 157)，在线/成功
- --warning: oklch(0.76 0.15 76)，等待/提醒
- --danger: oklch(0.63 0.18 24)，异常/停止

颜色策略是 restrained：蓝色只承担操作、选中和关键状态；成功、警告和危险各自独立，避免一色统治所有页面。

## Typography

单一系统无衬线字体：Segoe UI Variable, PingFang SC, Microsoft YaHei, system-ui, sans-serif。正文 13px，辅助信息 11px，页面标题 22px，面板标题 15px，数据数字 20–28px。标题使用 text-wrap: balance，不使用负字距。

## Layout

- 桌面端：固定 248px 侧栏 + 可滚动主区；侧栏可收起至 72px。
- 主区最大宽度 1480px，内边距 24px；页面使用 12–16px 间距节奏。
- 首页是“数字人舞台 + 实时对话/链路”工作区；RAG、评测、审计和后台配置采用标题、指标、工具区、列表/图表的顺序。
- 卡片只用于重复数据和明确分组，圆角上限 12px；不在卡片内再套卡片。

## Components

- ConsoleShell：侧栏导航、折叠、移动端抽屉、账户和系统状态。
- PageHeader：页面标题、描述和右侧操作。
- MetricTile：指标标签、值、趋势/说明和语义色。
- AvatarStage：数字人运行时展示、音量波形、微表情状态和 Provider 信息。
- RealtimePanel：WebSocket 状态、转写、回应、录音与中断。
- WorkPanel：RAG/评测/审计/配置的统一平面容器。
- StatusPill：在线、处理中、降级、异常等状态，图标与文字并用。

## Interaction & Motion

交互反馈 150–220ms，采用 ease-out。导航折叠、面板切换、录音状态和进度条可以动；数据列表不做页面加载编排。prefers-reduced-motion: reduce 下关闭循环动画和滚动平滑。

## Data Visualization

图表只表达可行动的趋势：RAG 使用知识库列表与 7 日切片趋势占位，无数据时明确显示“接入数据后更新趋势”；评测使用质量条形摘要和延迟分段；审计使用事件类型分布。图表旁必须有文字标签和数值，颜色不作为唯一编码。

## Responsive Rules

820px 以下侧栏变为抽屉，首页从三列变为单列，指标改为两列/一列；表格允许横向滚动；所有按钮、输入和状态文本保持可读，不依赖视口缩放字体。
