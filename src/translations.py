"""共享翻译字典——中/英/日 三语

2026-09-10 全局换肤时**清掉了所有 emoji 前缀与前导空格**：
旧版靠 "  📏  桌宠大小" 这种"emoji + 空格"做视觉（那是"直角矩形列表项 + emoji 前缀"时代的遗留），
新版把这些行换成了**纸片分组标题 + 自绘矢量图标**，再留 emoji 就成了"一个图标配一个 emoji"。
"""
TR = {
    # ── 设置窗口 ──
    "title":           {"zh": "设置",              "en": "Settings",              "ja": "設定"},
    "char_label":      {"zh": "角色:",             "en": "Character:",            "ja": "キャラクター:"},
    "char_png":        {"zh": "默认服装 (PNG)",     "en": "Default (PNG)",         "ja": "デフォルト (PNG)"},
    "char_gif":        {"zh": "Q版高木同学 (GIF)",  "en": "Chibi Takagi (GIF)",   "ja": "Q版高木さん (GIF)"},
    "size_label":      {"zh": "桌宠大小",          "en": "Pet Size",              "ja": "ペットサイズ"},
    "general_label":   {"zh": "通用设置",          "en": "General",               "ja": "一般設定"},
    "lang_label":      {"zh": "语言:",             "en": "Language:",             "ja": "言語:"},
    "auto_start_label":{"zh": "开机自启",          "en": "Start on Boot",         "ja": "起動時に開始"},
    "auto_on":         {"zh": "开",                "en": "ON",                    "ja": "オン"},
    "auto_off":        {"zh": "关",                "en": "OFF",                   "ja": "オフ"},
    "anim_label":      {"zh": "动画设置",          "en": "Animation",             "ja": "アニメーション設定"},
    "idle_label":      {"zh": "待机:",             "en": "Idle:",                 "ja": "待機:"},
    "hover_label":     {"zh": "悬停:",             "en": "Hover:",                "ja": "ホバー:"},
    "save_btn":        {"zh": "保存并退出",         "en": "Save && Exit",         "ja": "保存して終了"},
    "close_btn":       {"zh": "关闭",              "en": "Close",                 "ja": "閉じる"},
    "msgbox_title":    {"zh": "桌面宠物",           "en": "Desktop Pet",           "ja": "デスクトップペット"},
    "msgbox_text":     {"zh": "设置已修改，是否保存？", "en": "Settings have been modified. Save?", "ja": "設定が変更されました。保存しますか？"},

    # ── 气泡面板 ──
    # 2026-09-10 全局换肤：**去掉 emoji 前缀与前导空格**。
    # 旧版是"直角矩形文字条"，靠 "  📋  历史粘贴板" 这种 emoji + 空格做视觉；
    # 新版每行左侧是**自绘的圆形矢量图标**（`bubble_panel.ITEM_ICONS`），
    # 再留 emoji 就成了"一个图标配一个 emoji"。这几个键只有面板在用（托盘是 `tray_*`）。
    "bubble_settings":  {"zh": "设置",         "en": "Settings",        "ja": "設定"},
    "bubble_clipboard": {"zh": "历史粘贴板",   "en": "Clipboard",       "ja": "クリップボード"},
    "bubble_exit":      {"zh": "退出",         "en": "Exit",            "ja": "終了"},

    # ── 系统面板（右键）──
    "sys_topmost":       {"zh": "窗口置顶",     "en": "Always on Top",    "ja": "常に最前面"},
    "sys_desktop_level": {"zh": "桌面层级",     "en": "Desktop Level",    "ja": "デスクトップレベル"},
    "sys_minimize_tray": {"zh": "最小化到托盘", "en": "Minimize to Tray", "ja": "トレイに最小化"},

    # ── 托盘图标 ──
    "tray_show":      {"zh": "显示桌宠",   "en": "Show Pet",        "ja": "ペットを表示"},
    "tray_clipboard": {"zh": "历史粘贴板", "en": "Clipboard",       "ja": "クリップボード"},
    "tray_exit":      {"zh": "退出",       "en": "Exit",            "ja": "終了"},
    # 养成系统（阶段 F：托盘入口）。养成关闭 / 非 Q版 时这两项不显示
    "tray_checkin":        {"zh": "今日签到",   "en": "Daily Check-in",   "ja": "今日のチェックイン"},
    "tray_nurture_status": {"zh": "养成状态",   "en": "Nurture Status",   "ja": "育成の状態"},

    # ── GIF 设置页 ──
    "startup_group":   {"zh": "启动序列",           "en": "Startup Sequence",      "ja": "起動シーケンス"},
    "idle_group":      {"zh": "待机循环",           "en": "Idle Loop",             "ja": "待機ループ"},
    "behavior_group":  {"zh": "行为检测",           "en": "Behavior Detection",    "ja": "行動検出"},
    "mouse_group":     {"zh": "鼠标交互",           "en": "Mouse Interaction",     "ja": "マウス操作"},
    "afk_group":       {"zh": "AFK 随机播放",       "en": "AFK Random",            "ja": "AFKランダム"},
    "idle_action":     {"zh": "  待机动画:",         "en": "  Idle Action:",       "ja": "  待機アクション:"},
    "sleep_enable":    {"zh": "启用夜间睡眠待机 (23:00-24:00 准备 / 0:00-6:00 睡觉)", "en": "Enable Night Sleep (23:00-24:00 prep / 0:00-6:00 sleep)", "ja": "夜間睡眠を有効にする (23:00-24:00 準備 / 0:00-6:00 睡眠)"},
    "key_press":       {"zh": "按键打字",         "en": "Key Press",         "ja": "キー入力"},
    "audio_play":      {"zh": "音频播放",         "en": "Audio Play",        "ja": "オーディオ再生"},
    "audio_muted":     {"zh": "系统静音",         "en": "System Muted",      "ja": "システムミュート"},
    "hover_action":    {"zh": "  悬停:",             "en": "  Hover:",             "ja": "  ホバー:"},
    "long_hover":      {"zh": "  长悬停:",           "en": "  Long Hover:",        "ja": "  長押しホバー:"},
    "click_action":    {"zh": "  单击:",             "en": "  Click:",             "ja": "  クリック:"},
    "panel_button":    {"zh": "  面板按钮:",         "en": "  Panel Button:",      "ja": "  パネルボタン:"},
    "close_no_save":   {"zh": "  关闭/不保存:",      "en": "  Close/No Save:",     "ja": "  閉じる/保存しない:"},
    "dbl_click_seq":   {"zh": "  双击序列:",         "en": "  Double Click:",      "ja": "  ダブルクリック:"},
    "add_btn":         {"zh": "+ 添加",             "en": "+ Add",                 "ja": "+ 追加"},
    "remove_btn":      {"zh": "移除",               "en": "Remove",                "ja": "削除"},
    "afk_enable":      {"zh": "启用 AFK",           "en": "Enable AFK",            "ja": "AFKを有効にする"},
    "afk_timeout":     {"zh": "  空闲超时:",         "en": "  Idle Timeout:",      "ja": "  アイドルタイムアウト:"},
    "afk_interval":    {"zh": "  随机间隔:",         "en": "  Random Interval:",   "ja": "  ランダム間隔:"},
    "afk_pool":        {"zh": "  动画池:",           "en": "  Animation Pool:",    "ja": "  アニメーションプール:"},
    "seconds_suffix":  {"zh": " 秒",                "en": " sec",                  "ja": " 秒"},
}


def tr(key: str, lang: str) -> str:
    """获取翻译文本，找不到则返回 key 本身"""
    return TR.get(key, {}).get(lang, key)
