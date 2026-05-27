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
| `bubble_panel.py` | 侧边气泡面板（设置/退出入口） |
| `settings_window.py` | 设置窗口（QStackedWidget: PNG页 / Q版页） |
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
| `gif_settings_page.py` | Q版专用设置页 UI（序列编辑、映射、AFK池） |

### 历史粘贴板
| 文件 | 职责 |
|------|------|
| `clipboard_store.py` | SQLite 存储后端（建表、CRUD、搜索、过期清理） |
| `clipboard_monitor.py` | QTimer + QClipboard 轮询检测剪贴板变化 |
| `clipboard_window.py` | 历史窗口 UI（搜索栏、时间筛选、卡片列表、置顶/删除） |

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
