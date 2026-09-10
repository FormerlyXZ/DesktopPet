# DesktopPet - Windows 可交互式桌宠

## 项目简介
Windows 桌面宠物应用，使用 Python + PySide6 开发。支持两种角色类型：PNG 帧动画角色（默认服装）和 GIF 动图角色（Q版高木同学）。透明无边框置顶窗口，支持鼠标悬停/点击交互，可拖拽移动，带侧边气泡面板和设置窗口。

## 技术栈
- Python 3.10+
- PySide6 (Qt for Python)
- pynput (全局键盘/鼠标监听)
- 打包工具：PyInstaller

## 关键约束
- PNG 动画帧比例：9:16（竖长形），窗口自动适配
- PNG 每个动画预设时长：5秒
- GIF 动画使用 QMovie 原生播放，遵循 GIF 自身帧间隔
- 窗口行为：置顶 + 透明区域鼠标穿透
- 交互区域：仅人物实体部分响应鼠标
- **默认服装行为不可改动**（悬停=挥手、点击=气泡、拖拽=移动）

---

## 角色系统

项目支持两种角色类型，通过策略模式共存：

| 角色 | 类型 | 播放引擎 | 素材位置 |
|------|------|----------|----------|
| 默认服装 | PNG 帧序列 | AnimationEngine (QTimer) | `assets/默认服装/{动作名}/` |
| Q版高木同学 | GIF 动图 | QMovie | `素材库/高木同学Q版gif/` |

**CharacterController 抽象接口**（`src/character_base.py`）：
- `PngCharacter`（`src/png_character.py`）包装 AnimationEngine，零改动适配
- `GifCharacter`（`src/gif_character.py`）包装 QMovie，含交互状态机 + 行为检测 + AFK

---

## 项目文档 (docs/)

### 桌宠核心
| 文件 | 用途 |
|------|------|
| [01-需求规格.md](docs/01-需求规格.md) | 完整功能需求列表（含 Q版） |
| [02-技术方案.md](docs/02-技术方案.md) | 技术选型与架构设计（含策略模式、GIF方案） |
| [03-设计规范.md](docs/03-设计规范.md) | UI设计规范（含 Q版设置页） |
| [04-开发步骤.md](docs/04-开发步骤.md) | 分阶段执行步骤（含 Q版阶段） |
| [05-动画制作规范.md](docs/05-动画制作规范.md) | PNG/GIF 素材制作标准 |

### 历史粘贴板
| 文件 | 用途 |
|------|------|
| [01-需求规格.md](docs/clipboard/01-需求规格.md) | 粘贴板功能需求 |
| [02-技术方案.md](docs/clipboard/02-技术方案.md) | 粘贴板架构、存储方案、数据流 |
| [03-设计规范.md](docs/clipboard/03-设计规范.md) | 粘贴板窗口 UI 规范（配色、布局、交互） |
| [04-开发步骤.md](docs/clipboard/04-开发步骤.md) | 粘贴板分阶段开发步骤 |

### 养成高木同学（Nurture）
> **实现进行中。A~E 已完成（含实机验收，暂停点全部放行）；F、G 代码完成、实机验收待做；H 未开始。**
> 实现前请先读 `docs/nurture/02-技术方案.md` 第 4.8 节（悬停宽限期）与 4.9 节（角色接口扩展）。
> `src/pet_window.py` **已经改过了**（阶段 C），再动它之前务必重读 4.8 节与回归红线。

| 文件 | 用途 |
|------|------|
| [01-需求规格.md](docs/nurture/01-需求规格.md) | 养成需求：数值、食物获取、悬停菜单、喂食流程、对话气泡、行为感知 |
| [02-技术方案.md](docs/nurture/02-技术方案.md) | 架构分层、模块设计、ctypes 前台感知、与现有代码的耦合面清单 |
| [03-设计规范.md](docs/nurture/03-设计规范.md) | **全局 UI 美术规范**（暖粉奶白手绘风；2026-09-10 起不再只管养成系统） |
| [04-开发步骤.md](docs/nurture/04-开发步骤.md) | 分 8 阶段（A~H）开发步骤与暂停点 |

**术语约定（务必遵守，避免与现有命名混淆）**：

| 词 | 含义 |
|----|------|
| 「气泡面板」/ `BubblePanel` | 左键功能菜单、右键系统菜单。**名字不变**（文档与代码里都别改成"菜单面板"之类）。<br>2026-09-10 全局换肤后**内部实现改成了全自绘**（详见 `docs/03-设计规范.md` 第 2 节） |
| 「对话气泡」/ `SpeechBubble` | 人物头顶说话框。文档中一律写全「对话气泡」，**不要简称"气泡"** |

---

## 全局 UI 主题（2026-09-10 起）

**整个应用的界面统一成"暖粉奶白手绘风"**（原本只有养成系统是这套，其余是冷蓝磨砂玻璃）。

| 事项 | 去哪看 |
|------|--------|
| 色板与笔触的**唯一来源** | `src/ui_theme.py`（`nurture_icons` 只做转出，四个既有组件因此没动过） |
| 标准控件的配色 | `ui_theme.app_stylesheet()`（`SettingsWindow` 设在自己身上，子控件继承） |
| 规范全文 | `docs/nurture/03-设计规范.md`（已升级为**全局**规范） |
| 面板 / 设置窗口的具体规格 | `docs/03-设计规范.md` 第 2、3 节 |

> **改主题的正确姿势**：改 `ui_theme.py` 的色板常量或 `paint_*` 函数，别在组件里写死色值 ——
> `tests/test_nurture_icons.py::test_new_ui_files_avoid_forbidden_colors` 会扫描全部 UI 文件源码，
> 发现冷蓝色（或写死的旧色）就报错。

**工作前必读**：`docs/03-设计规范.md` 和 `docs/04-开发步骤.md`

---

## 开发日志 (devlog/)

每次开发会话在 `devlog/` 下记录当日工作：
- 文件命名：`YYYY-MM-DD.md`
- 内容格式：完成事项（✓）、待办事项（☐）、问题记录、核心文件表
- 会话开始时检查当日日志文件是否存在，不存在则创建
- 每完成一个阶段后更新日志

---

## 源代码结构 (src/)

### 核心窗口
| 文件 | 职责 |
|------|------|
| `pet_window.py` | 桌宠主窗口（透明、置顶、无边框），委托 CharacterController |
| `bubble_panel.py` | 左键功能面板 / 右键系统面板。**全自绘**（奶白纸片 + 2px 暖棕描边 + 20px 圆角 + 暖色投影；行 = 30px 圆形矢量图标 + 文案 + 可勾选项的圆形指示）。对外契约（`item_clicked` / `popup_at` / `show_at` / `set_item_checked`）与旧版一致 |
| `settings_window.py` | 设置窗口（QStackedWidget: PNG页 / Q版页）。自绘外壳 + 纸片分组 + `ui_theme.app_stylesheet()` |
| `ui_theme.py` | **全局主题的唯一定义**：色板、笔触（`pen`/`rounded_path`/`paint_paper`/`paint_card`/`paint_row`/`paint_circle`/`paint_badge`）、标准控件样式表 `app_stylesheet()` |
| `panel_animator.py` | 面板滑入淡出/滑出淡出过渡动画 |

### 角色系统（策略模式）
| 文件 | 职责 |
|------|------|
| `character_base.py` | CharacterController 抽象基类（接口 + 信号定义） |
| `png_character.py` | PngCharacter——包装 AnimationEngine，不改动原有代码 |
| `animation.py` | PNG 帧动画引擎（QTimer 驱动，5秒循环） |
| `gif_registry.py` | GIF 注册表——扫描素材库，正则解析文件名提取动作名 |
| `gif_character.py` | GifCharacter——QMovie播放 + 交互状态机 + 启动序列 + AFK |

### 行为检测
| 文件 | 职责 |
|------|------|
| `input_monitor.py` | QThread + pynput 全局键盘/鼠标监听 |
| `audio_monitor.py` | QTimer + ctypes Windows Core Audio API 音频检测 |

### 设置
| 文件 | 职责 |
|------|------|
| `config.py` | 配置管理（JSON 读写、deep_merge、开机自启注册表） |
| `gif_settings_page.py` | Q版专用设置页 UI（序列编辑、映射、AFK池）。**无内联样式**，配色全部继承 `SettingsWindow` 的主题样式表 |

### 历史粘贴板
| 文件 | 职责 |
|------|------|
| `clipboard_store.py` | SQLite 存储后端（建表、CRUD、搜索、过期清理） |
| `clipboard_monitor.py` | QTimer + QClipboard 轮询检测剪贴板变化 |
| `clipboard_window.py` | 历史窗口 UI（搜索栏、时间筛选、卡片列表、置顶/删除），正常窗口逻辑（任务栏+鼠标缩放+最小化+专属图标）；⚙ 设置对话框（背景样式+壁纸库缩略图管理+字体大小+自动清理） |

### 养成系统（Nurture，阶段 A~E 完成并实机验收，F/G 代码完成）
| 文件 | 职责 |
|------|------|
| `nurture_model.py` | **规则层纯函数**（不 import PySide6）：跨天/连签/签到产出/好感度上限/等级解锁/动画兜底链/兑换换算/节日命中/档位归并/语气七禁区/前台分类词表（`APP_KEYS`） |
| `nurture_store.py` | 数据层：`data/nurture.json` 原子写 + 2s 防抖 + 坏档隔离改名 + 跨天重置。**构造时不读盘，必须显式 `load()`**；`flags` 只认 `FLAG_DEFAULTS` 里的键 |
| `dialogue.py` | 台词库：权重抽取 + 最近 5 条防重复 + 占位符 + `min_level`/`tease` 过滤（**不依赖 Qt**） |
| `nurture_icons.py` | **全应用共用的矢量图标库**（27 个：9 悬停菜单 + 5 左右键面板 + 13 食物礼物）+ 三级降级链（用户 PNG → 内置矢量 → emoji/首字）+ 缓存。色板从这里**转出**（真正的定义在 `ui_theme.py`） |
| `hover_menu.py` | 悬停菜单：圆形按钮条（自绘）+ 落位（**恒定贴人物下方居中**→极窄屏竖排→夹紧；提示条恒在胶囊下方）+ **不抢焦点** |
| `nurture_panel.py` | 养成面板：三页（食物/礼物/状态）**全自绘**（卡片网格 + 心形进度条）+ 落位（**贴人物左侧**→翻右→夹紧）+ 不抢焦点 |
| `nurture_controller.py` | 业务层：喂食闭环 `try_send()`（九个结果码）、**获取途径**（签到四分支 + 陪伴/打字兑换 + 四种彩蛋，每次心跳结算）、菜单可用性表/角标、面板数据刷新、**台词调度**（冷却 / 全屏静默 / 90s 最小间隔 / 专注与免打扰 / tease 额度）、**前台分类入口**。**不含任何几何与绘制** |
| `speech_bubble.py` | 对话气泡：自绘「圆角矩形 + 尾巴合并路径」+ 像素级断行（最多 4 行）+ 贴头顶 14% 落位（越界翻下）+ **绝不抢焦点、鼠标完全穿透** |
| `window_monitor.py` | 前台窗口感知（阶段 G）：ctypes 探针（进程名 → 分类）+ 全屏几何判定 + `QTimer(1000ms)` 边沿触发 + `create_monitor()` 唯一创建入口。**默认关闭 ⇒ 连对象都不创建**；只发归一化分类，不读窗口标题、不打印、不写文件 |

> `src/pet_window.py` 已按阶段 C/D/E/F 改造：悬停延迟计时、350ms 收起宽限期、面板仲裁器
> （`_popups()` / `hide_all_popups()` / `any_popup_visible()`，含 `"nurture"`）、单击裁定
> （**2026-09-10 修订**：悬停菜单不再"吃掉"单击，见 01 文档 5.4.1）、
> 菜单按钮路由到 `NurtureController`、对话气泡（含拖动跟随与静音时段）、
> 托盘菜单的「今日签到」+「养成状态」、菜单弹出时的签到提醒。
> **再动它之前必读 `docs/nurture/02-技术方案.md` 4.8 节。**
>
> **对话气泡刻意不进仲裁器**：03 规范第 7 节的互斥矩阵里它与所有弹层「可共存」。
>
> `src/gif_character.py` 已加养成锁：`_locked` + `play_action()` / `is_busy()` / `release_lock()` /
> `handle_hover_menu_shown()`，**11 个交互入口**都有 `if self._locked: return`。
>
> 计划中但**尚未创建**：`nurture_settings_page.py`（阶段 H），见 `docs/nurture/04-开发步骤.md`。

### 配置素材（`assets/nurture/`，用户可编辑）
| 文件 | 内容 |
|------|------|
| `items.json` | 13 项食物/礼物：`kind` / `tier` / `anim`（GIF 动作名）/ `icon_key` / 专属台词 |
| `checkin.json` | 签到产出表与连签里程碑（数值可调，规则不在此处） |
| `levels.json` | 好感度阈值 50/120/250/450/700 + 称号 + 各级解锁标识 |
| `events.json` | 节日/纪念日 → 产出物品 + 专属台词场景 |
| `apps.json` | **阶段 G**：前台感知的查表文件 —— `categories`（5 个分类 × 219 条进程名）+ `ignore`（「不要感知」黑名单 26 条）+ `_说明`。命中黑名单返回 `unknown`，与"不认识的应用"无法区分 |
| `dialogues/*.json` | 每个场景一个文件，现有 **37 个**：阶段 B/E 的 17 个 + 阶段 F 的 15 个（`checkin_*` / `inventory_full` / `convert_*` / `egg_*` / `first_run` / `event_*`）+ 阶段 G 的 5 个（`detect_app_{code,browser,game,meeting,media}`）（`feed_full` / `feed_fav` / `feed_empty` / `checkin_done` 等另有 `dialogue.py` 里的内置兜底）。改完调 `DialogueLibrary.reload()` 即生效 |
| `icons/README.txt` | 自备图标 PNG 的命名与规格说明 |

> **`data/nurture.json` 与 `config.json` 刻意分离**：状态（好感度/库存/连签）走前者，
> 设置走后者。后者用 `deep_merge` 平滑升级，前者是高频变动的运行时数据。

**看内置图标长什么样**（改图标前后都该跑）：

```bash
python -m src.nurture_icons _icons_preview.png
```

出两张图：44px 带标签 + **20px 真实尺寸无标签**。第二张是判断"小尺寸下认不认得出"的唯一依据。

---

## 单元测试 (tests/)

纯 `unittest`，**不引入 pytest**。项目根目录运行：

```bash
python -m unittest discover -s tests -t . -v
```

| 文件 | 覆盖 |
|------|------|
| `test_nurture_model.py` | 数值规则全部分支（含表驱动边界） |
| `test_nurture_store.py` | 原子写 / 防抖 / 坏档隔离 / 跨天重置 / 脏值降级 |
| `test_nurture_dialogue.py` | 台词库：权重分布 / 防重复 / 占位符 / `tease` 整组剔除 / 坏文件与空池降级 |
| `test_nurture_icons.py` | 27 个图标渲染 / 三级降级优先级 / 缓存键 / 画法异常降级 / **色板单一来源**（转出值与 `ui_theme` 逐字相同）/ **冷蓝色源码扫描（覆盖全部 UI 文件）** |
| `test_nurture_assets.py` | `assets/nurture/*.json` **跨文件引用一致性**（动画名是否真在素材库、节日产出名是否存在、台词字数/标点/称呼与"不评判"黑名单句式）+ **阶段 G 的 `apps.json`**（分类只含 `APP_KEYS`、每条都是文件名不是路径、同名不跨分类、黑名单与分类不矛盾、密码管理器默认在列、每条都能被真加载器查回自己分类） |
| `test_nurture_hover_menu.py` | 悬停菜单：按钮尺寸公式 / 横竖排几何 / 落位（**恒贴下方·不压人物**·夹紧·副屏·极窄屏竖排）/ 提示条恒在胶囊下方 / 入场从下方滑上 / 窗口标志不抢焦点 / 点击信号 / 三语文案 |
| `test_nurture_pet_hover.py` | `PetWindow` 悬停集成：**宽限期状态机全部分支** / 抑制条件 / 拖拽抑制 / 单击·右键裁定（**含「菜单开着时单击仍弹功能面板」**，一条直接调裁定函数、一条投递真实鼠标事件走完整条路）/ 面板仲裁器 |
| `test_nurture_character_lock.py` | 养成锁：**11 个交互入口全堵** / 动画播完自动解锁 / 连喂 10 次不泄漏 / 真实 GIF 播放 / `is_busy()` 三态 / 菜单弹出钩子 |
| `test_nurture_panel.py` | 面板：**三列装得下** / 卡片不重叠不出界 / 高度跨页稳定 / 落位（贴左·翻右·不压人物）/ 脏数据降级 / 点击信号 / 三页渲染 |
| `test_nurture_controller.py` | 控制器：**九个结果码各一个类** / 四级兜底链 / 菜单可用性表 / 语气禁区 / 素材热重载 |
| `test_nurture_wiring.py` | 接线：菜单→面板→点卡片→扣库存+播动画+出台词 / 面板进仲裁器 / 切角色解绑 / 按键·音频·长悬停触发台词 / **没接 controller 时与阶段 C 行为一致** / **阶段 F 三个入口**（菜单弹出的签到提醒 · 托盘「今日签到」「养成状态」） |
| `test_nurture_speech_bubble.py` | 对话气泡：像素级断行（4 行上限 / 省略号 / 中英混排）/ 落位（头顶 14%·翻转·夹紧·副屏）/ **尾巴真的画在主体外面** / **入场方向** / 异步收起用轮询 / 窗口标志（不抢焦点·鼠标穿透·不重写鼠标事件） |
| `test_nurture_rewards.py` | 获取途径（阶段 F）：签到六条分支（首签·连签·断签·**时间回退**·同日·开关）/ 库存满仍记账 / 一次点击只出一句 / 兑换的阈值·上限·零头·**同一份进度不重复发** / 进度落盘与重启恢复 / 整点彩蛋概率与日上限 / 长待机彩蛋每天一次 / 节日与生日 / flag 落盘 / 心跳优先级与跑 20 遍不重复发 |
| `test_nurture_window_monitor.py` | 前台感知（阶段 G）：分类与大小写、黑名单与 `unknown` 不可区分、`apps.json` 容错、全屏几何、边沿触发、**自己的窗口被排除**、读不到的 3 拍防抖、探针/接收方抛异常不打断轮询、启停重同步、`create_monitor` 五种开关组合、`main._start_foreground_monitor`（**默认关闭时连对象都不建**）、**源码级隐私扫描**（无取标题 API / 不打印 / 不写文件）。探针**全部注入假数据**，不依赖真实前台窗口 |
| `test_ui_theme.py` | 全局主题 + 左右键面板（2026-09-10 换肤新增）：色板与转出值一致 / 无冷蓝 / 不对称圆角四角差 ≤2px / 圆角路径容错 / 样式表覆盖各控件且**滚动视口透明** / 面板**可见矩形 vs 窗口**（`visible_rect` 与窗口差 2×MARGIN）/ 行高累加 / 宽度按文案夹紧 / `popup_at` 贴人物右侧·垂直居中·贴右边缘翻左 / `show_at` 一角对准光标且不出屏 / 勾选状态 / 点击信号（含"按下与松手不在同一行不发信号"）/ 三语文案无 emoji |

**每次改动 `src/nurture_*.py` / `src/dialogue.py` / `src/hover_menu.py` / `src/pet_window.py` /
`src/ui_theme.py` / `src/bubble_panel.py` / `src/settings_window.py` / `src/gif_settings_page.py` /
`assets/nurture/**` 后必须跑一遍。**
数值规则是唯一不能被 UI 掩盖的部分，这里错了后面全是错的。

> **写新 UI 测试的三条硬经验**（踩过）：
> 1. `hide_with_anim()` **和 `popup_at()` 的滑入**都是**异步**的（160~220ms 动画跑完才到位）。
>    断言"收起成功了吗 / 落到哪了"**不能**用固定 `qWait` 等 —— 实测约 20% 概率随机失败。
>    用 `wait_until(predicate)` 轮询等条件成立（`popup_at` 直接读 `x()` 会拿到动画起点，差 40px）。
> 2. `HoverMenu.under_mouse()` 读**真实全局光标位置**，会让结果取决于"跑测试的人鼠标在哪"。
>    测试里必须替换成可控桩，两个分支各测一次。
> 3. **别让测试依赖当前时间**：`_tease_allowed()` 会读当前小时，深夜禁区默认 23:00~07:00 ——
>    不显式关掉的话，"晚上 11 点之后跑全量"会冒出三个假失败（2026-09-10 23:01 实测）。
>    涉及 `tease` 的用例请在 `set_config()` 里带上 `mute_hours_start/end = 0`（零长度 = 无深夜时段）。

---

## 动画素材管理

### PNG 帧序列（默认服装）
- 源文件（ZIP）放在 `素材库/` 目录（用户维护）
- 解压后放入 `assets/{服装名}/{动作名}/` 目录
- 帧文件命名：`001.png` `002.png` ...（三位数字编号）
- 添加新动画：放入对应目录后重启程序即可

### GIF 动图（Q版）
- 源文件直接放入 `素材库/高木同学Q版gif/`
- 命名规范：`takagi_{动作名}_{时间戳}.gif`，程序自动提取动作名
- 添加新 GIF：放入目录后重启程序即可

---

## 开发工作流

1. 阅读 `docs/` 中相关规范文档
2. 按 `docs/04-开发步骤.md` 分阶段执行
3. **每阶段过后设暂停点**，验证通过后再推进下一阶段
4. 每步只改 1-2 个文件，保持可控
5. 默认服装行为不可引入回归
6. 更新 `devlog/` 日志
7. 不跨阶段开发，确保每阶段稳定后再推进

## Q版 交互状态机速查

```
INACTIVE → STARTUP(到达→加载→加油) → IDLE(加油循环) ⇄ INTERACTING
                                            ↕
                                       HOVER_IDLE(害羞)
```

| 触发 | 动画 | 备注 |
|------|------|------|
| 启动 | 到达→加载→加油 | 可自定义顺序 |
| 悬停 | 害羞 | 进入 HOVER_IDLE |
| 悬停3秒 | 问号 | 长悬停 |
| 单击 | 惊吓 | |
| 双击(400ms) | 生气→哭 | 两步链式，不可打断 |
| 按键 | 打字 | 全局键盘监听 |
| 音频播放 | 唱歌 | Windows 音频检测 |
| 静音 | 静音 | Windows 静音检测 |
| 面板按钮 | 点头 | |
| 关闭/不保存 | 摇头 | |
| AFK 30秒 | 随机池 | 之后每1-3分钟随机 |
