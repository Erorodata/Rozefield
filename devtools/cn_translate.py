"""English text for CN-only strings ported into the Global client.

Order: exact translation memory from the Global client's own CN<->EN pairs, then hand-written
translations (MANUAL), then pattern templates. Output: translations.json {"<Sheet>:<ID>": [texts]}.
"""
import json, re, sys

CHAR = {'菲': 'Fei', '芙': 'Flavoure', '光': 'Hikari', '格': 'Gazetter', '诗': 'Shiika', '可': 'Cacao', '鸽': 'Dove',
        '伏': 'Kobushi', '寅': 'Yin', '橙': 'CC', '珂': 'Cho', '莉': 'Molly', '莫': 'Molly', '乌': 'Unna', '琳': 'Lynn',
        '丹': 'Deningha', '辉': 'Naoki', '莱': 'Lexy', '蕾': 'Connie', '妙': 'Miao', '梦': 'Moon', '蓝': 'Lacy', '爱': 'Aurele',
        '喜': 'Sixi', '洛': 'Lolomay', '奈': 'Nicy', '桃': 'Momo', '兔': 'Tutu', '宁': 'Meng', '芥': 'Sagel'}
ZODIAC = {'天蝎座': 'Scorpio', '射手座': 'Sagittarius', '摩蝎座': 'Capricorn', '摩羯座': 'Capricorn', '水瓶座': 'Aquarius',
          '双鱼座': 'Pisces', '白羊座': 'Aries', '金牛座': 'Taurus', '双子座': 'Gemini', '巨蟹座': 'Cancer'}
METAL = {'黄金': 'Gold', '白银': 'Silver', '黄铜': 'Bronze', '黑铁': 'Iron', '金': 'Gold', '银': 'Silver', '铜': 'Bronze', '铁': 'Iron'}
NUM = {'Ⅰ': 'I', 'Ⅱ': 'II', 'Ⅲ': 'III', 'Ⅳ': 'IV', 'Ⅴ': 'V', 'Ⅵ': 'VI', 'Ⅶ': 'VII', 'Ⅷ': 'VIII', 'Ⅸ': 'IX', 'Ⅹ': 'X'}
GLOSS = {  # longest first when applied
    '万圣': 'Halloween', '初冬': 'Early Winter', '雪境': 'Snowland', '新月': 'New Moon', '暖冬': 'Warm Winter', '迎春': 'Spring Welcome',
    '纯白': 'Pure White', '周年庆': 'Anniversary', '周年': 'Anniversary', '特惠': 'Special Offer', '糖果': 'Candy', '精选': 'Selection',
    '夜巡': 'Night Patrol', '酬宾': 'Thanks', '絮语': 'Whisper', '温暖': 'Warmth', '能量': 'Energy', '成长': 'Growth', '暖阳补给': 'Sunshine Supply',
    '焕彩': 'Radiance', '颂歌': 'Carol', '凝光': 'Glow', '寻踪补给': 'Trail Supply', '情谊': 'Friendship', '超值': 'Value',
    '补给': 'Supply', '接福': 'Good Fortune', '贺岁': 'New Year', '祈缘': 'Wish', '纳瑞': 'Blessing', '吉签': 'Lucky Draw',
    '丰年': 'Harvest', '心意': 'Heartfelt', '心动': 'Heartbeat', '邂逅': 'Encounter', '相遇': 'Meeting', '恋歌': 'Love Song',
    '礼包': 'Package', '神秘': 'Mystery', '大礼包': 'Grand Package', '古琴': 'Guqin', '恶魔之翼': "Demon's Wings",
    '星梦圆舞曲': 'Starry Dream Waltz', '动作': 'Emote',
}
MANUAL = {
    # ---- items: names
    '周年币': 'Anniversary Coin', '周年庆': 'Anniversary', '新手自选': 'Newcomer Selector', 'SR映像自选礼包I': 'SR Footage Selector Package I', '可在周年币商场兑换道具': 'Exchange for items in the Anniversary Coin Shop',
    '完成周年庆相关活动可获得周年币': 'Earned from Anniversary events',
    '风之结晶': 'Wind Crystal', '蕴含风之力量的特殊结晶，是制作部分玩法类家具所需的合成材料。':
        'A special crystal holding the power of wind. Material for crafting some gameplay furniture.',
    '在售货机的游戏厅商店用游戏积分兑换获得': "Exchanged with game points at the vending machine's arcade shop",
    '一枚可爱的小徽章，可以佩戴在名字旁边。': 'A cute little badge that can be worn next to your name.',
    '获得后可在时装界面中进行佩戴。': 'Once obtained, wear it from the Fashion screen.',
    '淘气徽章': 'Mischief Badge', '淘气挑战徽章': 'Mischief Challenge Badge', '满足徽章': 'Content Badge', '满足挑战徽章': 'Content Challenge Badge',
    '可怜徽章': 'Pitiful Badge', '可怜挑战徽章': 'Pitiful Challenge Badge', '耍酷徽章': 'Too Cool Badge', '耍酷挑战徽章': 'Too Cool Challenge Badge',
    '偷笑徽章': 'Giggle Badge', '偷笑挑战徽章（测试）': 'Giggle Challenge Badge (Test)',
    '抽奖券': 'Lottery Ticket', '用于罗塔锦鲤活动换取兑奖码，也可以在周年庆商城中兑换锦鲤徽章和锦鲤头像框。活动时间结束后每张没有进行兑换的召唤券将转化为10星石。':
        'Used in the Rota Koi event to get prize codes, or exchanged for the Koi Badge and Koi Avatar Frame in the Anniversary Shop. After the event, each unused ticket turns into 10 Starstones.',
    '用于装饰队长头像的头像框，可以在换装外观界面进行更换。': "An avatar frame for the captain's profile picture. Change it from the appearance screen.",
    '可以更换手机顶部的背景壁纸': 'Changes the wallpaper at the top of the phone',
    '爱-透明低语': 'Aurele - Clear Whisper', '兔-睡前故事': 'Tutu - Bedtime Story', '梦-被窝酣眠': 'Moon - Snug Slumber',
    '动画主角L': 'Anime Lead L', '动画主角M': 'Anime Lead M', '动画主角R': 'Anime Lead R',
    '获得后能够解锁爱-透明低语头像': 'Unlocks the "Aurele - Clear Whisper" profile picture',
    '获得后能够解锁兔-睡前故事头像': 'Unlocks the "Tutu - Bedtime Story" profile picture',
    '获得后能够解锁梦-被窝酣眠头像': 'Unlocks the "Moon - Snug Slumber" profile picture',
    '获得后能够解锁动画主角L头像': 'Unlocks the "Anime Lead L" profile picture', '获得后能够解锁动画主角M头像': 'Unlocks the "Anime Lead M" profile picture',
    '获得后能够解锁动画主角R头像': 'Unlocks the "Anime Lead R" profile picture',
    '蕾': 'Connie', '解锁探索员头像所需要的道具': "Item needed to unlock this Salvager's profile picture",
    '蕾的马口铁徽章': "Connie's Tin Badge", '获得该徽章可以后续前往官方指定页面领取实物吧唧周边': 'Owners could later claim a physical pin badge from the official page',
    '获得后可以解锁特别的聊天表情包': 'Unlocks a special chat sticker',
    '蕾塞舞': "Connie's Dance", '获得后可以解锁蕾塞舞互动动作': "Unlocks the \"Connie's Dance\" interaction emote",
    '注意！只有直接获得该动作才可以教会其他人，通过学习他人的动作是无法进行教学的。': 'Note: only players who obtained this emote directly can teach it; an emote learned from someone else cannot be taught.',
    '抱摔': 'Suplex', '获得后可以解锁抱摔互动动作': 'Unlocks the "Suplex" interaction emote',
    # outfits
    '樱草初绽头饰': 'Primrose Bloom Headpiece', '小鹿角、小耳朵、花瓣发饰，是阳光下自由的小鹿。': 'Little antlers, little ears and petal hair clips: a free fawn in the sunshine.',
    '樱草初绽发辫': 'Primrose Bloom Braids', '粉红色的双麻花辫，洋溢着春樱的气息。': 'Pink twin braids brimming with spring blossoms.',
    '樱草初绽裙装': 'Primrose Bloom Dress', '点缀着粉红色花瓣的裙装，搭配透明裙摆与袖管，透露着青草地的清新。': 'A dress scattered with pink petals, with sheer skirt and sleeves, fresh as a meadow.',
    '暗夜哥特发辫': 'Night Gothic Twintails', '渐变色的大螺旋双马尾，沉稳和高冷遮盖不住一丝俏皮。': 'Big gradient spiral twintails; calm and aloof, yet a little playful.',
    '暗夜哥特裙装': 'Night Gothic Dress', '黑白配色的哥特式裙装，低调的华丽。': 'A black-and-white gothic dress. Understated elegance.',
    '暗夜哥特小翅膀': 'Night Gothic Wings', '黑色闪耀着点点星芒的小翅膀，质感拉满。': 'Little black wings glittering with starlight. Top-tier texture.',
    '暗夜哥特洋伞': 'Night Gothic Parasol', '搭配裙装的简约洋伞，基础的配色，华丽的款式。': 'A simple parasol to match the dress: basic colors, gorgeous style.',
    '盛夏沙滩遮阳帽': 'Midsummer Beach Sun Hat', '搭配着蝴蝶结的粉色遮阳帽，夏日必备品。': 'A pink sun hat with a bow. A summer essential.',
    '盛夏沙滩长发': 'Midsummer Beach Long Hair', '充满活力的披肩长发，少女感认证。': 'Lively shoulder-length hair. Certified girlish.',
    '盛夏沙滩露肩装': 'Midsummer Beach Off-Shoulder Set', '充满夏日气息的露肩热裤套装，记得涂好防晒哦。': 'An off-shoulder top and hot pants full of summer. Remember your sunscreen!',
    '盛夏沙滩墨镜[1]': 'Midsummer Beach Sunglasses [1]', '盛夏沙滩墨镜[2]': 'Midsummer Beach Sunglasses [2]', '盛夏沙滩墨镜': 'Midsummer Beach Sunglasses',
    '夏日沙滩伴侣之墨镜，点缀以花朵图案。': 'Beach-day sunglasses decorated with flowers.',
    '可爱星星发型': 'Cute Star Hairstyle', '可爱的直短发，少女感认证。': 'Cute straight short hair. Certified girlish.',
    '可爱星星裙装': 'Cute Star Dress', '点缀着星星图案的套头裙装，活泼又减龄的款式。': 'A pullover dress with star patterns. Lively and youthful.',
    # furniture
    '花店储物架': 'Flower Shop Shelf', '海边渔具': 'Seaside Fishing Gear', '禅院古琴': 'Zen Temple Guqin', '古琴': 'Guqin',
    '精美的小家具装饰，可以用来装扮花园广场。': 'A fine piece of furniture for decorating the Garden Plaza.',
    '星梦圆舞曲': 'Starry Dream Waltz',
    '点缀着蔷薇与星光的梦幻旋转木马，传说中封存着永无止境的童话。\n它的核心刻有特殊的魔力回路，当受到外力冲击时，旋转速度会越来越快。\n——小心，别把美梦转晕了。':
        'A dreamy carousel of roses and starlight, said to hold a never-ending fairy tale.\nA special magic circuit is carved into its core: the harder it is pushed, the faster it spins.\n— Careful not to make your sweet dreams dizzy.',
    '风暴之椅': 'Storm Chair', '随处可见的白色塑料椅，坐上去后却好像隐隐能听到风暴的声音。': 'An ordinary white plastic chair, yet sit on it and you can faintly hear a storm.',
    '清纹玉枰': 'Jade Go Board', '精美的小家具装饰，可以用来装扮花园广场。交互后可以游玩五子棋游戏。': 'A fine piece of furniture for decorating the Garden Plaza. Interact with it to play Gomoku.',
    '上升风场[1]': 'Updraft [1]', '上升风场[2]': 'Updraft [2]',
    '精美的小家具装饰，可以用来装扮花园广场。靠近似乎可以飞得更高？': 'A fine piece of furniture for decorating the Garden Plaza. Stand close and you might fly higher?',
    '精美的小家具装饰，可以用来装扮花园广场。靠近似乎可以飞起来？': 'A fine piece of furniture for decorating the Garden Plaza. Stand close and you might take off?',
    '联合演算纪念家具，可以用来装扮花园广场。': 'United Calculation memorial furniture for decorating the Garden Plaza.',
    # gift sets
    '布偶熊玩偶服': 'Teddy Bear Costume', '可获布偶熊玩偶服套装': 'Contains the Teddy Bear Costume set',
    '夜色堇套装': 'Night Violet Set', '可获夜色堇套装': 'Contains the Night Violet set', '魔术套装': 'Magic Set', '可获华丽魔术套装': 'Contains the Dazzling Magic set',
    '朝雾学生套装': 'Morning Mist Student Set', '可获朝雾学生套装': 'Contains the Morning Mist Student set',
    '焰金魔法套装': 'Blazing Gold Magic Set', '可获焰金魔法套装': 'Contains the Blazing Gold Magic set',
    '禅院家具套装': 'Zen Temple Furniture Set', '可获禅院家具套装': 'Contains the Zen Temple furniture set',
    '粉色甜酷套装': 'Pink Sweet-Cool Set', '可获粉色甜酷套装': 'Contains the Pink Sweet-Cool set', '中式节日套装': 'Chinese Festival Set',
    '可获中式节日套装': 'Contains the Chinese Festival set', '小天使套装': 'Little Angel Set', '可获小天使套装': 'Contains the Little Angel set',
    '升级的秘诀': 'Secret to Leveling Up', '快速升级的秘诀': 'Secret to Leveling Up Fast', '金马贺岁': 'Golden Horse New Year',
    '“透明色的告白”': '"A Clear Confession"', '“蓝色是今天的我，粉色是梦里的我。你收到的是哪一封告白？”': '"Blue is me today, pink is me in my dreams. Which confession did you receive?"',
    '兔兔的月光收藏': "Tutu's Moonlight Collection", '“兔兔将珍藏的故事与温柔收在这里，等待与你一同开启。"': '"Tutu keeps her treasured stories and tenderness here, waiting to open them with you."',
    '游戏币补给礼包': 'Game Coin Supply Package', '内含一定数量的游戏币，可用于开启游戏厅中的小游戏。': 'Contains Game Coins for playing arcade minigames.',
    '藏在枕头里的月亮': 'The Moon Hidden in a Pillow', '“听说每个枕头里都藏着一轮小小的月亮，只有在甜甜的梦乡中才能发现。”': '"They say every pillow hides a tiny moon, found only in sweet dreams."',
    '散落在城市的收藏品': 'A collectible scattered around the city',
    '一个神秘的磁带，记录了某公司老板羞于启齿的童年小故事。': "A mysterious tape with a certain company boss's embarrassing childhood stories.",
    '临时背包格子增加+1': 'Temporary bag slots +1', '临时背包格子增加+2': 'Temporary bag slots +2',
    # misc short
    '椿月回忆商店': 'Camellia Moon Memories Shop', '素材商店': 'Materials Shop', '周年庆商城': 'Anniversary Shop', '周年庆礼包商店': 'Anniversary Package Shop',
    '活动商店': 'Event Shop', '搜打撤': 'Search-Fight-Extract', '宫': 'Gong', '商': 'Shang', '角': 'Jue', '徵': 'Zhi', '羽': 'Yu',
    '联合演算 S3': 'United Calculation S3', '宠物食材仓库': 'Pet Food Storehouse', '每日开放': 'Open daily', '星愿学园': 'Orison School',
    '万家灯火': 'Lights of Ten Thousand Homes', '活动副本': 'Event Stage', '击败青铜鼎': 'Defeat the Bronze Cauldron', '击败所有怪物': 'Defeat all monsters',
    '数列空间': 'Sequence Field', '模拟空间': 'Simulated Field', '灰物成长素材': 'Ashen Creature growth materials',
    '研究部搭建的模拟空间，可通过空间能量累积灰生物喜欢的食物，同时也会招来灰生物……\n<color=#EB005D>(每日开放)</color>':
        "A simulated field built by the Research Department. Field energy builds up food the Ashen Creatures love... which also attracts them.\n<color=#EB005D>(Open daily)</color>",
    '颠倒的世界': 'The Upside-Down World', '颠倒的世界-1': 'The Upside-Down World - 1', '荧荧说有一个大消息要告诉我们': 'Irene says she has big news for us',
    '完成主线章节7故事11': 'Complete Main Story Chapter 7, Part 11',
    '罗塔锦鲤特别奖励发放！': 'Rota Koi special reward!', '《开放空间》运营团队': 'The OverField Team',
    '亲爱的欧皇队长：\n\n特别感谢您在周年庆期间对于我们的支持，希望你收下这份心意。\n\n下个周年希望我们能和队长一起乘风破浪！':
        "Dear Lucky Captain,\n\nThank you so much for supporting us during the Anniversary. Please accept this token of our thanks.\n\nWe hope to ride the waves with you again next anniversary!",
    '爱的特殊头像贴纸，可以在手机的个人头像里进行更换。': "Aurele's special profile sticker. Change it from your phone's profile picture.",
    '兔的特殊头像贴纸，可以在手机的个人头像里进行更换。': "Tutu's special profile sticker. Change it from your phone's profile picture.",
    '梦的特殊头像贴纸，可以在手机的个人头像里进行更换。': "Moon's special profile sticker. Change it from your phone's profile picture.",
    '特殊的礼装头像贴纸，可以在手机的个人头像里进行更换。': "A special formal profile sticker. Change it from your phone's profile picture.",
    '一张印着特别图案的大头贴，获得方式暂时未知。': 'A photo sticker with a special design. How to get it is unknown for now.',
    '参与特别活动后可获得': 'Obtained from special events', '获得[抱摔]表情道具后可解锁': 'Unlocked after obtaining the [Suplex] emote item',
    '累积登录60天': 'Log in for 60 days in total', '当前充值金额': 'Current top-up amount', '累积充值达到29元': 'Top up 29 CNY in total',
    '等级达到20级': 'Reach Level 20', '一起战斗10次': 'Fight together 10 times', '担任领队战斗10次': 'Fight as party leader 10 times',
    '[外传]各自的前辈': '[Side Story] Their Own Seniors', '[外传]看穿命运的眼': '[Side Story] Eyes That See Fate',
    '[外传]给孩子们的糖果': '[Side Story] Candy for the Children',
    '咖啡店来了一位不速之客。': 'An unexpected guest arrives at the café.', '小伏离开后，一个人影悄悄靠近……': 'After Kobushi leaves, a figure quietly approaches...',
    '他们来到了一个无人的角落。': 'They come to a deserted corner.', '占卜结束后，洛洛莓回到了现实世界……': 'After the reading, Lolomay returns to the real world...',
    '洛洛莓决定去咖啡店等待。': 'Lolomay decides to wait at the café.', '乌娜躲在阴影里': 'Unna hides in the shadows', '前往咖啡店': 'Go to the café',
    '前往杂货店': 'Go to the general store', '前往小吃店': 'Go to the snack shop', '前往罗塔公司': 'Go to Rota Corporation',
    '规划路线<color=red>点亮脚下的砖块</color>。 像一笔画般不要经过重复的格子。 \n\n连贯地<color=red>踩遍每一个格子</color>，宝箱就会出现。':
        'Plan a route to <color=red>light up the tiles under your feet</color>. Like a one-stroke drawing, never cross the same tile twice.\n\n<color=red>Step on every tile</color> in one go and a chest will appear.',
    '连贯地点亮砖块': 'Light up the tiles in one go', '还剩砖块': 'Tiles left', '个': '', '一笔砖块': 'One-Stroke Tiles',
    '铲子': 'Shovel', '好寂寞': 'So Lonely', '高雅人士1': 'Refined Person 1', '芝麻虫虫': 'Sesame Bug', '芭蕾礼仪': 'Ballet Bow',
    '手势舞': 'Hand Dance', '打喷嚏': 'Sneeze', '右滚': 'Roll Right', '左滚': 'Roll Left', '泄气': 'Deflated',
    '通行证': 'Pass', '通行证展示': 'Pass Showcase', '活动商店': 'Event Shop', '流星扭蛋机': 'Meteor Gacha', '星座扭蛋机': 'Zodiac Gacha', '星光扭蛋机': 'Starlight Gacha',
    '七日签到': '7-day Check-in', '周年庆签到（10日签到）': 'Anniversary Check-in (10 days)', '51签到（8日签到）': 'May Day Check-in (8 days)',
    '暖风树': 'Warm Breeze Tree', '童趣树': 'Childhood Tree', '棒球树': 'Baseball Tree', '宴席树': 'Banquet Tree', '雅韵树': 'Elegance Tree',
    '净心树': 'Pure Heart Tree', '资源树': 'Resource Tree', '红冬树': 'Red Winter Tree', '幽冥庭院': 'Netherworld Courtyard', '罗塔火锅店': 'Rota Hotpot Restaurant',
    '校园14日': '14 Days at School', '火锅': 'Hotpot', '美食节': 'Food Festival', '莉': 'Molly', '夜色堇': 'Night Violet', '春日甜食': 'Spring Sweets',
    '布偶熊': 'Teddy Bear', '爱心座椅': 'Heart Chair', '星心小马': 'Star-Heart Pony', '暴打老李': 'Beat Up Mr. Li', '暴打老李-召请活动': 'Beat Up Mr. Li - Invite Event',
    '暴打老李-回归活动': 'Beat Up Mr. Li - Return Event', '周年庆生': 'Anniversary Celebration', '周年礼包': 'Anniversary Packages', '周年币商城': 'Anniversary Coin Shop',
    '周年庆回馈': 'Anniversary Rewards', '每日怪物寻宝': 'Daily Monster Treasure Hunt', '周年许愿': 'Anniversary Wishes', '周年抽奖': 'Anniversary Lottery',
    '樱落归期': 'When the Sakura Falls', '51限定商城': 'May Day Limited Shop', '51充值回馈': 'May Day Top-up Rewards', '雨润鱼肥': 'Rain-Fed Fish',
    '骑狗狗': 'Doggy Ride', '万圣留影墙': 'Halloween Photo Wall',
    '「虎虎狮妹」寅': '"Lion Dancing Girl" Yin', '「苍白女孩」乌': '"Vampire Girl" Unna', '「命运占卜师」洛': '"Fortune Teller" Lolomay',
    '「登山少年」辉': '"Mountain Boy" Naoki', '「幻想同人女」爱': '"Fantasy Fangirl" Aurele', '「小魔术师」蓝': '"Little Magician" Lacy',
    '「灰蓝偶像」宁': '"Cool Idol" Meng', '「天气之子」橙': '"Weather Child" CC', '「神机妙算」喜': '"Divine Calculator" Sixi',
    '「神秘记者」蕾': '"Mysterious Reporter" Connie', '「雾都侦探」莫': '"Fog City Detective" Molly',
    # recordings (title, text)
    '老李录音：钓鱼': "Mr. Li's Tape: Fishing", '老李录音：赶海': "Mr. Li's Tape: Beachcombing", '老李录音：老李独白': "Mr. Li's Tape: Mr. Li's Monologue",
    '老李录音：海鲜汤': "Mr. Li's Tape: Seafood Soup", '老李录音：海里垃圾': "Mr. Li's Tape: Trash in the Sea", '老李录音：毛线球变多': "Mr. Li's Tape: More Yarn Balls",
    '老李录音：武器平衡性': "Mr. Li's Tape: Weapon Balance", '老李录音：柠檬落地灯': "Mr. Li's Tape: Lemon Floor Lamp", '老李录音：柜门挡WIFI': "Mr. Li's Tape: Cabinet Door Blocks WiFi",
    '老李录音：染发': "Mr. Li's Tape: Hair Dye", '老李录音：弹药和体力': "Mr. Li's Tape: Ammo and Stamina", '老李录音：女装': "Mr. Li's Tape: Crossdressing",
    '老李录音：四瓶盐三瓶油': "Mr. Li's Tape: Four Bottles of Salt, Three of Oil", '老李录音：制作物品': "Mr. Li's Tape: Crafting",
    '老李录音：从来没有学过B': "Mr. Li's Tape: Never Learned B", '老李录音：五瓶盐的蛋炒饭': "Mr. Li's Tape: Five-Salt Fried Rice", '老李录音：二段跳': "Mr. Li's Tape: Double Jump",
    '老李录音：九个柠檬十二个胡萝卜': "Mr. Li's Tape: Nine Lemons, Twelve Carrots", '老李录音：一条条垃圾': "Mr. Li's Tape: Trash by the Piece", '老李录音：一件背心': "Mr. Li's Tape: One Vest",
    '老李小时候特别喜欢钓鱼，但是又特别的菜。所以现在每用100个鱼饵，就得消耗1000根钓鱼竿。': 'As a kid Mr. Li loved fishing but was terrible at it. That is why every 100 baits now cost 1,000 fishing rods.',
    '老李小时候在70级升80级的过程中，需要一年四季地去赶海。而现在他坚持这样，于是，他被人打了。': 'As a kid, going from level 70 to 80 meant beachcombing all year round. He still insists on it, so he got beaten up.',
    '当老李小时候第一次摸到八位机，我就想，以后一定要做自己的游戏。在大厂打了十几年的工，再到七年前决定自己创业，这一路坚持真的很难。但，要我放弃，那是更难的一件事情。如果你能听到这里，说明你还没走，还在陪着我们。我们还有很多地方要改，很多新内容要做。我们会一直努力，把游戏一点一点做得更好。谢谢你，谢谢你一直都在，也希望你未来还在。':
        'The first time I touched an 8-bit console as a kid, I knew I would make my own game one day. After more than ten years at big studios, I started my own company seven years ago. Sticking with it has been really hard. But giving up would be even harder. If you can hear this, you are still here with us. There is a lot left to fix and a lot of new content to make. We will keep working to make the game better, bit by bit. Thank you for always being here, and I hope you will still be here in the future.',
    '是什么菜需要加12瓶酱油和12瓶盐呢？那是老李小时候吃过最咸的菜——海鲜汤。': 'Which dish needs 12 bottles of soy sauce and 12 of salt? The saltiest thing Mr. Li ate as a kid: seafood soup.',
    '为什么海里只有垃圾呢？是因为老李小时候喜欢把家门口的垃圾场当作海洋，一个人在里面游啊游啊。': 'Why is there only trash in the sea? Because as a kid Mr. Li pretended the dump outside his house was the ocean and swam around in it alone.',
    '嘿，你知道为什么失败的时候有概率让毛线球变多吗？那是因为老李小时候学习过黑暗炼金术。': 'Hey, know why failing can sometimes give you more yarn balls? Mr. Li studied dark alchemy as a kid.',
    '老李小时候踩在凳子上面拿东西，因为自己的平衡性太差而摔了一个大跟头。因此，所有武器的平衡性越差，就越容易出现超低伤害。': 'As a kid Mr. Li stood on a stool to reach something and took a big fall because his balance was terrible. So the worse a weapon\'s balance, the more often it does super-low damage.',
    '老李小时候给家里制作的落地灯，居然是用柠檬做的。': 'The floor lamp Mr. Li made for his home as a kid was made of lemons.',
    '老李小时候发现打开自家的柜门，就会影响整栋楼的WiFi。': 'As a kid Mr. Li found that opening his cabinet door knocked out WiFi for the whole building.',
    '老李小时候去理发店染发，遇到了黑店。染了十次才染出一次他想要的颜色。': 'As a kid Mr. Li got his hair dyed at a shady salon. It took ten tries to get the color he wanted once.',
    '老李小时候玩弹弓，发现弹药的数量和自己的体质居然相关。': 'Playing with a slingshot as a kid, Mr. Li found his ammo count depended on his constitution.',
    '老李小时候要女装，必须吃了药才能穿上小裙子。': 'As a kid, Mr. Li had to take a potion before he could fit into a little dress.',
    '普通的一顿饭要四瓶盐、三瓶油，原因是老李小时候闹过饥荒。': 'An ordinary meal takes four bottles of salt and three of oil, because Mr. Li lived through a famine as a kid.',
    '带着75%的成功率来制作物品，居然有一半都会失败。哼，那是因为老李小时候的数学是体育老师教的。': 'Crafting at 75% success and half of them fail? Hmph. Mr. Li\'s math was taught by the PE teacher.',
    '老李小时候的英文又又又又是体育老师教的。所以他只学了A、C、D、E、F、G，从来没有学过B。': 'Mr. Li\'s English was also, also, also taught by the PE teacher. So he only learned A, C, D, E, F, G and never B.',
    '老李从小到大的口味都很重，一份普通的蛋炒饭就要加五瓶盐。': 'Mr. Li has always liked strong flavors: five bottles of salt in plain egg fried rice.',
    '嘿，你知道吗？老李小学二年级才学会跑步，但是在一年级的时候就学会了二段跳。': 'Hey, did you know? Mr. Li only learned to run in second grade, but learned the double jump in first grade.',
    '老李小时候从来没有吃过柠檬，也没有吃过胡萝卜。所以当他吃章鱼刺身的时候，大喊一声：“给我来九个柠檬，12个胡萝卜！”': 'As a kid Mr. Li had never eaten lemons or carrots. So when he had octopus sashimi he shouted: "Give me nine lemons and 12 carrots!"',
    '钓鱼图鉴里所有的垃圾都是“一条一条”的，那是因为老李小时候的语文也是体育老师教的。': 'All the trash in the fishing guide is counted "per fish", because Mr. Li\'s Chinese class was also taught by the PE teacher.',
    '小时候的某一天，老李剪了家里三件衣服，才做出来了一件背心。': 'One day as a kid, Mr. Li cut up three pieces of clothing to make a single vest.',
}
ABIL = {'[贝海姆]捕虫幸运结算概率': '[Behaim] Bug-catching luck chance', '捕虫幸运结算概率': 'Bug-catching luck chance',
        '[贝海姆]采集幸运结算概率': '[Behaim] Gathering luck chance', '采集幸运结算概率': 'Gathering luck chance',
        '[贝海姆]先攻击飞': '[Behaim] First-strike knockback', '生命百分比': 'HP %', '移动速度': 'Move speed', '暴击伤害': 'Crit DMG',
        '[贝海姆]先攻必杀': '[Behaim] First-strike critical', '暴击率': 'Crit rate', '[贝海姆]奔跑消耗降低': '[Behaim] Sprint cost reduction',
        '奔跑消耗降低': 'Sprint cost reduction'}


def rules(x, tm):
    if x in MANUAL:
        return MANUAL[x]
    if not re.search(r'[\u4e00-\u9fff]', x):
        return x
    if x in tm:
        return tm[x]
    m = re.fullmatch(r'(.+?)：?([\d.]+/[\d.]+%?)?', x)
    if m and m.group(1).rstrip('：') in ABIL:
        k = ABIL[m.group(1).rstrip('：')]
        return k + (': ' + m.group(2) if m.group(2) else ':')
    m = re.fullmatch(r'(黄金|白银|黄铜|黑铁)(.+座)奖杯底座', x)
    if m:
        return f'{METAL[m.group(1)]} {ZODIAC[m.group(2)]} Trophy Base'
    m = re.fullmatch(r'制作【星座(金|银|铜|铁)杯-(.+座)】的必要材料', x)
    if m:
        return f'Required to craft [Zodiac {METAL[m.group(1)]} Cup - {ZODIAC[m.group(2)]}]'
    m = re.fullmatch(r'星座(金|银|铜|铁)杯-(.+座)', x)
    if m:
        return f'Zodiac {METAL[m.group(1)]} Cup - {ZODIAC[m.group(2)]}'
    m = re.fullmatch(r'深渊S(\d+)(挑战)?徽章', x)
    if m:
        return f'Abyss S{m.group(1)} {"Challenge " if m.group(2) else ""}Badge'
    m = re.fullmatch(r'\[(特殊|晴天娃娃|布丁狗) \| (.+)\]', x)
    if m:
        who, what = m.group(1), m.group(2)
        head = {'特殊': 'Special', '晴天娃娃': 'Sunshine Doll', '布丁狗': 'Pompompurin'}[who]
        inner = STICKER.get(what, what)
        return f'[{head} | {inner}]'
    m = re.fullmatch(r'制作(.+?)(\[\d\])?(\d+)次', x)
    if m and m.group(1) in NAMES:
        n = int(m.group(3))
        return f'Craft {NAMES[m.group(1)]}{m.group(2) or ""} ' + ('once' if n == 1 else f'{n} times')
    m = re.fullmatch(r'累积充值达到(\d+)元', x)
    if m:
        return f'Top up {m.group(1)} CNY in total'
    m = re.fullmatch(r'高雅人士(\d+)', x)
    if m:
        return f'Refined Person {m.group(1)}'
    m = re.fullmatch(r'联合演算 S(\d+)', x)
    if m:
        return f'United Calculation S{m.group(1)}'
    m = re.fullmatch(r'颠倒的世界-(\d+)', x)
    if m:
        return f'The Upside-Down World - {m.group(1)}'
    m = re.fullmatch(r'(源点压制|基站维护|紧急救援|深层回收|异象侦测)\[(\d+)\]', x)
    if m:
        return {'源点压制': 'Source Suppression', '基站维护': 'Base Station Maintenance', '紧急救援': 'Emergency Rescue',
                '深层回收': 'Deep Recovery', '异象侦测': 'Anomaly Detection'}[m.group(1)] + f' [{m.group(2)}]'
    m = re.fullmatch(r'击杀(.+?)(\(樱花\))?1次', x)
    if m and m.group(1) in NAMES:
        return f'Defeat {NAMES[m.group(1)]}{" (Sakura)" if m.group(2) else ""} once'
    m = re.fullmatch(r'总评价达到(\d+)', x)
    if m:
        return f'Reach a total score of {int(m.group(1)):,}'
    m = re.fullmatch(r'第(.+)期通行证获得', x)
    if m:
        return f'From Pass Season {CNNUM.get(m.group(1), m.group(1))}'
    m = re.fullmatch(r'灰物食材仓库\[(.+)\]', x)
    if m:
        return f'Ashen Creature Food Storehouse [{NUM.get(m.group(1), m.group(1))}]'
    m = re.fullmatch(r'共创树(.+)', x)
    if m:
        return f'Co-creation Tree {m.group(1)}'
    # gift packs: glossary composition
    if re.search(r'礼包|补给$', x) or x in ('万圣糖果礼包',):
        y = x
        for k in sorted(GLOSS, key=len, reverse=True):
            y = y.replace(k, ' ' + GLOSS[k] + ' ')
        for k, v in NUM.items():
            y = y.replace(k, ' ' + v)
        y = re.sub(r'\s+', ' ', y).strip()
        if not re.search(r'[一-鿿]', y):
            return y
    return None


STICKER = {'菲切菜': 'Fei Chopping Veggies', '菲揉脸': 'Fei Squishing Cheeks', '洛赞！': 'Lolomay: Nice!', '鸽鱼': 'Dove Fish',
           '洛接电话': 'Lolomay on the Phone', '伏www': 'Kobushi lol', '莉打招呼': 'Molly Says Hi', '菲举蘑菇': 'Fei Holding a Mushroom',
           '格不愧是我': 'Gazetter: As Expected of Me', '蓝无语': 'Lacy Speechless', '菲惊讶': 'Fei Surprised', '菲胡言乱语': 'Fei Babbling',
           '伏靠我了': 'Kobushi: Leave It to Me', '下雨': 'Rain', '莉心虚': 'Molly Feeling Guilty', '热化了': 'Melting in the Heat',
           '洛哦内盖': 'Lolomay: Onegai', '菲大餐': 'Fei Feast', '莱诶嘿': 'Lexy: Ehehe'}
CNNUM = {'十五': '15', '十六': '16', '二十': '20', '二十一': '21'}
NAMES = {}


def build(rows, tm, names):
    NAMES.update(names)
    out, missing = {}, []
    for key, texts in rows:
        res = []
        for x in texts:
            if not x.strip():
                res.append(x); continue
            y = globals()['rules'](x, tm)
            if y is None:
                missing.append(x); y = x
            res.append(y)
        out[key] = res
    return out, missing


# ---------------------------------------------------------------- long texts: translated line by line
LINES = {
    '一名重要的研究员在采集样本时与护卫走散了。': 'An important researcher got separated from their escort while collecting samples.',
    '他身上带着关键的数据硬盘，绝对不能有闪失。': 'He is carrying a critical data drive. Nothing can go wrong.',
    '找到他，把他安全地护送到撤离点。': 'Find him and escort him safely to the extraction point.',
    '我们需要一种特殊的晶体来升级天车的引擎。': "We need a special crystal to upgrade the Skycart's engine.",
    '这种晶体只生长在污染最严重的坑道深处。': 'It only grows deep in the most contaminated tunnels.',
    '采集过程可能会引来大家伙，请务必小心。': 'Collecting it may draw out something big. Be careful.',
    '地图上的这个坐标出现了一块无法解析的黑色区域。': 'An unreadable black zone has appeared at these map coordinates.',
    '既不是灰物反应，也不是地形阻挡。': "It isn't an Ashen Creature signal, and it isn't terrain.",
    '去那边看一眼，哪怕只是拍张照片回来也好。': 'Go take a look, even if you only bring back a photo.',
    '最近这附近的重力参数有些异常，走路都会觉得飘。': "Gravity readings around here have been off lately. Walking feels floaty.",
    '怀疑是有特殊的变异体在干扰磁场。找到那个干扰源并消灭它，不然大家都寸步难行。': "We suspect a special mutant is disrupting the magnetic field. Find the source and eliminate it, or nobody can move.",
    '我们的前哨站遭到了伏击，通讯刚刚中断了。': 'Our outpost was ambushed and communications just went dark.',
    '那是我们在该区域最后的据点，绝不能丢失。': "It's our last foothold in the area. We can't lose it.",
    '不论付出什么代价，都要把里面的人救出来！': 'Get the people inside out, whatever it takes!',
    '糟糕的消息，那片区域的“源点”比预想的要活跃。': 'Bad news: the "Source" in that area is more active than expected.',
    '已经有一批异化灰物开始向外围扩散了。': 'A wave of mutated Ashen Creatures is already spreading outward.',
    '务必在它们冲破防线前，将核心区域彻底肃清。': 'Clear out the core area before they break through the line.',
    '接到求救信号，有一支新人探索队在回程路上迷路了。': 'We got a distress call: a rookie exploration team got lost on the way back.',
    '他们的氧气和补给都不多了，情况不太乐观。': "They're low on oxygen and supplies. It doesn't look good.",
    '你离他们最近，能过去把他们带回来吗？': "You're closest. Can you go bring them back?",
    '侦测器在前方废墟深处发现了高频的灰物反应。': 'The detector picked up heavy Ashen Creature activity deep in the ruins ahead.',
    '如果不及时处理，它们很快就会形成规模。': "If we don't deal with it now, they'll grow into a horde.",
    '趁它们还没聚集起来，去把那个生成点端掉吧！': 'Take out the spawn point before they gather!',
    '空气中弥漫着一种奇怪的孢子，吸入过多会产生幻觉。': 'Strange spores fill the air. Breathe in too many and you will hallucinate.',
    '必须在防护服滤芯耗尽前找到散布孢子的母体。': "Find the mother spreading them before your suit's filter runs out.",
    '动作要快，别让幻觉干扰了你的判断。': "Be quick, and don't let the hallucinations cloud your judgement.",
    '该死，净化装置的过滤网堵塞了，稳定性正在急速下降！': "Damn, the purifier's filter is clogged and stability is dropping fast!",
    '如果不马上进行抢修，整片区域都会被污染。': "If it isn't fixed now, the whole area will be contaminated.",
    '请掩护维修小队，消灭所有靠近的灰物！': 'Cover the repair team and destroy every Ashen Creature that comes close!',
    '运输队的一辆载具抛锚了，现在被困在灰雾边缘。': "A transport vehicle broke down and is stuck at the edge of the grey fog.",
    '听说那边出现了高攻击性的异化体，他们撑不了太久。十万火急，请立即前往支援，确保存活！': "Highly aggressive mutants were spotted there and they won't hold out long. It's urgent: go support them now and keep them alive!",
    '这里的信号中继站最近总是受到干扰，效率大幅下降。': 'The signal relay here keeps getting interference and its efficiency has dropped a lot.',
    '技术人员说是因为附近有灰物在啃食线路。': 'The technicians say Ashen Creatures nearby are chewing the cables.',
    '麻烦你去清理一下周围，让基站恢复正常运作。': 'Please clear the area so the base station can work normally again.',
    '我们需要在这片高地架设临时信标，以扩展探索视野。': 'We need to set up a temporary beacon on this high ground to extend our view.',
    '架设设备需要一点时间，而且动静可能会有点大。': 'Setting it up takes a while and may be a bit noisy.',
    '帮我们要守住阵地，别让任何东西靠近设备！': 'Hold the position and keep everything away from the equipment!',
    '档案显示这片旧城区里遗留着一些未损坏的存储芯片。': 'Records show some undamaged memory chips were left in this old district.',
    '虽然那里灰物密度很高，但这些数据对研究部很有用。': "There are lots of Ashen Creatures there, but the Research Department really needs that data.",
    '能不能请你潜入进去，悄悄把东西带出来？': 'Could you sneak in and quietly bring them out?',
    '这次的目标有点棘手，是一个已经发生了变异的聚合体。': 'This target is tricky: a cluster that has already mutated.',
    '它周围聚集了大量的灰物，普通的火力很难接近。': "It's surrounded by Ashen Creatures; normal firepower can barely get close.",
    '这是一场硬仗，但如果是你的话，应该没问题。': "It'll be a tough fight, but you should be fine.",
    '既然你正好在那边，能不能帮我测试一下新研发的探测器？': "Since you're over there, could you test our new detector for me?",
    '只需要带着它跑遍这几个标记点就行。': 'Just carry it around these marked points.',
    '虽然可能会引来一些好奇的灰物，但这正是测试的一部分！': "It may attract some curious Ashen Creatures, but that's part of the test!",
    '3号观测塔的能源核心正在重启，这期间防御力场会失效。': "Observation Tower 3's power core is rebooting and its shield will be down meanwhile.",
    '那些灰物对能量波动很敏感，肯定会蜂拥而至。': "Ashen Creatures are sensitive to energy surges; they'll swarm in for sure.",
    '在重启完成前的这几分钟里，塔的安全就交给你了。': "For these few minutes until the reboot finishes, the tower's safety is in your hands.",
    '这是一个特殊的委托，我们要回收一个仍在运作的“旧日核心”。': 'A special request: we need to recover an "Old Core" that is still running.',
    '它的辐射会不断吸引周围的怪物，搬运过程会非常艰难。': 'Its radiation keeps drawing in monsters, so moving it will be very hard.',
    '准备好迎接冲击了吗？这可是个大工程。': "Ready for impact? This is a big job.",
    '警报！监测到极不稳定的能量波动，源点即将爆发！': 'Alert! Extremely unstable energy detected. The Source is about to erupt!',
    '必须立刻切断它们与灰域的连接。': 'Cut their link to the Grey Zone right now.',
    '动作要快，一定要在能量失控前结束战斗！': 'Move fast and end the fight before the energy goes out of control!',
    '有个遗落的空投补给箱掉在了裂隙边缘。': 'A lost airdrop supply crate landed at the edge of the rift.',
    '那里地势险要，而且周围有很多飞行种灰物徘徊。': 'The terrain is treacherous and flying Ashen Creatures circle the area.',
    '身手敏捷的任务非你莫属，拜托了。': 'A job for someone agile: you. Please.',
    '〓扭蛋机规则〓': '〓Gacha Machine Rules〓',
    '※本期每次抽取扭蛋需消耗1枚扭蛋币，首次单抽扭蛋可享1折。': '※Each draw costs 1 Gacha Coin. Your first single draw is 90% off.',
    '※本期扭蛋物品共有种类13款，总数45个，其中3款为主题款物品，其余10款为普通款物品。': '※This machine has 13 kinds of items, 45 in total: 3 themed items and 10 regular items.',
    '※每次抽中扭蛋后，该款扭蛋总数减少1，当总数减少至0时表示该款扭蛋不再会被抽中。': '※Each draw removes 1 of that item; once an item reaches 0 it can no longer be drawn.',
    '※所有主题款物品都被抽出后，剩余扭蛋将作为奖励全部赠送。': '※Once all themed items are drawn, everything left is given to you as a reward.',
    '※若在10连抽取过程中，提前抽完扭蛋机中所有物品或主题款余量为0，会归还本次10连中未使用的扭蛋币。': '※If a 10-draw empties the machine or the themed items run out early, unused Gacha Coins are refunded.',
    '※当所有扭蛋及奖励都获取后，本扭蛋机不可再进行贩售抽取。': '※Once all items and rewards are obtained, the machine closes.',
    '※活动结束时尚未使用的扭蛋币不会回收，可通用于之后推出的扭蛋机。': '※Unused Gacha Coins are kept after the event and work in future machines.',
    '〓扭蛋初始概率公示〓': '〓Initial Draw Rates〓',
    '〓招募说明〓': '〓Recruitment Info〓', '〓招募规则〓': '〓Recruitment Rules〓', '〓基础概率〓': '〓Base Rates〓', '〓特殊说明〓': '〓Notes〓',
    '【常驻映像招募】为固定常驻活动': '[Standard Footage Recruitment] is a permanent banner',
    '※每10连招募必定会获得至少1张SR映像。': '※Every 10-pull guarantees at least 1 SR Footage.',
    '※在本招募内最多70次必定能通过保底100%获取一枚SSR映像。': '※Within 70 pulls on this banner, an SSR Footage is guaranteed.',
    '※每次获取到SSR映像时会重置保底累积次数。': '※The pity count resets whenever you get an SSR Footage.',
    '※完成主线获得特别纪念映像后该映像会自动加入招募池。': '※Special memorial Footage earned from the main story joins the pool automatically.',
    '※单抽次数会累积到综合保底次数。': '※Single pulls count toward pity.',
    '※剧情映像未触发相关剧情并获得该映像时，无法在卡池中抽出': '※Story Footage cannot be pulled until you have reached its story and obtained it.',
    '每次招募的同时会额外获得【外观券】': 'Every pull also gives [Appearance Tickets]',
    '〓若获得重复探索员〓': '〓Duplicate Salvagers〓', '〓若获得重复映像〓': '〓Duplicate Footage〓',
    '重复获得映像时，SSR映像每次会获得20个星尘，SR映像每次会获得15个星砂。': 'Duplicate Footage gives 20 Stardust (SSR) or 15 Star Sand (SR).',
    '【高级自选映像卡池】限时活动招募已开启。活动期间内限定自选SSR映像获取概率大幅提高。': '[Advanced Footage Selector] limited banner is open. Your chosen SSR Footage has a greatly increased rate.',
    '【新手自选映像卡池】限时活动招募已开启。活动期间内限定自选SSR映像获取概率大幅提高。': '[Newcomer Footage Selector] limited banner is open. Your chosen SSR Footage has a greatly increased rate.',
    '【初级自选映像卡池】限时活动招募已开启。活动期间内限定自选SSR映像获取概率大幅提高。': '[Basic Footage Selector] limited banner is open. Your chosen SSR Footage has a greatly increased rate.',
    '【常驻招募UP】限时活动招募已开启。活动期间内限定SSR探索员「桃」获取概率大幅提高至原先的6倍': '[Standard Recruitment UP] is open. SSR Salvager "Momo" has 6× her usual rate.',
    '【自选卡池】限时活动招募已开启。活动期间内限定自选SSR探索员获取概率大幅提高。': '[Selector Banner] limited banner is open. Your chosen SSR Salvager has a greatly increased rate.',
    '【新手自选卡池】限时活动招募已开启。活动期间内限定自选SSR探索员获取概率大幅提高。': '[Newcomer Selector Banner] limited banner is open. Your chosen SSR Salvager has a greatly increased rate.',
    '【拼布裁缝】限时活动招募已开启。活动期间内限定SSR探索员「丹」获取概率大幅提高。': '[Patchwork Tailor] limited banner is open. SSR Salvager "Deningha" has a greatly increased rate.',
    '【雾都侦探】限时活动招募已开启。活动期间内限定SSR探索员「莫」获取概率大幅提高。': '[Fog City Detective] limited banner is open. SSR Salvager "Molly" has a greatly increased rate.',
    '※每10连招募必定会获得至少1把SSR武器。': '※Every 10-pull guarantees at least 1 SSR weapon.',
    '※每10连招募必定会获得至少1名SR探索员。': '※Every 10-pull guarantees at least 1 SR Salvager.',
    '※在本招募内每次获得SSR映像时，有50%的概率为本期限定映像。': '※Each SSR Footage has a 50% chance to be the featured one.',
    '※在本招募内最多70次必定能通过保底100%获取本期限定映像。': '※The featured Footage is guaranteed within 70 pulls.',
    '※卡池在获取指定自选映像后关闭。': '※The banner closes once you get your chosen Footage.',
    '※单抽次数不会累积到综合保底次数。与【普通映像招募】【限定映像招募】的招募次数保底独立计算，互不影响。': "※Pulls here don't count toward shared pity; pity is separate from [Standard Footage] and [Limited Footage] banners.",
    '※在本招募内最多70次必定能通过保底100%获取一名SSR探索员。': '※An SSR Salvager is guaranteed within 70 pulls.',
    '※每次获取到SSR探索员时会重置保底累积次数。': '※The pity count resets whenever you get an SSR Salvager.',
    '※在本招募内每次获得SSR探索员时，有50%的概率为本期限定探索员。': '※Each SSR Salvager has a 50% chance to be the featured one.',
    '※在本招募内最多70次必定能通过保底100%获取本期限定探索员。': '※The featured Salvager is guaranteed within 70 pulls.',
    '※每次获取到限定探索员时会重置保底累积次数。': '※The pity count resets whenever you get the featured Salvager.',
    '※单抽次数不会累积到综合保底次数。与【普通招募】【限定招募】的招募次数保底独立计算，互不影响。': "※Pulls here don't count toward shared pity; pity is separate from [Standard] and [Limited] banners.",
    '※单抽次数会累积到综合保底次数。所有【限时活动招募】的招募次数保底完全共享，会一直累计在【限时活动招募】中，且与【普通招募】的招募次数保底独立计算，互不影响。': '※Pulls count toward pity. Pity is shared across all [Limited] banners and carries over, separate from the [Standard] banner.',
    '无论通过何种方式（包含但不限于招募、商城兑换、系统赠送等）获得重复SSR探索员，并且该探索员没有升至五星时，每次将转化为3个对应探索员的晋升凭证和16个星尘；第6次并且该探索员已经升至五星后，获得40个星尘。': 'A duplicate SSR Salvager (from any source) becomes 3 of her promotion tokens and 16 Stardust until she reaches 5 stars; after that, 40 Stardust.',
    '无论通过何种方式（包含但不限于招募、商城兑换、系统赠送等）获得重复SR探索员，并且该探索员没有升至五星时，每次将转化为3个对应探索员的晋升凭证和3个星尘；第6次并且该探索员已经升至五星后，获得12个星尘。': 'A duplicate SR Salvager (from any source) becomes 3 of her promotion tokens and 3 Stardust until she reaches 5 stars; after that, 12 Stardust.',
    '无论通过何种方式（包含但不限于招募、商城兑换、系统赠送等）获得重复SSR映像，并且该映像没有升至五星时，每次将转化为3个对应映像的晋升凭证和16个星尘；第6次并且该映像已经升至五星后，获得40个星尘。': 'A duplicate SSR Footage (from any source) becomes 3 of its promotion tokens and 16 Stardust until it reaches 5 stars; after that, 40 Stardust.',
    '无论通过何种方式（包含但不限于招募、商城兑换、系统赠送等）获得重复SR映像，并且该映像没有升至五星时，每次将转化为3个对应映像的晋升凭证和3个星尘；第6次并且该映像已经升至五星后，获得12个星尘。': 'A duplicate SR Footage (from any source) becomes 3 of its promotion tokens and 3 Stardust until it reaches 5 stars; after that, 12 Stardust.',
    '无论通过何种方式（包含但不限于招募、商城兑换、系统赠送等）获得重复SSR探索员，并且该探索员没有升至五星时，每次将转化为3个对应映像的晋升凭证和16个星尘；第6次并且该探索员已经升至五星后，获得40个星尘。': 'A duplicate SSR Salvager (from any source) becomes 3 promotion tokens and 16 Stardust until she reaches 5 stars; after that, 40 Stardust.',
    '无论通过何种方式（包含但不限于招募、商城兑换、系统赠送等）获得重复SR探索员，并且该探索员没有升至五星时，每次将转化为3个对应映像的晋升凭证和3个星尘；第6次并且该探索员已经升至五星后，获得12个星尘。': 'A duplicate SR Salvager (from any source) becomes 3 promotion tokens and 3 Stardust until she reaches 5 stars; after that, 12 Stardust.',
}
RATE_WORDS = {'SSR探索员': 'SSR Salvager', 'SR探索员': 'SR Salvager', 'SSR映像': 'SSR Footage', 'SR映像': 'SR Footage',
              '（含保底综合概率2.1%）': ' (2.1% including pity)', '基础映像': 'Base Footage', '自选UP映像': 'Selected UP Footage', '自选UP角色': 'Selected UP Salvager'}
HALLOWEEN_HELP = {
    '活动指南': 'Event Guide',
}
HALLOWEEN_BODY = ("<b>Event:</b>\n\n<b>1. Trick-or-Treat Candy Hunt:</b>\nDeep in the courtyard are three candies glowing with a strange light, said to be the ghosts' dearest treasures:\n"
                  "  <b><color=#008000>Green Candy</color></b>\n  <b><color=#8A2BE2>Purple Candy</color></b>\n  <b><color=#FFA500>Orange Candy</color></b>\n\n"
                  "They are all hidden behind the event stage bosses, waiting for brave Salvagers to find them!\n\n"
                  "<b>2. The Mysterious Ghost Badge:</b>\nCollect all three candies to make a <b>Colorful Candy Bag</b>! Open it for a <b><color=#8A2BE2>Ghost Badge</color></b>, the only currency for event rewards!\n\n"
                  "<b>3. Challenge! \"Netherworld Courtyard\":</b>\nEvery day the event screen gives you 2 <b>Event Stage Challenge Tickets</b> from the ghosts: their invitation to play!\n\n"
                  "    The ghosts hide in the courtyard; their glow and sounds help you find them.\n"
                  "    When you find one, open your profile at the top left, take out the camera and snap! Freeze their panicked faces!\n"
                  "    Photographed ghosts shyly drop their <b><color=#FFA500>power-up items</color></b> and run. Each item has its own powerful effect to help you beat strong enemies!\n\n"
                  "<b>Tip:</b> every item has surprising effects. Experiment and find your favorite way to catch ghosts!\n\n"
                  "<b>Note</b>: after each boss reward, the challenge ticket vanishes in a puff of smoke.\n\n")
HALLOWEEN_END_TREE = ("<b>4. Gifts under the Wishing Tree:</b>\nTake your <b><color=#8A2BE2>Ghost Badges</color></b> to the <b><color=#FFA500>Wishing Tree</color></b> in the top-left menu. "
                      "They say the ancient tree spirit answers wishes for badges with exclusive Halloween gifts!\n\nSo, got your courage and your camera ready?\n\n<b>This Halloween, let's go ghost-hunting together!</b>")
HALLOWEEN_END_POT = ("<b>4. Halloween Gifts from the Cauldron:</b>\nTake your <b><color=#8A2BE2>Ghost Badges</color></b> to the <b><color=#FFA500>Cauldron</color></b>, open the <b>Halloween Event Shop</b> and pick your favorite Halloween gifts!\n\n"
                     "You can also press <b>Reward Exchange</b> at the bottom of the event page to open the shop directly.\n\nSo, got your courage and your camera ready?\n\n<b>This Halloween, let's go ghost-hunting together!</b>")


def long_text(x, tm):
    if x.startswith('<b>活动内容：</b>'):
        return HALLOWEEN_BODY + (HALLOWEEN_END_POT if '坩埚' in x else HALLOWEEN_END_TREE)
    out = []
    for line in x.split('\n'):
        s = line.strip()
        if not s:
            out.append(line); continue
        if s in LINES:
            out.append(LINES[s]); continue
        if s in tm:
            out.append(tm[s]); continue
        m = re.fullmatch(r'(.+?)x(\d+) ([\d.]+%)', s)
        if m:
            nm = NAMES.get(m.group(1)) or tm.get(m.group(1)) or MANUAL.get(m.group(1)) or m.group(1)
            out.append(f'{nm} x{m.group(2)} {m.group(3)}'); continue
        m = re.fullmatch(r'(SSR|SR)(探索员|映像)获得【外观券】x(\d+)', s)
        if m:
            out.append(f'{m.group(1)} {"Salvager" if m.group(2) == "探索员" else "Footage"}: +{m.group(3)} [Appearance Tickets]'); continue
        m = re.fullmatch(r'打开后可自行选择以下物品之一：(.+)', s)
        if m:
            parts = re.findall(r'\[(.+?)\]x(\d+)', m.group(1))
            out.append('Open to choose one of: ' + ', '.join(f'[{NAMES.get(a) or tm.get(a) or a}]x{b}' for a, b in parts)); continue
        if '/' in s:
            head, _, rest = s.rpartition('：') if '：' in s else ('', '', s)
            names = []
            for n in rest.split('/'):
                if '，在获取SSR探索员时' in n:
                    n0 = n.split('，')[0]
                    names.append(NAMES.get(n0) or CHAR.get(n0, n0))
                    names.append('; when an SSR Salvager is pulled, Momo is 6× more likely (Momo 50%, others 8.33% each)')
                    continue
                names.append(RATE_WORDS.get(n) or CHAR.get(n) or NAMES.get(n) or tm.get(n) or n)
            out.append((RATE_WORDS.get(head, head) + ': ' if head else '') + '/'.join(names).replace('/; ', '; ')); continue
        y = s
        for k, v in RATE_WORDS.items():
            y = y.replace(k, v)
        out.append(y)
    return '\n'.join(out)


_rules = rules


def rules(x, tm):  # noqa: F811
    y = _rules(x, tm)
    if y is None and ('\n' in x or len(x) > 40 or x.startswith('打开后可自行选择')):
        y = long_text(x, tm)
    m = re.fullmatch(r'(SSR|SR)映像自选礼包(I+)', x)
    if y is None and m:
        y = f'{m.group(1)} Footage Selector Package {m.group(2)}'
    m = re.fullmatch(r'制作上升风场\[2\](\d+)次', x)
    if y is None and m:
        n = int(m.group(1)); y = 'Craft Updraft [2] ' + ('once' if n == 1 else f'{n} times')
    if y is None and x == '常驻招募-粉红偶像UP':
        y = 'Standard Recruitment - Pretty Idol UP'
    return y


if __name__ == '__main__':
    rows = json.load(open(sys.argv[1], encoding='utf-8'))
    tm = json.load(open(sys.argv[2], encoding='utf-8'))
    names = json.load(open(sys.argv[3], encoding='utf-8')) if len(sys.argv) > 4 else {}
    out, missing = build(rows, tm, names)
    json.dump(out, open(sys.argv[-1], 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    u = sorted(set(missing), key=len)
    print(len(out), 'rows;', len(u), 'segments still Chinese')
    json.dump(u, open(sys.argv[-1] + '.missing.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=0)


