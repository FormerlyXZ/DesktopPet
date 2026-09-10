用户自备图标目录
================

把 PNG 放进这个目录，程序会**自动优先使用它**，覆盖 src/nurture_icons.py 里的内置矢量图标。
不需要改任何代码，重启程序生效。

文件名即图标键（icon_key），例如：

    feed.png          喂食          gift.png          送礼
    checkin.png       签到          heart.png         好感度
    chat.png          陪她聊聊      headpat.png       摸头
    settings.png      设置          close.png         关闭
    lock.png          未解锁

    bread.png         奶油面包      onigiri.png       饭团
    milk.png          牛奶          yakisoba.png      炒面面包
    shortcake.png     草莓蛋糕      icecream.png      冰淇淋
    candyapple.png    苹果糖        chocolate.png     巧克力
    birthday.png      生日蛋糕      easterbasket.png  复活节彩蛋篮
    redpacket.png     压岁钱        rose.png          玫瑰花
    festivalbag.png   夏日祭礼包

规格要求
--------

* 格式：PNG，**必须含 alpha 通道**（透明背景）
* 尺寸：建议 64×64（程序会缩放到 20px 使用）
* 风格：2px 暖棕描边（#8D6E63）+ 平涂粉/奶白填充，圆头线帽，**不要渐变、不要高光**
* 留白：四周留约 1~2px，避免描边被裁掉

缺失或文件名对不上也没关系 —— 程序按三级降级：
用户 PNG → 内置矢量图标 → emoji / 食物名首字。
**永远不会出现"没有图标"的空白。**

看内置图标长什么样：

    python -m src.nurture_icons _icons_preview.png

会生成两张对照图（44px 带标签、20px 真实尺寸），照着画风格最统一。
