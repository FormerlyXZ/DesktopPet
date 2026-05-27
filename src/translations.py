"""共享翻译字典——中/英/日 三语"""
TR = {
    # ── 设置窗口 ──
    "title":           {"zh": "设置",              "en": "Settings",              "ja": "設定"},
    "char_label":      {"zh": "角色:",             "en": "Character:",            "ja": "キャラクター:"},
    "char_png":        {"zh": "默认服装 (PNG)",     "en": "Default (PNG)",         "ja": "デフォルト (PNG)"},
    "char_gif":        {"zh": "Q版高木同学 (GIF)",  "en": "Chibi Takagi (GIF)",   "ja": "Q版高木さん (GIF)"},
    "size_label":      {"zh": "📏  桌宠大小",       "en": "📏  Pet Size",         "ja": "📏 ペットサイズ"},
    "general_label":   {"zh": "⚙  通用设置",       "en": "⚙  General",           "ja": "⚙ 一般設定"},
    "lang_label":      {"zh": "  语言:",            "en": "  Language:",           "ja": "  言語:"},
    "auto_start_label":{"zh": "  开机自启",         "en": "  Start on Boot",       "ja": "  起動時に開始"},
    "auto_on":         {"zh": "开",                "en": "ON",                    "ja": "オン"},
    "auto_off":        {"zh": "关",                "en": "OFF",                   "ja": "オフ"},
    "anim_label":      {"zh": "🎬  动画设置",       "en": "🎬  Animation",        "ja": "🎬 アニメーション設定"},
    "idle_label":      {"zh": "  待机:",            "en": "  Idle:",               "ja": "  待機:"},
    "hover_label":     {"zh": "  悬停:",            "en": "  Hover:",              "ja": "  ホバー:"},
    "save_btn":        {"zh": "保存并退出",         "en": "Save && Exit",         "ja": "保存して終了"},
    "close_btn":       {"zh": "关闭",              "en": "Close",                 "ja": "閉じる"},
    "msgbox_title":    {"zh": "桌面宠物",           "en": "Desktop Pet",           "ja": "デスクトップペット"},
    "msgbox_text":     {"zh": "设置已修改，是否保存？", "en": "Settings have been modified. Save?", "ja": "設定が変更されました。保存しますか？"},

    # ── 气泡面板 ──
    "bubble_settings":  {"zh": "  ⚙  设置",        "en": "  ⚙  Settings",        "ja": "  ⚙  設定"},
    "bubble_clipboard": {"zh": "  📋  历史粘贴板",  "en": "  📋  Clipboard",      "ja": "  📋  クリップボード"},
    "bubble_exit":      {"zh": "  🚪  退出",        "en": "  🚪  Exit",           "ja": "  🚪  終了"},

    # ── GIF 设置页 ──
    "startup_group":   {"zh": "启动序列",           "en": "Startup Sequence",      "ja": "起動シーケンス"},
    "idle_group":      {"zh": "待机循环",           "en": "Idle Loop",             "ja": "待機ループ"},
    "behavior_group":  {"zh": "行为检测",           "en": "Behavior Detection",    "ja": "行動検出"},
    "mouse_group":     {"zh": "鼠标交互",           "en": "Mouse Interaction",     "ja": "マウス操作"},
    "afk_group":       {"zh": "AFK 随机播放",       "en": "AFK Random",            "ja": "AFKランダム"},
    "idle_action":     {"zh": "  待机动画:",         "en": "  Idle Action:",       "ja": "  待機アクション:"},
    "key_press":       {"zh": "  按键打字:",         "en": "  Key Press:",         "ja": "  キー入力:"},
    "audio_play":      {"zh": "  音频播放:",         "en": "  Audio Play:",        "ja": "  オーディオ再生:"},
    "audio_muted":     {"zh": "  系统静音:",         "en": "  System Muted:",      "ja": "  システムミュート:"},
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
