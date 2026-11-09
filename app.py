import os
import io
import gc
import json
import time
import base64
import requests
from flask import Flask, request, abort
from PIL import Image

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    MessagingApiBlob,
    ReplyMessageRequest,
    TextMessage,
    FlexMessage,
    FlexContainer,
    QuickReply,
    QuickReplyItem,
    MessageAction,
    CameraAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, ImageMessageContent

app = Flask(__name__)

CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# মেমরি স্টোরেজ
user_languages = {}
user_countries = {}
user_last_scans = {}
user_scan_history = {}

# সম্পূর্ণ স্থানীয়কৃত টেক্সট কনফিগারেশন (English, Bengali, Chinese, Japanese, Indonesian, Arabic)
I18N = {
    "English": {
        "status_halal": "✅ HALAL",
        "status_haram": "❌ HARAM",
        "status_syubhah": "⚠️ SYUBHAH (Doubtful)",
        "label_reason": "Observation & Reason:",
        "label_items": "Detected Ingredients:",
        "label_alternatives": "💡 Recommended Halal Alternatives:",
        "label_hadith_title": "📜 Warning from Hadith:",
        "hadith_text": "The Prophet ﷺ said: 'What is lawful is clear and what is unlawful is clear, and between them are matters that are doubtful... So he who guards against doubtful matters clears himself in regard to his religion and his honor.' [Sahih al-Bukhari: 52, Sahih Muslim: 1599]",
        "label_advice_title": "💡 Important Recommendation:",
        "cam_btn": "📷 Open Camera",
        "cam_prompt": "Tap '📷 Open Camera' below to take a clear picture of the ingredient list:",
        "lang_confirm": "✅ Settings updated!\n📍 Country: {country}\n🌐 Language: English\n\nPlease send a clear photo of the ingredient list.",
        "country_selected": "📍 Country selected: {country}\nLanguage automatically set to English. You can also pick another language below:",
        "default_prompt": "Please choose from the menu or send a photo of the ingredients list.",
        "select_country_first": "🌍 Please select your country or destination:",
        "btn_explain": "❓ Explain Ingredients",
        "btn_history": "📜 Scan History",
        "history_title": "📋 Your Food Check History (Total: {count}):\n",
        "history_empty": "You have no food scan history yet. Send an ingredient image to start checking.",
        "history_hint": "\n👉 Type the item number (e.g. 1, 2) to view the full result card again.",
        "counter_text": "📊 Total Checked: {total} (Item #{item_no})"
    },
    "Bengali": {
        "status_halal": "✅ HALAL (হালাল)",
        "status_haram": "❌ HARAM (হারাম)",
        "status_syubhah": "⚠️ SYUBHAH (সন্দেহজনক)",
        "label_reason": "পর্যবেক্ষণ ও কারণ:",
        "label_items": "শনাক্তকৃত উপাদান:",
        "label_alternatives": "💡 হালাল বিকল্প সাজেশন:",
        "label_hadith_title": "📜 হাদিসের আলোকে সতর্কতা:",
        "hadith_text": "রাসূলুল্লাহ ﷺ বলেছেন: 'হালালও স্পষ্ট এবং হারামও স্পষ্ট। আর এ দুয়ের মাঝে রয়েছে বহু সন্দেহজনক বিষয়... যে ব্যক্তি সন্দেহজনক বিষয় থেকে নিজেকে বাঁচিয়ে রাখল, সে তার দ্বীন ও সম্মান রক্ষা করল।' [সহিহ বুখারি: ৫২, সহিহ মুসলিম: ১৫৯৯]",
        "label_advice_title": "💡 গুরুত্বপূর্ণ পরামর্শ:",
        "cam_btn": "📷 ক্যামেরা খুলুন",
        "cam_prompt": "নিচের '📷 ক্যামেরা খুলুন' বাটনে চাপ দিয়ে পণ্যের উপাদানের স্পষ্ট ছবি তুলুন:",
        "lang_confirm": "✅ সেটিংস সম্পন্ন হয়েছে!\n📍 দেশ: {country}\n🌐 ভাষা: বাংলা\n\nএখন খাবারের উপাদানের স্পষ্ট ছবি পাঠান।",
        "country_selected": "📍 দেশ নির্বাচিত: {country}\nভাষা বাংলায় সেট করা হয়েছে। চাইলে নিচে অন্য ভাষাও বেছে নিতে পারেন:",
        "default_prompt": "মেনু থেকে অপশন বেছে নিন অথবা পণ্যের উপাদানের স্পষ্ট ছবি পাঠান।",
        "select_country_first": "🌍 প্রথমে আপনার অবস্থান বা ভ্রমণের দেশ নির্বাচন করুন:",
        "btn_explain": "❓ উপাদান বিস্তারিত জানাও",
        "btn_history": "📜 হিস্ট্রি তালিকা",
        "history_title": "📋 আপনার চেক করা খাবারের ইতিহাস (মোট: {count}টি):\n",
        "history_empty": "আপনার এখনও কোনো খাবারের স্ক্যান ইতিহাস সংরক্ষিত নেই। উপাদানের ছবি পাঠিয়ে চেক করুন।",
        "history_hint": "\n👉 যে কোনো খাবারের বিস্তারিত কার্ড দেখতে তার নম্বর লিখে পাঠান (যেমন: 1, 2)।",
        "counter_text": "📊 মোট চেক করা হয়েছে: {total}টি (আইটেম #{item_no})"
    },
    "Chinese": {
        "status_halal": "✅ 清真 (HALAL)",
        "status_haram": "❌ 非清真 (HARAM)",
        "status_syubhah": "⚠️ 疑似/存疑 (SYUBHAH)",
        "label_reason": "判断原因与分析:",
        "label_items": "检测到的主要配料:",
        "label_alternatives": "💡 推荐清真替代品:",
        "label_hadith_title": "📜 圣训警示:",
        "hadith_text": "先知穆罕默德 ﷺ 说：‘合法的（清真）是明白的，非法的也是明白的，在这两者之间有许多疑似的事物...避开疑似事物的人，确已保全了他的宗教和名节。’ [布哈里圣训: 52, 穆斯林圣训: 1599]",
        "label_advice_title": "💡 重要建议:",
        "cam_btn": "📷 打开相机",
        "cam_prompt": "点击下方‘📷 打开相机’按钮，清晰拍摄食品包装上的配料表:",
        "lang_confirm": "✅ 设置已完成！\n📍 国家: {country}\n🌐 语言: 简体中文\n\n请发送食品配料表清晰照片。",
        "country_selected": "📍 已选择国家: {country}\n语言已自动设为中文。您也可以在下方更改语言:",
        "default_prompt": "请从菜单选择功能，或直接发送配料表图片进行检查。",
        "select_country_first": "🌍 请先选择您所在的国家或目的地:",
        "btn_explain": "❓ 详细成分分析",
        "btn_history": "📜 检查历史",
        "history_title": "📋 您的食品检查历史记录 (总计: {count}):\n",
        "history_empty": "暂无检查记录。请拍摄并发送食品配料表照片开始使用。",
        "history_hint": "\n👉 发送对应编号（如：1, 2）可重新查看完整结果卡片。",
        "counter_text": "📊 已检查总数: {total} (第 #{item_no} 件)"
    },
    "Japanese": {
        "status_halal": "✅ ハラール (HALAL)",
        "status_haram": "❌ ハラーム (HARAM)",
        "status_syubhah": "⚠️ シュブハ (疑わしい)",
        "label_reason": "判定理由・観察:",
        "label_items": "検出された原材料:",
        "label_alternatives": "💡 推奨されるハラール代替品:",
        "label_hadith_title": "📜 ハディースによる教え:",
        "hadith_text": "預言者ムハンマド ﷺ は仰いました:『合法（ハラール）なものは明白であり、非合法（ハラーム）なものも明白である。そして両者の間には疑わしい事柄がある...疑わしいものを避ける者は、自らの宗教と名誉を守ることになる。』[サヒーフ・ブハーリー: 52, サヒーフ・ムスリム: 1599]",
        "label_advice_title": "💡 重要なお知らせ:",
        "cam_btn": "📷 カメラを起動",
        "cam_prompt": "下の『📷 カメラを起動』ボタンを押して原材料名の写真を撮影してください:",
        "lang_confirm": "✅ 設定が完了しました！\n📍 対象国: {country}\n🌐 言語: 日本語\n\n原材料名の写真を送信してください。",
        "country_selected": "📍 国を選択しました: {country}\n言語が日本語に設定されました。別の言語を選ぶことも可能です:",
        "default_prompt": "メニューから選択するか、商品の原材料名（原材料表示）の写真を送信してください。",
        "select_country_first": "🌍 まず対象の国を選択してください:",
        "btn_explain": "❓ 成分の詳細解説",
        "btn_history": "📜 履歴一覧",
        "history_title": "📋 食品判定履歴 (合計: {count}件):\n",
        "history_empty": "まだ履歴がありません。原材料の写真を送信して判定を開始してください。",
        "history_hint": "\n👉 番号（例: 1, 2）を送信すると、詳細結果を再確認できます。",
        "counter_text": "📊 チェック済み総数: {total}件 (アイテム #{item_no})"
    },
    "Indonesian": {
        "status_halal": "✅ HALAL",
        "status_haram": "❌ HARAM",
        "status_syubhah": "⚠️ SYUBHAH (Meragukan)",
        "label_reason": "Alasan & Observasi:",
        "label_items": "Bahan Terdeteksi:",
        "label_alternatives": "💡 Alternatif Halal Disarankan:",
        "label_hadith_title": "📜 Peringatan Hadits:",
        "hadith_text": "Rasulullah ﷺ bersabda: 'Sesungguhnya yang halal itu jelas dan yang haram itu jelas, dan di antara keduanya ada perkara-perkara syubhat... Barangsiapa menjauhi syubhat, maka ia telah membersihkan agama dan kehormatannya.' [HR. Bukhari: 52, Muslim: 1599]",
        "label_advice_title": "💡 Rekomendasi Penting:",
        "cam_btn": "📷 Buka Kamera",
        "cam_prompt": "Tekan tombol '📷 Buka Kamera' di bawah untuk mengambil foto komposisi:",
        "lang_confirm": "✅ Pengaturan selesai!\n📍 Negara: {country}\n🌐 Bahasa: Bahasa Indonesia\n\nSilakan kirim foto komposisi makanan.",
        "country_selected": "📍 Negara dipilih: {country}\nBahasa telah diatur. Anda juga dapat memilih bahasa lain di bawah ini:",
        "default_prompt": "Silakan pilih menu atau kirim foto daftar komposisi bahan.",
        "select_country_first": "🌍 Silakan pilih negara Anda terlebih dahulu:",
        "btn_explain": "❓ Jelaskan Bahan",
        "btn_history": "📜 Riwayat Cek",
        "history_title": "📋 Riwayat Pemeriksaan Makanan (Total: {count}):\n",
        "history_empty": "Belum ada riwayat pemeriksaan makanan tersimpan. Kirim foto bahan untuk memulai.",
        "history_hint": "\n👉 Ketik nomor item (misal: 1, 2) untuk melihat kartu hasil lengkap kembali.",
        "counter_text": "📊 Total Diperiksa: {total} (Item #{item_no})"
    },
    "Arabic": {
        "status_halal": "✅ حلال (HALAL)",
        "status_haram": "❌ حرام (HARAM)",
        "status_syubhah": "⚠️ شبهة (SYUBHAH)",
        "label_reason": "الملاحظة والسبب:",
        "label_items": "المكونات المكتشفة:",
        "label_alternatives": "💡 البدائل الحلال المقترحة:",
        "label_hadith_title": "📜 التحذير النبوي الشريف:",
        "hadith_text": "قال رسول الله ﷺ: 'إن الحلال بيّن وإن الحرام بيّن، وبينهما أمور مشتبهات... فمن اتقى الشبهات فقد استبرأ لدينه وعِرضه.' [صحيح البخاري: ٥٢، صحيح مسلم: ١٥٩٩]",
        "label_advice_title": "💡 نصيحة هامة:",
        "cam_btn": "📷 فتح الكاميرا",
        "cam_prompt": "اضغط على زر '📷 فتح الكاميرا' بالأسفل لتصوير قائمة المكونات بوضوح:",
        "lang_confirm": "✅ تم ضبط الإعدادات بنجاح!\n📍 الدولة: {country}\n🌐 اللغة: العربية\n\nيرجى إرسال صورة واضحة لقائمة المكونات.",
        "country_selected": "📍 تم تحديد الدولة: {country}\nتم تعيين اللغة. يمكنك أيضاً تغيير اللغة بالأسفل:",
        "default_prompt": "يرجى الاختيار من القائمة أو إرسال صورة واضحة لقائمة المكونات.",
        "select_country_first": "🌍 يرجى اختيار الدولة أولاً:",
        "btn_explain": "❓ تفاصيل المكونات",
        "btn_history": "📜 سجل الفحص",
        "history_title": "📋 سجل فحص الأطعمة الخاص بك (الإجمالي: {count}):\n",
        "history_empty": "لا يوجد سجل فحص حتى الآن. يرجى إرسال صورة للمكونات للبدء.",
        "history_hint": "\n👉 أرسل رقم العنصر (مثال: 1, 2) لإعادة عرض بطاقة النتيجة التفصيلية.",
        "counter_text": "📊 إجمالي العناصر المفحوصة: {total} (عنصر #{item_no})"
    }
}

# সম্পূর্ণ দেশভিত্তিক তথ্য ভাণ্ডার (বহুভাষিক)
COUNTRY_DETAILS = {
    "Japan": {
        "title": "JP HALAL FOOD CHECKER 🇯🇵",
        "advice_app": {
            "English": "This bot is a free AI tool. For 100% verified accuracy in Japan, we highly recommend using the officially verified paid app 'Halal Japan'.",
            "Bengali": "আমাদের এই বটটি একটি ফ্রি এআই টুল। জাপানে শতভাগ নির্ভরযোগ্য তথ্যের জন্য ভেরিফাইড পেইড অ্যাপ 'Halal Japan' ব্যবহারের অনুরোধ করা হচ্ছে।",
            "Chinese": "本机器人为免费AI工具。如需在日本获取100%经过人工核实的安全信息，强烈建议使用官方认证付费App『Halal Japan』。",
            "Japanese": "当ボットは無料AIツールです。日本国内での100%確実な安全確認には、公式認証アプリ『Halal Japan』(有料)のご利用を推奨します。"
        },
        "haram": {
            "English": "🚫 [Japan 🇯🇵] Haram Ingredients:\n• 豚肉, ポーク (Pork)\n• 豚脂, ラード (Pork Fat / Lard)\n• ハム, ベーコン, 豚骨エキス (Ham, Bacon, Pork bone extract)\n• 豚ゼラチン (Pork gelatin)\n• 牛肉, 鶏肉 (Non-halal beef/chicken)\n• 動物性油脂 (Animal fats)\n• アルコール, 洋酒, 酒精 (Alcohol, Spirits)\n• 酒, 料理酒, 味醂 (Mirin / Cooking Sake)",
            "Bengali": "🚫 [জাপান 🇯🇵] নিশ্চিত হারাম উপাদান:\n• 豚肉、ポーク | শুকরের মাংস\n• 豚脂肪、豚脂、ラード | শুকরের চর্বি / লার্ড\n• ハム、ベーコン、豚骨エキス | হ্যাম, বেকন, শুকরের নির্যাস\n• 豚ゼラチン | শুকরের জেলাটিন\n• アルコール、料理酒、味醂 (みりん) | রান্নার মদ, মিরিন",
            "Chinese": "🚫 [日本 🇯🇵] 严禁成分 (Haram):\n• 豚肉、ポーク (猪肉)\n• 豚脂、ラード (猪油/白油)\n• ハム、ベーコン、豚骨エキス (火腿、培根、猪骨提取物)\n• 豚ゼラチン (猪明胶)\n• 牛肉、鶏肉 (未经清真屠宰的肉类)\n• 動物性油脂、混合油脂 (动物油脂)\n• アルコール、洋酒、酒精 (酒精、食用酒精)\n• 酒、料理酒、味醂/みりん (日本料理酒、味霖)"
        },
        "syubhah": {
            "English": "⚠️ [Japan 🇯🇵] Syubhah (Doubtful):\n• 乳化剤 (Emulsifier / E471) - unless plant-based\n• ショートニング (Shortening)\n• マーガリン (Margarine)\n• 加工油脂 (Processed oils)\n• ゼラチン, コラーゲン (Gelatin/Collagen - unless fish origin)",
            "Bengali": "⚠️ [জাপান 🇯🇵] সন্দেহজনক উপাদান (Syubhah):\n• 乳化剤 (ইমালসিফায়ার E471) - উৎস অস্পষ্ট হলে\n• ショートニング (শর্টনিং)\n• マーガリン (মার্জারিন)\n• ゼラチン、コラーゲン (জেলাটিন)",
            "Chinese": "⚠️ [日本 🇯🇵] 存疑成分 (Syubhah):\n• 乳化剤 (乳化剂 / E471) - 未注明植物来源时\n• ショートニング (起酥油)\n• マーガリン (人造奶油)\n• 加工油脂 (加工油脂)\n• ゼラチン、コラーゲン (明胶/胶原蛋白 - 非鱼源)"
        },
        "tips": {
            "English": "🛒 [Japan 🇯🇵] Shopping Tips:\n1. Look for '植物性' or '植物油脂' (Plant-based) on breads.\n2. Avoid western pastries with '洋酒' (Liquor).\n3. Check Onigiri rice balls for '味醂' (Mirin).",
            "Bengali": "🛒 [জাপান 🇯🇵] কেনাকাটার টিপস:\n১. পাউরুটিতে '植物性' বা '植物油脂' লেখা থাকলে নিরাপদ।\n২. মিষ্টি ও কেক কেনার সময় '洋酒' পরিহার করুন।\n৩. ওনিগিরিতে 'みりん' (মিরিন) চেক করুন।",
            "Chinese": "🛒 [日本 🇯🇵] 购物小贴士:\n1. 购买面包时注意是否有‘植物性’或‘植物油脂’标识。\n2. 糕点甜品中常含有‘洋酒’或‘酒精’，需仔细甄别。\n3. 部分便利店饭团使用‘味醂（みりん）’调味，请留意。"
        },
        "info": {
            "English": "ℹ️ [Japan 🇯🇵] Guide:\n• Take a flat, clear photo of the '原材料名' (Ingredients) table.\n• Use 'Halal Japan' paid app for full manufacturer verification.",
            "Bengali": "ℹ️ [জাপান 🇯🇵] নির্দেশিকা:\n• উপাদানের তালিকার (原材料名) সোজা ছবি পাঠান।\n• ১০০% নিরাপত্তার জন্য 'Halal Japan' অ্যাপ দেখুন।",
            "Chinese": "ℹ️ [日本 🇯🇵] 指南:\n• 请清晰拍摄包装上的‘原材料名’部分。\n• 建议配合『Halal Japan』官方App核实生产线交叉污染。"
        }
    },
    "USA": {
        "title": "US HALAL FOOD CHECKER 🇺🇸",
        "advice_app": {
            "English": "This bot is a free AI tool. For 100% verified certainty in the USA, consider checking with apps like 'Scan Halal' or 'Crescent Halal'.",
            "Bengali": "আমাদের এই বটটি একটি ফ্রি এআই টুল। যুক্তরাষ্ট্রে ১০০% নির্ভুলতার জন্য 'Scan Halal' অথবা 'Crescent Halal' অ্যাপ ব্যবহার করুন।",
            "Chinese": "本机器人为免费AI工具。在美国获取100%认证信息，建议参考『Scan Halal』或伊斯兰食品营养委员会(IFANCA)认证。"
        },
        "haram": {
            "English": "🚫 [USA 🇺🇸] Haram Ingredients:\n• Pork, Bacon, Ham, Pork Lard\n• Pork Gelatin / Animal Gelatin\n• Carmine / Cochineal Extract (E120)\n• Pure Vanilla Extract (Contains 35%+ alcohol by FDA law)\n• Brewer's Yeast (from beer brewing)\n• Cooking wines, Rum flavorings",
            "Bengali": "🚫 [USA 🇺🇸] নিশ্চিত হারাম উপাদান:\n• Pork, Bacon, Ham, Lard\n• Pork Gelatin / Gelatin\n• Carmine / Cochineal Extract (E120)\n• Pure Vanilla Extract (৩৫%+ অ্যালকোহল থাকে)\n• Wine, Rum flavoring",
            "Chinese": "🚫 [美国 🇺🇸] 严禁成分 (Haram):\n• 猪肉、培根、火腿、猪油 (Pork, Bacon, Lard)\n• 猪明胶 (Pork Gelatin)\n• 胭脂红/胭脂虫红 (Carmine / E120)\n• 纯香草精 (Pure Vanilla Extract - FDA规定含35%以上酒精)\n• 啤酒酵母 (Brewer's Yeast)\n• 料理酒、含酒精香精"
        },
        "syubhah": {
            "English": "⚠️ [USA 🇺🇸] Syubhah (Doubtful):\n• Mono and diglycerides (E471)\n• Shortening (unless marked 100% vegetable)\n• Whey powder / Animal Rennet in Cheese\n• Natural & Artificial Flavors (alcohol carriers)",
            "Bengali": "⚠️ [USA 🇺🇸] সন্দেহজনক উপাদান (Syubhah):\n• Mono and diglycerides (E471)\n• Shortening\n• Whey powder / Animal Rennet\n• Natural & Artificial Flavors",
            "Chinese": "⚠️ [美国 🇺🇸] 存疑成分 (Syubhah):\n• 单双甘油酯 (E471 - 动植物来源不明)\n• 起酥油 (Shortening - 未注明全植物)\n• 乳清粉/奶酪动物凝乳酶 (Rennet)\n• 天然与人工香精 (可能使用酒精作为溶剂)"
        },
        "tips": {
            "English": "🛒 [USA 🇺🇸] Shopping Tips:\n1. Look for 'Kosher Pareve' (OU Pareve) which guarantees meat/alcohol free.\n2. Check gummy candies and marshmallows for Pork Gelatin.\n3. Buy '100% Vegetable Shortening' for baking.",
            "Bengali": "🛒 [USA 🇺🇸] কেনাকাটার টিপস:\n১. Kosher Pareve সিল থাকলে মাংস ও অ্যালকোহলমুক্ত থাকে।\n২. মার্শমেলো ও গামিতে জেলাটিন চেক করুন।",
            "Chinese": "🛒 [美国 🇺🇸] 购物小贴士:\n1. 认准‘Kosher Pareve’(正统犹太素食洁食)标识，不含肉类和酒精。\n2. 棉花糖、软糖通常含猪明胶，请特别注意。\n3. 烘焙食品认准‘100% Vegetable Shortening’。"
        },
        "info": {
            "English": "ℹ️ [USA 🇺🇸] Guide:\n• Take a clear picture of the 'Ingredients' section on the FDA nutrition label.",
            "Bengali": "ℹ️ [USA 🇺🇸] নির্দেশিকা:\n• প্যাকেটের 'Ingredients' অংশের সোজা ছবি স্ক্যান করুন।",
            "Chinese": "ℹ️ [美国 🇺🇸] 指南:\n• 请清晰拍摄FDA营养标签下方的‘Ingredients’部分。"
        }
    },
    "China": {
        "title": "CN HALAL FOOD CHECKER 🇨🇳",
        "advice_app": {
            "English": "This bot is a free AI tool. In China, prioritize items with official 'Green Halal (清真)' certificates.",
            "Bengali": "চীনে খাদ্যের নিশ্চয়তার জন্য 'Green Halal (清真)' লোগো ও সার্টিফিকেট অনুসরণ করুন।",
            "Chinese": "本机器人为免费AI工具。在中国境内选购食品，请认准中国伊斯兰教协会或各省市伊协认证的‘清真 (Halal)’标志。"
        },
        "haram": {
            "English": "🚫 [China 🇨🇳] Haram Ingredients:\n• 猪肉, 猪油, 猪脂 (Pork & Lard)\n• 猪血, 鸭血 (Blood curds)\n• 料酒, 黄酒, 白酒 (Cooking wine & Liquor)\n• 鸡精, 浓汤宝 (Non-halal broths)\n• 明胶, 阿胶 (Gelatin & Donkey-hide gelatin)",
            "Bengali": "🚫 [চীন 🇨🇳] নিশ্চিত হারাম উপাদান:\n• 猪肉、猪油 (শুকরের মাংস ও চর্বি)\n• 猪血、鸭血 (রক্তজাত খাবার)\n• 料酒、黄酒、白酒 (চীনা রান্নার মদ)\n• 鸡精、浓汤宝 (অ-হালাল ব্রোথ)",
            "Chinese": "🚫 [中国 🇨🇳] 严禁成分 (Haram):\n• 猪肉、猪油、猪脂、猪皮、猪肉浸膏\n• 猪血、鸭血、血旺等血液制品\n• 料酒、黄酒、白酒、花雕酒、米酒、食用酒精\n• 非清真鸡精、鸡汁、浓汤宝\n• 明胶、阿胶 (驴皮胶)"
        },
        "syubhah": {
            "English": "⚠️ [China 🇨🇳] Syubhah (Doubtful):\n• 起酥油 (Shortening)\n• 人造奶油, 人造黄油 (Margarine)\n• 乳化剂 (Emulsifier / E471)\n• 食用香精 (Flavors)",
            "Bengali": "⚠️ [চীন 🇨🇳] সন্দেহজনক উপাদান (Syubhah):\n• 起酥油 (শর্টনিং)\n• 人造奶油 (মার্জারিন)\n• 乳化剂 (ইমালসিফায়ার E471)",
            "Chinese": "⚠️ [中国 🇨🇳] 存疑成分 (Syubhah):\n• 起酥油 (可能含有动物油脂)\n• 人造奶油、人造黄油 (植脂或动脂混炼)\n• 乳化剂、单双甘油脂肪酸酯\n• 食用香精 (香精载体可能含醇)"
        },
        "tips": {
            "English": "🛒 [China 🇨🇳] Shopping Tips:\n1. Look for the green '清真' logo.\n2. Instant noodles often use '料酒' (cooking wine) in sauce packets.",
            "Bengali": "🛒 [চীন 🇨🇳] কেনাকাটার টিপস:\n১. প্যাকেটের গায়ে সবুজ '清真' সিল আছে কি না দেখুন।\n২. নুডুলসের সসে '料酒' থাকতে পারে।",
            "Chinese": "🛒 [中国 🇨🇳] 购物小贴士:\n1. 优先选购带有绿色‘清真’标识的正规食品。\n2. 方便面与自热火锅的酱包中极常含有‘料酒’，务必检查。"
        },
        "info": {
            "English": "ℹ️ [China 🇨🇳] Guide:\n• Take a photo of the '配料' or '配料表' (Ingredients).",
            "Bengali": "ℹ️ [চীন 🇨🇳] নির্দেশিকা:\n• উপাদানের তালিকার (配料表) সোজা ছবি পাঠান।",
            "Chinese": "ℹ️ [中国 🇨🇳] 指南:\n• 请清晰拍摄食品包装背面的‘配料’或‘配料表’。"
        }
    },
    "Korea": {
        "title": "KR HALAL FOOD CHECKER 🇰🇷",
        "advice_app": {
            "English": "For 100% verified accuracy in South Korea, consider using apps like 'Mufko' or 'KMF Halal'.",
            "Bengali": "দক্ষিণ কোরিয়ায় শতভাগ নিশ্চয়তার জন্য 'Mufko' অথবা 'KMF Halal' অ্যাপ ব্যবহার করুন।",
            "Chinese": "在韩国请认准KMF清真认证，或使用韩国本地开发的『Mufko』App。"
        },
        "haram": {
            "English": "🚫 [Korea 🇰🇷] Haram Ingredients:\n• 돼지고기 (Pork)\n• 돈지 / 라드 (Pork Fat / Lard)\n• 햄, 베이컨 (Ham, Bacon)\n• 맛술, 미림 (Cooking wine / Mirin)\n• 청주, 주정 (Alcohol / Spirits in sauces)\n• 동물성유지 (Animal fat)",
            "Bengali": "🚫 [কোরিয়া 🇰🇷] নিশ্চিত হারাম উপাদান:\n• 돼지고기 (শুকরের মাংস)\n• 돈지 / 라드 (লার্ড)\n• 맛술, 미림 (রান্নার মদ)\n• 주정 (অ্যালকোহল)",
            "Chinese": "🚫 [韩国 🇰🇷] 严禁成分 (Haram):\n• 돼지고기 (猪肉)\n• 돈지 / 라드 (猪油)\n• 햄, 베이컨 (火腿、培根)\n• 맛술, 미림 (料酒、味霖)\n• 청주, 주정 (清酒、酒精 - 辣酱中极常见)\n• 동물성유지 (动物油脂)"
        },
        "syubhah": {
            "English": "⚠️ [Korea 🇰🇷] Syubhah (Doubtful):\n• 쇼트닝 (Shortening)\n• 마가린 (Margarine)\n• 유화제 (Emulsifier / E471)\n• 가공유지 (Processed oils)",
            "Bengali": "⚠️ [কোরিয়া 🇰🇷] সন্দেহজনক উপাদান (Syubhah):\n• 쇼트닝 (শর্টনিং)\n• 유화제 (ইমালসিফায়ার)\n• 가공유지 (প্রক্রিয়াজাত চর্বি)",
            "Chinese": "⚠️ [韩国 🇰🇷] 存疑成分 (Syubhah):\n• 쇼트닝 (起酥油)\n• 마가린 (人造黄油)\n• 유화제 (乳化剂)\n• 가공유지 (加工油脂)"
        },
        "tips": {
            "English": "🛒 [Korea 🇰🇷] Shopping Tips:\n1. Look for '식물성유지' (Vegetable oil).\n2. Ramyun (라면) soups very often contain pork extract.",
            "Bengali": "🛒 [কোরিয়া 🇰🇷] কেনাকাটার টিপস:\n১. প্যাকেটে 식물성유지 লেখা থাকলে নিরাপদ।\n২. রামিয়নের স্যুপে শুকর থাকে কি না দেখুন।",
            "Chinese": "🛒 [韩国 🇰🇷] 购物小贴士:\n1. 认准‘식물성유지 (植物油脂)’标识。\n2. 韩国泡面（라면）汤粉包绝大多数含牛猪肉提取物，须格外小心。"
        },
        "info": {
            "English": "ℹ️ [Korea 🇰🇷] Guide:\n• Take a picture of '원재료명' (Ingredients).",
            "Bengali": "ℹ️ [কোরিয়া 🇰🇷] নির্দেশিকা:\n• উপাদানের তালিকার (원재료명) স্পষ্ট ছবি পাঠান।",
            "Chinese": "ℹ️ [韩国 🇰🇷] 指南:\n• 请清晰拍摄包装背面的‘원재료명’（原材料名）部分。"
        }
    },
    "Bangladesh": {
        "title": "BD HALAL FOOD CHECKER 🇧🇩",
        "advice_app": {
            "English": "In Bangladesh, prioritize products with Islamic Foundation Bangladesh & BSTI Halal certificates.",
            "Bengali": "বাংলাদেশে শতভাগ নিশ্চয়তার জন্য ইসলামিক ফাউন্ডেশন ও বিএসটিআই হালাল লোগো অনুসরণ করুন।",
            "Chinese": "在孟加拉国，请优先认准孟加拉伊斯兰基金会或BSTI清真认证标志。"
        },
        "haram": {
            "English": "🚫 [Bangladesh 🇧🇩] Haram Ingredients:\n• Pork, Bacon, Lard (in imported snacks)\n• Non-halal Gelatin\n• Carmine (E120)\n• Alcohol, Rum flavoring",
            "Bengali": "🚫 [বাংলাদেশ 🇧🇩] নিশ্চিত হারাম উপাদান:\n• পর্ক, বেকন, হ্যাম, লার্ড (আমদানিকৃত খাদ্যে)\n• অ-হালাল প্রাণিজ জেলাটিন\n• অ্যালকোহল, রাম এসেন্স\n• ক্যারমাইন / কোচিনিল (E120)",
            "Chinese": "🚫 [孟加拉 🇧🇩] 严禁成分 (Haram):\n• 进口零食中的猪肉、猪油成分\n• 非清真明胶 (Gelatin)\n• 胭脂红 (E120)\n• 酒精、朗姆酒香精"
        },
        "syubhah": {
            "English": "⚠️ [Bangladesh 🇧🇩] Syubhah (Doubtful):\n• Emulsifiers (E471, E472)\n• Bakery Shortening & Margarine\n• Cheese Rennet & Whey powder",
            "Bengali": "⚠️ [বাংলাদেশ 🇧🇩] সন্দেহজনক উপাদান (Syubhah):\n• ইমালসিফায়ার (E471, E472)\n• শর্টনিং ও মার্জারিন\n• পনিরের রেনেট ও হুই পাউডার",
            "Chinese": "⚠️ [孟加拉 🇧🇩] 存疑成分 (Syubhah):\n• 乳化剂 (E471, E472)\n• 烘焙起酥油与人造奶油\n• 奶酪凝乳酶与乳清粉"
        },
        "tips": {
            "English": "🛒 [Bangladesh 🇧🇩] Shopping Tips:\n1. Check imported chocolates and jellies for Gelatin sources.\n2. Look for Islamic Foundation Halal logo.",
            "Bengali": "🛒 [বাংলাদেশ 🇧🇩] কেনাকাটার টিপস:\n১. আমদানিকৃত চকলেট ও জেলিতে জেলাটিনের উৎস দেখুন।\n২. ইসলামিক ফাউন্ডেশনের হালাল লোগো দেখে নিন।",
            "Chinese": "🛒 [孟加拉 🇧🇩] 购物小贴士:\n1. 进口巧克力和果冻需仔细核对明胶来源。\n2. 认准本地伊斯兰基金会清真认证。"
        },
        "info": {
            "English": "ℹ️ [Bangladesh 🇧🇩] Guide:\n• Take a picture of 'উপাদান' or 'Ingredients'.",
            "Bengali": "ℹ️ [বাংলাদেশ 🇧🇩] নির্দেশিকা:\n• মোড়কের 'উপাদান' বা 'Ingredients' অংশের সোজা ছবি তুলুন।",
            "Chinese": "ℹ️ [孟加拉 🇧🇩] 指南:\n• 请清晰拍摄包装上的‘উপাদান’或‘Ingredients’配料部分。"
        }
    }
}

COUNTRY_RULES = {
    "Japan": {
        "title": "JP HALAL FOOD CHECKER 🇯🇵",
        "haram_prompt": """
        TARGET REGION: JAPAN.
        Header: 原材料名.
        - HARAM: 豚肉, 豚脂, ラード, 豚骨, ポークエキス, 豚ゼラチン, ハム, ベーコン, 牛肉/鶏肉 (unless Halal marked), 動物性油脂, 混合油脂, コンソメ, アルコール, 洋酒, 酒精, 酒, 料理酒, 清酒, 味醂 (みりん), 発酵調味料 (with alcohol).
        - SYUBHAH: ショートニング, マーガリン, ファットスプレッド, 乳化剤 (E471/E472), 加工油脂, コラーゲン, ゼラチン.
        """
    },
    "China": {
        "title": "CN HALAL FOOD CHECKER 🇨🇳",
        "haram_prompt": """
        TARGET REGION: CHINA.
        Header: 配料 / 配料表.
        - HARAM: 猪肉, 猪油, 猪脂, 猪皮, 猪血, 培根, 火腿, 动物油脂, 鸡精, 浓汤宝, 料酒 (Chinese cooking wine), 黄酒, 白酒, 花雕酒, 米酒, 食用酒精, 啤酒, 明胶, 阿胶, 鸭血.
        - SYUBHAH: 起酥油, 人造奶油, 人造黄油, 乳化剂, 酶制剂, 食用香精.
        """
    },
    "Korea": {
        "title": "KR HALAL FOOD CHECKER 🇰🇷",
        "haram_prompt": """
        TARGET REGION: SOUTH KOREA.
        Header: 원재료명.
        - HARAM: 돼지고기, 돈지/라드, 햄, 베이컨, 젤라틴 (돼지), 쇠고기/닭고기 (unless Halal marked), 맛술 (Cooking wine), 청주, 주정 (Alcohol), 양조주, 동물성유지.
        - SYUBHAH: 쇼트닝, 마가린, 유화제 (E471), 가공유지, 콜라겐, 효소제제.
        """
    },
    "USA": {
        "title": "US HALAL FOOD CHECKER 🇺🇸",
        "haram_prompt": """
        TARGET REGION: USA (FDA Standard).
        Header: Ingredients.
        - HARAM: Pork, Bacon, Ham, Lard, Pork Gelatin, Non-Zabiha Beef/Chicken extracts, Carmine/Cochineal extract (E120), Pure Vanilla Extract (with alcohol), Brewer's yeast, Alcohol, Wine, Rum flavoring.
        - SYUBHAH: Gelatin, Mono and diglycerides (E471), Polysorbate 60/80, Whey powder, Enzymes, Natural/Artificial Flavors.
        """
    },
    "Bangladesh": {
        "title": "BD HALAL FOOD CHECKER 🇧🇩",
        "haram_prompt": """
        TARGET REGION: BANGLADESH.
        Header: উপাদান, উপাদানসমূহ, Ingredients.
        - HARAM: শুয়োরের মাংস/চর্বি (Pork, Lard), অ-হালাল প্রাণিজ জেলাটিন, ক্যারমাইন/E120, অ্যালকোহল, রাম এসেন্স.
        - SYUBHAH: ইমালসিফায়ার (E471, E472), শর্টনিং, মার্জারিন, পনিরের রেনেট, হুই পাউডার.
        """
    }
}

def get_country_selection_menu():
    return QuickReply(items=[
        QuickReplyItem(action=MessageAction(label="🇯🇵 Japan", text="Country: Japan")),
        QuickReplyItem(action=MessageAction(label="🇺🇸 USA", text="Country: USA")),
        QuickReplyItem(action=MessageAction(label="🇨🇳 China", text="Country: China")),
        QuickReplyItem(action=MessageAction(label="🇰🇷 Korea", text="Country: Korea")),
        QuickReplyItem(action=MessageAction(label="🇧🇩 Bangladesh", text="Country: Bangladesh"))
    ])

def get_language_selection_menu():
    return QuickReply(items=[
        QuickReplyItem(action=MessageAction(label="🇬🇧 English", text="Set: English")),
        QuickReplyItem(action=MessageAction(label="🇯🇵 日本語", text="Set: Japanese")),
        QuickReplyItem(action=MessageAction(label="🇨🇳 简体中文", text="Set: Chinese")),
        QuickReplyItem(action=MessageAction(label="🇧🇩 বাংলা", text="Set: Bengali")),
        QuickReplyItem(action=MessageAction(label="🇮🇩 Indonesia", text="Set: Indonesian")),
        QuickReplyItem(action=MessageAction(label="🇸🇦 العربية", text="Set: Arabic"))
    ])

def get_direct_camera_quick_reply(lang="English"):
    label = I18N.get(lang, I18N["English"])["cam_btn"]
    return QuickReply(items=[
        QuickReplyItem(action=CameraAction(label=label))
    ])

def get_post_scan_quick_reply(lang="English"):
    lang_data = I18N.get(lang, I18N["English"])
    return QuickReply(items=[
        QuickReplyItem(action=MessageAction(label=lang_data["btn_explain"], text="explain_last_scan")),
        QuickReplyItem(action=MessageAction(label=lang_data["btn_history"], text="show_history")),
        QuickReplyItem(action=CameraAction(label=lang_data["cam_btn"]))
    ])

def get_localized_country_text(country, category, lang="English"):
    country_data = COUNTRY_DETAILS.get(country, COUNTRY_DETAILS["Japan"])
    cat_dict = country_data.get(category, {})
    if isinstance(cat_dict, dict):
        return cat_dict.get(lang, cat_dict.get("English", cat_dict.get("Bengali", "")))
    return str(cat_dict)

def create_halal_flex_card(product_name, company_name, status, reason, items_text, alternatives_text, lang="English", country="Japan", item_no=None, total_count=None):
    lang_data = I18N.get(lang, I18N["English"])
    country_info = COUNTRY_RULES.get(country, COUNTRY_RULES["Japan"])
    country_header = country_info["title"]
    advice_text = get_localized_country_text(country, "advice_app", lang)

    status_upper = status.upper().strip()

    if "HALAL" in status_upper:
        header_color = "#107C41"
        status_title = lang_data["status_halal"]
        badge_bg = "#E8F5E9"
        badge_color = "#1B5E20"
    elif "HARAM" in status_upper:
        header_color = "#D32F2F"
        status_title = lang_data["status_haram"]
        badge_bg = "#FFEBEE"
        badge_color = "#B71C1C"
    else:
        header_color = "#E65100"
        status_title = lang_data["status_syubhah"]
        badge_bg = "#FFF3E0"
        badge_color = "#E65100"

    body_contents = []

    # কাউন্টার তথ্য
    if item_no is not None and total_count is not None:
        counter_label = lang_data["counter_text"].format(total=total_count, item_no=item_no)
        body_contents.append({
            "type": "box",
            "layout": "vertical",
            "paddingBottom": "6px",
            "contents": [
                {
                    "type": "text",
                    "text": counter_label,
                    "weight": "bold",
                    "size": "xxs",
                    "color": "#757575"
                }
            ]
        })

    # ১. পণ্যের নাম ও প্রস্তুতকারক কোম্পানির বক্স
    if product_name or company_name:
        prod_display = product_name if product_name else "Food Item"
        comp_display = f" | {company_name}" if company_name else ""
        body_contents.append({
            "type": "box",
            "layout": "vertical",
            "paddingBottom": "10px",
            "contents": [
                {
                    "type": "text",
                    "text": f"📦 {prod_display}{comp_display}",
                    "weight": "bold",
                    "size": "sm",
                    "color": "#111111",
                    "wrap": True
                }
            ]
        })

    # ২. স্ট্যাটাস ও কারণ
    body_contents.append({
        "type": "box",
        "layout": "vertical",
        "backgroundColor": badge_bg,
        "cornerRadius": "8px",
        "paddingAll": "12px",
        "contents": [
            {
                "type": "text",
                "text": lang_data["label_reason"],
                "weight": "bold",
                "size": "xs",
                "color": badge_color
            },
            {
                "type": "text",
                "text": reason if reason else "Completed",
                "size": "sm",
                "color": "#333333",
                "wrap": True,
                "margin": "xs"
            }
        ]
    })

    # ৩. শনাক্তকৃত উপাদানসমূহ
    body_contents.append({
        "type": "box",
        "layout": "vertical",
        "margin": "md",
        "contents": [
            {
                "type": "text",
                "text": lang_data["label_items"],
                "weight": "bold",
                "size": "xs",
                "color": "#666666"
            },
            {
                "type": "text",
                "text": items_text if items_text else "-",
                "size": "sm",
                "color": "#111111",
                "wrap": True,
                "margin": "xs"
            }
        ]
    })

    # ৪. বিকল্প সাজেশন
    if alternatives_text and alternatives_text.strip():
        body_contents.append({
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#E0F2F1",
            "cornerRadius": "6px",
            "paddingAll": "10px",
            "margin": "md",
            "contents": [
                {
                    "type": "text",
                    "text": lang_data["label_alternatives"],
                    "weight": "bold",
                    "size": "xxs",
                    "color": "#00695C"
                },
                {
                    "type": "text",
                    "text": alternatives_text,
                    "size": "xxs",
                    "color": "#004D40",
                    "wrap": True,
                    "margin": "xs"
                }
            ]
        })

    # ৫. হাদিস ও উপদেশ
    body_contents.extend([
        {
            "type": "separator",
            "margin": "lg"
        },
        {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#FFFDE7",
            "cornerRadius": "6px",
            "paddingAll": "10px",
            "margin": "md",
            "contents": [
                {
                    "type": "text",
                    "text": lang_data["label_hadith_title"],
                    "weight": "bold",
                    "size": "xxs",
                    "color": "#F57F17"
                },
                {
                    "type": "text",
                    "text": lang_data["hadith_text"],
                    "size": "xxs",
                    "color": "#4E342E",
                    "wrap": True,
                    "margin": "xs"
                }
            ]
        },
        {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#F4F6F8",
            "cornerRadius": "6px",
            "paddingAll": "10px",
            "margin": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": lang_data["label_advice_title"],
                    "weight": "bold",
                    "size": "xxs",
                    "color": "#1A73E8"
                },
                {
                    "type": "text",
                    "text": advice_text,
                    "size": "xxs",
                    "color": "#555555",
                    "wrap": True,
                    "margin": "xs"
                }
            ]
        }
    ])

    flex_json = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": header_color,
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "text",
                    "text": country_header,
                    "color": "#FFFFFF",
                    "size": "xs",
                    "weight": "bold",
                    "letterSpacing": "1px"
                },
                {
                    "type": "text",
                    "text": status_title,
                    "color": "#FFFFFF",
                    "size": "xl",
                    "weight": "bold",
                    "margin": "sm"
                }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "18px",
            "contents": body_contents
        }
    }
    return FlexContainer.from_json(json.dumps(flex_json))

@app.route("/", methods=['GET'])
def index():
    return "Global Halal Food Checker Active with Fully Localized Country-Language Engine."

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    global user_languages, user_countries, user_last_scans, user_scan_history
    user_id = event.source.user_id
    raw_text = event.message.text.strip()
    text = raw_text.lower()

    # গ্লোবাল স্ট্যান্ডার্ড অনুযায়ী ডিফল্ট ভাষা English এবং ডিফল্ট দেশ Japan
    current_lang = user_languages.get(user_id, "English")
    current_country = user_countries.get(user_id, "Japan")
    history_list = user_scan_history.get(user_id, [])

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # ১. হিস্ট্রি প্রদর্শন
        if text in ["show_history", "history", "হিস্ট্রি", "ইতিহাস", "履歴", "历史", "riwayat", "سجل"]:
            if not history_list:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=I18N[current_lang]["history_empty"])]
                    )
                )
                return

            response_msg = I18N[current_lang]["history_title"].format(count=len(history_list))
            for idx, item in enumerate(reversed(history_list[-10:]), 1):
                actual_idx = len(history_list) - idx + 1
                prod = item.get("product_name", "Food Item")
                status = item.get("status", "VERIFY")
                response_msg += f"{actual_idx}. 📦 {prod} [{status}]\n"

            response_msg += I18N[current_lang]["history_hint"]
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=response_msg)]
                )
            )
            return

        # ২. নির্দিষ্ট নম্বরের আইটেম পুনরায় দেখা
        if raw_text.isdigit():
            target_idx = int(raw_text)
            if 1 <= target_idx <= len(history_list):
                saved_item = history_list[target_idx - 1]
                flex_container = create_halal_flex_card(
                    saved_item.get("product_name", ""),
                    saved_item.get("company_name", ""),
                    saved_item.get("status", "SYUBHAH"),
                    saved_item.get("reason", ""),
                    saved_item.get("items", ""),
                    saved_item.get("alternatives", ""),
                    current_lang,
                    saved_item.get("country", current_country),
                    item_no=target_idx,
                    total_count=len(history_list)
                )
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[
                            FlexMessage(
                                alt_text=f"History #{target_idx}: {saved_item.get('status')}",
                                contents=flex_container,
                                quick_reply=get_post_scan_quick_reply(current_lang)
                            )
                        ]
                    )
                )
                return

        # ৩. শেষ স্ক্যানের উপাদানের ব্যাখ্যা
        if text in ["explain_last_scan", "explain", "বিস্তারিত", "ব্যাখ্যা", "解説", "详细", "jelaskan"]:
            last_scan = user_last_scans.get(user_id)
            if last_scan:
                prod = last_scan.get('product_name', 'Item')
                comp = last_scan.get('company_name', 'Brand')
                explanation = f"🔍 [{prod} ({comp})]:\n\n"
                explanation += f"📊 Status: {last_scan.get('status')}\n\n"
                explanation += f"📌 Reason: {last_scan.get('reason')}\n\n"
                explanation += f"🏷️ Ingredients: {last_scan.get('items')}\n\n"
                if last_scan.get('alternatives'):
                    explanation += f"💡 Alternatives: {last_scan.get('alternatives')}\n\n"
                line_bot_api.reply_message(
                    ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=explanation)])
                )
            else:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=I18N[current_lang]["history_empty"])]
                    )
                )
            return

        # ৪. দেশ নির্বাচন ও স্বয়ংক্রিয়ভাবে উপযোগী ভাষা নির্ধারণ (Smart Auto-Language)
        if raw_text.startswith("Country:"):
            chosen = raw_text.replace("Country:", "").strip().lower()
            if "china" in chosen:
                user_countries[user_id] = "China"
                user_languages[user_id] = "Chinese"
            elif "korea" in chosen or "한국" in chosen:
                user_countries[user_id] = "Korea"
                user_languages[user_id] = "English"  # কোরিয়ার ক্ষেত্রে আন্তর্জাতিক ভাষা English ডিফল্ট
            elif "usa" in chosen or "america" in chosen:
                user_countries[user_id] = "USA"
                user_languages[user_id] = "English"
            elif "bangladesh" in chosen or "bd" in chosen:
                user_countries[user_id] = "Bangladesh"
                user_languages[user_id] = "Bengali"
            else:
                user_countries[user_id] = "Japan"
                user_languages[user_id] = "Japanese"

            current_country = user_countries[user_id]
            current_lang = user_languages[user_id]

            msg = I18N[current_lang]["country_selected"].format(country=current_country)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=msg, quick_reply=get_language_selection_menu())]
                )
            )
            return

        # ৫. ভাষা নির্বাচন
        if raw_text.startswith("Set:"):
            target = raw_text.replace("Set:", "").strip().lower()
            if "english" in target:
                user_languages[user_id] = "English"
            elif "chinese" in target or "中文" in target:
                user_languages[user_id] = "Chinese"
            elif "japan" in target or "日本語" in target:
                user_languages[user_id] = "Japanese"
            elif "indonesia" in target:
                user_languages[user_id] = "Indonesian"
            elif "arabic" in target or "عرب" in target:
                user_languages[user_id] = "Arabic"
            else:
                user_languages[user_id] = "Bengali"

            current_lang = user_languages[user_id]
            msg = I18N[current_lang]["lang_confirm"].format(country=current_country)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=msg, quick_reply=get_direct_camera_quick_reply(current_lang))]
                )
            )
            return

        # রিচ মেনু বাটন C: হারাম উপাদান (সম্পূর্ণ স্থানীয়কৃত)
        if any(k in text for k in ["haram", "হারাম", "ハラーム", "非清真"]):
            country_haram_text = get_localized_country_text(current_country, "haram", current_lang)
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=country_haram_text)])
            )
            return

        # রিচ মেনু বাটন D: সন্দেহজনক উপাদান (সম্পূর্ণ স্থানীয়কৃত)
        if any(k in text for k in ["syubhah", "doubtful", "সন্দেহ", "シュブハ", "存疑"]):
            country_syubhah_text = get_localized_country_text(current_country, "syubhah", current_lang)
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=country_syubhah_text)])
            )
            return

        # রিচ মেনু বাটন E: শপিং টিপস (সম্পূর্ণ স্থানীয়কৃত)
        if any(k in text for k in ["tip", "কেনাকাটা", "tips", "贴士"]):
            country_tips_text = get_localized_country_text(current_country, "tips", current_lang)
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=country_tips_text)])
            )
            return

        # রিচ মেনু বাটন F: গাইড ও তথ্য (সম্পূর্ণ স্থানীয়কৃত)
        if any(k in text for k in ["info", "guide", "সাহায্য", "তথ্য", "指南"]):
            country_info_text = get_localized_country_text(current_country, "info", current_lang)
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=country_info_text)])
            )
            return

        # রিচ মেনু বাটন B: দেশ ও ভাষা নির্বাচন
        if any(k in text for k in ["language", "ভাষা", "bahasa", "言語", "语言", "country", "দেশ", "国家"]):
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(
                            text=I18N[current_lang]["select_country_first"],
                            quick_reply=get_country_selection_menu()
                        )
                    ]
                )
            )
            return

        # রিচ মেনু বাটন A: ছবি তোলা
        if any(k in text for k in ["take a photo", "camera", "ক্যামেরা", "scan", "ছবি", "相机", "拍照"]):
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(
                            text=I18N[current_lang]["cam_prompt"],
                            quick_reply=get_direct_camera_quick_reply(current_lang)
                        )
                    ]
                )
            )
            return

        # ডিফল্ট রিপ্লাই
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    TextMessage(
                        text=f"📍 Country: {current_country} | 🌐 Language: {current_lang}\n" + I18N[current_lang]["default_prompt"],
                        quick_reply=get_country_selection_menu()
                    )
                ]
            )
        )

# আপডেট করা এআই মডেল
def call_gemini_vision(prompt, image_b64):
    candidate_models = [
        "models/gemini-3.5-flash-lite",
        "models/gemini-3.8-flash"
    ]

    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}}
            ]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 750,
            "response_mime_type": "application/json"
        }
    }

    last_error = ""
    for model_name in candidate_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent?key={GEMINI_API_KEY}"
        for attempt in range(2):
            try:
                res = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=30)
                if res.status_code == 200:
                    data = res.json()
                    return data["candidates"][0]["content"]["parts"][0]["text"].strip()
                elif res.status_code == 503:
                    time.sleep(1)
                    continue
                else:
                    last_error = f"API Error ({res.status_code}): {res.text}"
                    break
            except Exception as e:
                last_error = str(e)
                break

    raise Exception(last_error)

@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event):
    global user_languages, user_countries, user_last_scans, user_scan_history
    user_id = event.source.user_id
    selected_lang = user_languages.get(user_id, "English")
    selected_country = user_countries.get(user_id, "Japan")

    try:
        with ApiClient(configuration) as api_client:
            blob_api = MessagingApiBlob(api_client)
            raw_bytes = blob_api.get_message_content(event.message.id)

        img = Image.open(io.BytesIO(raw_bytes))
        img.thumbnail((500, 500))
        out_buf = io.BytesIO()
        img.convert('RGB').save(out_buf, format="JPEG", quality=60, optimize=True)
        image_b64 = base64.b64encode(out_buf.getvalue()).decode("utf-8")

        del raw_bytes, img, out_buf
        gc.collect()

        country_context = COUNTRY_RULES.get(selected_country, COUNTRY_RULES["Japan"])["haram_prompt"]

        prompt = f"""
        Act as an expert Global Halal Food Inspector specialized in packaged foods for: {selected_country}.
        
        Rules & Standards for {selected_country}:
        {country_context}

        Inspection Procedure:
        1. Identify the Product Name and Manufacturer / Brand name from packaging or barcode context.
        2. Accurately detect and transcribe ingredients or barcode information from the packaging.
        3. Detect all Haram ingredients (pork derivatives, non-halal meat extracts, cooking alcohol/sake/mirin/liaojiu/cheongju, carmine/E120, animal fats).
        4. Detect any Syubhah/Doubtful components (shortening, emulsifiers E471/E472, unspecified animal gelatin, collagen, enzymes, yeast food).
        5. Verdict Hierarchy: If ANY Haram found -> 'HARAM'. Else if ANY Syubhah found -> 'SYUBHAH'. Otherwise -> 'HALAL'.
        6. Smart Halal Alternative: If status is 'HARAM' or 'SYUBHAH', suggest 1-2 widely available Halal alternative brands/items in {selected_country}. If HALAL, leave 'alternatives' empty.

        CRITICAL LOCALIZATION RULE:
        All explanation, reason, items description, and alternatives MUST BE STRICTLY WRITTEN IN: {selected_lang}.

        You MUST respond ONLY with a valid JSON matching this schema:
        {{
            "product_name": "Product name written in {selected_lang}",
            "company_name": "Manufacturer/Brand name",
            "status": "HALAL" or "HARAM" or "SYUBHAH",
            "reason": "Analysis strictly written in {selected_lang}",
            "items": "Detected specific key ingredients strictly written in {selected_lang}",
            "alternatives": "Suggested halal alternatives strictly written in {selected_lang}"
        }}
        """

        result_raw = call_gemini_vision(prompt, image_b64)
        result_json = json.loads(result_raw)

        product_name = result_json.get("product_name", "")
        company_name = result_json.get("company_name", "")
        status = result_json.get("status", "SYUBHAH")
        reason = result_json.get("reason", "")
        items = result_json.get("items", "")
        alternatives = result_json.get("alternatives", "")

        if user_id not in user_scan_history:
            user_scan_history[user_id] = []

        scan_record = {
            "product_name": product_name,
            "company_name": company_name,
            "status": status,
            "reason": reason,
            "items": items,
            "alternatives": alternatives,
            "country": selected_country
        }
        user_scan_history[user_id].append(scan_record)

        total_scans = len(user_scan_history[user_id])
        current_item_no = total_scans

        user_last_scans[user_id] = scan_record

        flex_container = create_halal_flex_card(
            product_name, company_name, status, reason, items, alternatives, 
            selected_lang, selected_country, item_no=current_item_no, total_count=total_scans
        )
        reply_payload = [
            FlexMessage(
                alt_text=f"Check Result: {status}",
                contents=flex_container,
                quick_reply=get_post_scan_quick_reply(selected_lang)
            )
        ]

    except Exception as e:
        reply_payload = [TextMessage(text=f"Error analyzing image: {str(e)}")]

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=reply_payload
            )
        )
