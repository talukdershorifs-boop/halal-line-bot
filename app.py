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

user_languages = {}
user_countries = {}
user_last_scans = {}  # ফলো-আপ চ্যাটের জন্য শেষ স্ক্যানের ফলাফল সংরক্ষণ

I18N = {
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
        "country_selected": "📍 দেশ নির্বাচিত: {country}\nএখন আপনার পছন্দের ভাষা বেছে নিন:",
        "default_prompt": "মেনু থেকে অপশন বেছে নিন অথবা পণ্যের উপাদানের স্পষ্ট ছবি পাঠান।",
        "select_country_first": "🌍 প্রথমে আপনার অবস্থান বা ভ্রমণের দেশ নির্বাচন করুন:",
        "btn_explain": "❓ উপাদান বিস্তারিত জানাও"
    },
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
        "lang_confirm": "✅ Settings configured!\n📍 Country: {country}\n🌐 Language: English\n\nPlease send a clear photo of the ingredient list.",
        "country_selected": "📍 Country selected: {country}\nNow, please select your language:",
        "default_prompt": "Please choose from the menu or send a photo of the ingredients list.",
        "select_country_first": "🌍 Please select your country first:",
        "btn_explain": "❓ Explain Ingredients"
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
        "country_selected": "📍 Negara dipilih: {country}\nSekarang, silakan pilih bahasa Anda:",
        "default_prompt": "Silakan pilih menu atau kirim foto daftar komposisi bahan.",
        "select_country_first": "🌍 Silakan pilih negara Anda terlebih dahulu:",
        "btn_explain": "❓ Jelaskan Bahan"
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
        "country_selected": "📍 国を選択しました: {country}\n次に言語を選択してください:",
        "default_prompt": "メニューから選択するか、商品の原材料名（原材料表示）の写真を送信してください。",
        "select_country_first": "🌍 まず対象の国を選択してください:",
        "btn_explain": "❓ 成分の詳細解説"
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
        "country_selected": "📍 تم تحديد الدولة: {country}\nالآن يرجى اختيار اللغة:",
        "default_prompt": "يرجى الاختيار من القائمة أو إرسال صورة واضحة لقائمة المكونات.",
        "select_country_first": "🌍 يرجى اختيار الدولة أولاً:",
        "btn_explain": "❓ تفاصيل المكونات"
    }
}

COUNTRY_DETAILS = {
    "Japan": {
        "title": "JP HALAL FOOD CHECKER 🇯🇵",
        "advice_app": "আমাদের এই বটটি একটি ফ্রি এআই টুল। জাপানে শতভাগ নির্ভরযোগ্য তথ্যের জন্য ভেরিফাইড পেইড অ্যাপ 'Halal Japan' ব্যবহারের অনুরোধ করা হচ্ছে।",
        "haram": """🚫 [জাপান 🇯🇵] নিশ্চিত হারাম উপাদান:
• 豚肉、ポーク | শুকরের মাংস
• 豚脂肪、豚脂、ラード | শুকরের চর্বি / লার্ড
• ハム、ベーコン、豚骨エキス | হ্যাম, বেকন, শুকরের হাড়ের নির্যাস
• 豚ゼラチン | শুকরের জেলাটিন
• 牛肉、牛脂、鶏肉 | সাধারণ জবাইবিহীন গরু/মুরগি
• 動物性油脂、混合油脂 | মিশ্র প্রাণিজ চর্বি
• コンソメ、ブイヨン | কনসোমে/ব্রোথ
• アルコール、洋酒、酒精 | অ্যালকোহল, মদ
• 酒、清酒、料理酒、味醂 (みりん) | রান্নার মদ, মিরিন""",

        "syubhah": """⚠️ [জাপান 🇯🇵] সন্দেহজনক উপাদান (Syubhah):
• 乳化剤 (ইমালসিফায়ার / E471) - উৎস উল্লেখ না থাকলে
• ショートニング (শর্টনিং) - বেকারি ফ্যাট
• マーガリン (মার্জারিন) - প্রাণিজ তেলের সম্ভাবনা
• ファットスプレッド (ফ্যাটস্প্রেড)
• 加工油脂 (প্রক্রিয়াজাত চর্বি)
• ゼラチン、コラーゲン | মাছের নিশ্চিত উল্লেখ ছাড়া

📜 নবিজি ﷺ বলেছেন: 'যে ব্যক্তি সন্দেহজনক বিষয় থেকে বাঁচল, সে দ্বীন রক্ষা করল।' [বুখারি: ৫২]""",

        "tips": """🛒 [জাপান 🇯🇵] কেনাকাটার টিপস:
১. পাউরুটি ও বিস্কুটে '植物性' বা '植物油脂' (উদ্ভিজ্জ) লেখা থাকলে নিরাপদ।
২. পেস্ট্রি, কেক ও চকলেট কেনার সময় '洋酒' (মদ) পরিহার করুন।
৩. কনভিনিয়েন্স স্টোরের ওনিগিরিতে প্রায়ই 'みりん' (মিরিন) ফ্লেভার থাকে, চেক করুন।""",

        "info": """ℹ️ [জাপান 🇯🇵] নির্দেশিকা:
• পণ্যের উপাদানের তালিকার (原材料名) সোজা ও স্পষ্ট ছবি স্ক্যান করুন।
• শতভাগ নিরাপদ থাকার জন্য অফিশিয়াল 'Halal Japan' অ্যাপ ব্যবহার করুন।"""
    },
    "China": {
        "title": "CN HALAL FOOD CHECKER 🇨🇳",
        "advice_app": "আমাদের এই বটটি একটি ফ্রি এআই টুল। চীনে খাদ্যদ্রব্যের ক্ষেত্রে নিশ্চিত হতে 'Green Halal (清真)' লোগো ও সার্টিফায়েড গাইডলাইন অনুসরণ করুন।",
        "haram": """🚫 [চীন 🇨🇳] নিশ্চিত হারাম উপাদান:
• 猪肉、猪油、猪脂 | শুকরের মাংস ও চর্বি
• 猪皮、猪肉浸膏、火腿、培根 | শুকরের চামড়া, নির্যাস, হ্যাম
• 猪血、鸭血、血旺 | রক্ত দিয়ে তৈরি খাবার
• 料酒、黄酒、白酒 | চীনা রান্নার ওয়াইন/মদ
• 花雕酒、米酒、食用酒精 | চালের মদ ও অ্যালকোহল
• 鸡精、浓汤宝 (অ-হালাল ব্রোথ)
• 明胶、阿胶 (অ-হালাল প্রাণিজ জেলাটিন)""",

        "syubhah": """⚠️ [চীন 🇨🇳] সন্দেহজনক উপাদান (Syubhah):
• 起酥油 (শর্টনিং) - প্রাণিজ ফ্যাটের মিশ্রণ থাকতে পারে
• 人造奶油、人造黄油 (মার্জারিন)
• 乳化剂 (ইমালসিফায়ার) - উদ্ভিদ না প্রাণী অস্পষ্ট হলে
• 食用香精 (ফ্লেভারিং) - ওয়াইন দ্রাবক ব্যবহৃত হতে পারে
• 单双甘油脂肪酸酯 (E471)

📜 নবিজি ﷺ বলেছেন: 'যে ব্যক্তি সন্দেহজনক বিষয় থেকে বাঁচল, সে দ্বীন রক্ষা করল।' [বুখারি: ৫২]""",

        "tips": """🛒 [চীন 🇨🇳] কেনাকাটার টিপস:
১. প্যাকেটের গায়ে সবুজ '清真' (Halal) সিল আছে কি না আগে নিশ্চিত হোন।
২. চাইনিজ স্ন্যাকস ও নুডুলসে রান্নার ওয়াইন '料酒' প্রচুর থাকে, উপাদান দেখুন।
৩. জেলাটিনযুক্ত ক্যান্ডি বা জেলি এড়িয়ে চলুন।""",

        "info": """ℹ️ [চীন 🇨🇳] নির্দেশিকা:
• পণ্যের উপাদানের তালিকার (配料 / 配料表) অংশের ছবি স্ক্যান করুন।
• চীনে অনুমোদিত হালাল অথরিটির '清真' সিল দেখে কেনা সবচেয়ে নিরাপদ।"""
    },
    "Korea": {
        "title": "KR HALAL FOOD CHECKER 🇰🇷",
        "advice_app": "আমাদের এই বটটি একটি ফ্রি এআই টুল। দক্ষিণ কোরিয়ায় শতভাগ নিরাপদ খাদ্য বাছাই করতে 'Mufko' অথবা 'KMF Halal' অ্যাপ ব্যবহারের অনুরোধ করা হচ্ছে।",
        "haram": """🚫 [কোরিয়া 🇰🇷] নিশ্চিত হারাম উপাদান:
• 돼지고기 (Pork) | শুকরের মাংস
• 돈지 / 라드 (Lard) | শুকরের চর্বি
• 햄, 베이컨, 돼지껍데기 | হ্যাম, বেকন, শুকরের চামড়া
• 맛술, 미림 | রান্নার মদ (Cooking wine/Mirin)
• 청주, 주정 | চুংজু মদ, অ্যালকোহল
• 쇠고기, 닭고기 | সাধারণ জবাইবিহীন মাংস
• 동물성유지 | প্রাণিজ চর্বি""",

        "syubhah": """⚠️ [কোরিয়া 🇰🇷] সন্দেহজনক উপাদান (Syubhah):
• 쇼트닝 (শর্টনিং) - বেকারি ফ্যাট
• 마가린 (মার্জারিন) - মিশ্র প্রাণিজ চর্বি
• 유화제 (ইমালসিফায়ার E471)
• 가공유지 (প্রক্রিয়াজাত চর্বি)
• 젤라틴 (জেলাটিন - মাছের না হলে)
• 고추장, 쌈장, 된장 | ফারমেন্টেড সসে অ্যালকোহল/স্পিরিট মিশ্রণ থাকতে পারে

📜 নবিজি ﷺ বলেছেন: 'সন্দেহজনক বিষয় থেকে দূরে থাকাই দ্বীন রক্ষা করা।' [বুখারি: ৫২]""",

        "tips": """🛒 [কোরিয়া 🇰🇷] কেনাকাটার টিপস:
১. প্যাকেটে 식물성유지 (উদ্ভিজ্জ তেল) লেখা থাকলে নিরাপদ।
২. জনপ্রিয় রামিয়ন (라면)-এর স্যুপ ব্রোথে শুকরের নির্যাস প্রায়ই থাকে, সতর্ক থাকুন।
৩. কোরিয়ান সস কেনার সময় 주정 (অ্যালকোহল) আছে কি না দেখে নিন।""",

        "info": """ℹ️ [কোরিয়া 🇰🇷] নির্দেশিকা:
• পণ্যের উপাদানের তালিকার (원재료명) স্পষ্ট ছবি পাঠান।
• কোরিয়ায় শতভাগ নিশ্চিত থাকতে 'Mufko' অ্যাপ বা KMF Halal সিল চেক করুন।"""
    },
    "USA": {
        "title": "US HALAL FOOD CHECKER 🇺🇸",
        "advice_app": "আমাদের এই বটটি একটি ফ্রি এআই টুল। যুক্তরাষ্ট্রে ১০০% নির্ভুল ও হালাল পণ্য নিশ্চিত করতে 'Scan Halal' অথবা 'Crescent Halal' অ্যাপ ব্যবহার করুন।",
        "haram": """🚫 [USA 🇺🇸] নিশ্চিত হারাম উপাদান:
• Pork, Bacon, Ham, Pork Lard | শুকর ও চর্বি
• Pork Gelatin / Gelatin (অ-হালাল উৎস)
• Carmine / Cochineal Extract (E120) | লাল পোকার রঙ
• Pure Vanilla Extract (আইন অনুযায়ী ৩৫%+ অ্যালকোহল থাকে)
• Brewer's Yeast (বিয়ার তৈরির ইস্ট)
• Wine, Rum flavoring containing alcohol
• Non-Zabiha Beef / Poultry extracts""",

        "syubhah": """⚠️ [USA 🇺🇸] সন্দেহজনক উপাদান (Syubhah):
• Mono and diglycerides (E471) - উৎস অস্পষ্ট হলে
• Shortening (প্রাণিজ না উদ্ভিজ্জ পরিষ্কার না হলে)
• Whey powder / Rennet in Cheese (প্রাণিজ রেনেট)
• Enzymes (Lipase, Pepsin)
• Natural & Artificial Flavors (অ্যালকোহল দ্রাবক থাকতে পারে)

📜 নবিজি ﷺ বলেছেন: 'সন্দেহজনক বিষয় পরিহার করাই উত্তম।' [বুখারি: ৫২]""",

        "tips": """🛒 [USA 🇺🇸] কেনাকাটার টিপস:
১. Kosher Pareve (OU Pareve, Circle-U) সিল থাকলে মাংস ও অ্যালকোহলমুক্ত থাকে।
二. মার্শমেলো, গামি ক্যান্ডিতে Gelatin থাকে যা অধিকাংশ ক্ষেত্রে শুকর থেকে আসে।
৩. পাউরুটি কেনার সময় '100% Plant Based' বা 'Vegetable Shortening' লেখা খুঁজুন।""",

        "info": """ℹ️ [USA 🇺🇸] নির্দেশিকা:
• প্যাকেটের 'Ingredients' অংশের স্পষ্ট ছবি স্ক্যান করুন।
• সার্বিক যাচাইয়ের জন্য 'Scan Halal' অ্যাপ ব্যবহার করতে পারেন।"""
    },
    "Bangladesh": {
        "title": "BD HALAL FOOD CHECKER 🇧🇩",
        "advice_app": "আমাদের এই বটটি একটি ফ্রি এআই টুল। স্থানীয় ও আমদানিকৃত খাদ্যে নিশ্চিত থাকতে 'ইসলামিক ফাউন্ডেশন বাংলাদেশ' ও বিএসটিআই হালাল লোগো অনুসরণ করুন।",
        "haram": """🚫 [বাংলাদেশ 🇧🇩] নিশ্চিত হারাম উপাদান:
• পর্ক, বেকন, হ্যাম, লার্ড (আমদানিকৃত খাদ্যে)
• অ-হালাল প্রাণিজ জেলাটিন (আমদানিকৃত জেলি, চকলেটে)
• অ্যালকোহল, স্পিরিট, রাম এসেন্স
• ক্যারমাইন / কোচিনিল (E120 লাল কৃত্রিম রঙ)
• অ-হালাল বিদেশি মাংসের নির্যাস ও ব্রোথ""",

        "syubhah": """⚠️ [বাংলাদেশ 🇧🇩] সন্দেহজনক উপাদান (Syubhah):
• ইমালসিফায়ার (E471, E472a-f, E481) - ভেজিটেবল উৎস উল্লেখ না থাকলে
• শর্টনিং ও মার্জারিন (বেকারি পণ্যে প্রাণিজ চর্বির ব্যবহার)
• রেনেট (Rennet) - আমদানিকৃত চিজে ব্যবহৃত এনজাইম
• হুই পাউডার (Whey powder)
• কৃত্রিম সুগন্ধি ও এসেন্স

📜 নবিজি ﷺ বলেছেন: 'যে ব্যক্তি সন্দেহজনক বিষয় থেকে বাঁচল, সে দ্বীন রক্ষা করল।' [বুখারি: ৫২]""",

        "tips": """🛒 [বাংলাদেশ 🇧🇩] কেনাকাটার টিপস:
১. আমদানিকৃত বিস্কুট বা চকলেটের মোড়কে E471 ও Gelatin এর উৎস যাচাই করুন।
২. সাধারণ বেকারি থেকে কেক/পেস্ট্রি কেনার সময় শর্টনিংয়ের উৎস জেনে নিন।
৩. মোড়কের গায়ে ইসলামিক ফাউন্ডেশন বা স্বীকৃত হালাল সনদ লোগো দেখে নিন।""",

        "info": """ℹ️ [বাংলাদেশ 🇧🇩] নির্দেশিকা:
• মোড়কের 'উপাদান' বা 'Ingredients' অংশের সোজা ছবি তুলুন।
• স্থানীয় পণ্যে ইসলামিক ফাউন্ডেশনের হালাল লোগো নিশ্চিত থাকুন।"""
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
        - HARAM: 돼지고기, 돈지/라드, 햄, 베이컨, 젤라틴 (돼지), 쇠고기/닭고기 (unless Halal marked), 맛술 (Cooking wine), 청주, 주정 (Alcohol), 양조주, 동물性유지.
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
        QuickReplyItem(action=MessageAction(label="🇨🇳 China", text="Country: China")),
        QuickReplyItem(action=MessageAction(label="🇰🇷 Korea", text="Country: Korea")),
        QuickReplyItem(action=MessageAction(label="🇺🇸 USA", text="Country: USA")),
        QuickReplyItem(action=MessageAction(label="🇧🇩 Bangladesh", text="Country: Bangladesh"))
    ])

def get_language_selection_menu():
    return QuickReply(items=[
        QuickReplyItem(action=MessageAction(label="🇧🇩 বাংলা", text="Set: Bengali")),
        QuickReplyItem(action=MessageAction(label="🇬🇧 English", text="Set: English")),
        QuickReplyItem(action=MessageAction(label="🇮🇩 Indonesia", text="Set: Indonesian")),
        QuickReplyItem(action=MessageAction(label="🇯🇵 日本語", text="Set: Japanese")),
        QuickReplyItem(action=MessageAction(label="🇸🇦 العربية", text="Set: Arabic"))
    ])

def get_direct_camera_quick_reply(lang="Bengali"):
    label = I18N.get(lang, I18N["Bengali"])["cam_btn"]
    return QuickReply(items=[
        QuickReplyItem(action=CameraAction(label=label))
    ])

def get_post_scan_quick_reply(lang="Bengali"):
    lang_data = I18N.get(lang, I18N["Bengali"])
    return QuickReply(items=[
        QuickReplyItem(action=MessageAction(label=lang_data["btn_explain"], text="explain_last_scan")),
        QuickReplyItem(action=CameraAction(label=lang_data["cam_btn"]))
    ])

def create_halal_flex_card(status, reason, items_text, alternatives_text, lang="Bengali", country="Japan"):
    lang_data = I18N.get(lang, I18N["Bengali"])
    country_info = COUNTRY_RULES.get(country, COUNTRY_RULES["Japan"])
    country_header = country_info["title"]
    advice_text = COUNTRY_DETAILS.get(country, COUNTRY_DETAILS["Japan"])["advice_app"]

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

    body_contents = [
        {
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
        },
        {
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
        }
    ]

    # যদি বিকল্প সাজেশন থাকে (হারাম বা সন্দেহজনক পণ্যের জন্য)
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
    return "Global Halal Food Checker with Alternatives & Micro-chat Active."

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
    global user_languages, user_countries, user_last_scans
    user_id = event.source.user_id
    raw_text = event.message.text.strip()
    text = raw_text.lower()

    current_lang = user_languages.get(user_id, "Bengali")
    current_country = user_countries.get(user_id, "Japan")

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # মাইক্রো-চ্যাট: শেষ স্ক্যানের উপাদানের বিস্তারিত ব্যাখ্যা
        if text == "explain_last_scan" or "বিস্তারিত" in text or "explain" in text:
            last_scan = user_last_scans.get(user_id)
            if last_scan:
                explanation = f"🔍 [বিশ্লেষণ - {last_scan.get('status')}]:\n\n"
                explanation += f"📌 কারণ: {last_scan.get('reason')}\n\n"
                explanation += f"🏷️ উপাদানসমূহ: {last_scan.get('items')}\n\n"
                if last_scan.get('alternatives'):
                    explanation += f"💡 বিকল্প: {last_scan.get('alternatives')}\n\n"
                explanation += "কোনো নির্দিষ্ট কাঞ্জি বা কোড সম্পর্কে জানতে প্রশ্ন লিখে পাঠাতে পারেন।"
                line_bot_api.reply_message(
                    ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=explanation)])
                )
            else:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="আগে একটি পণ্যের উপাদানের ছবি পাঠিয়ে যাচাই করুন।")]
                    )
                )
            return

        # দেশ নির্বাচন
        if raw_text.startswith("Country:"):
            chosen = raw_text.replace("Country:", "").strip().lower()
            if "china" in chosen:
                user_countries[user_id] = "China"
            elif "korea" in chosen or "한국" in chosen:
                user_countries[user_id] = "Korea"
            elif "usa" in chosen or "america" in chosen:
                user_countries[user_id] = "USA"
            elif "bangladesh" in chosen or "bd" in chosen:
                user_countries[user_id] = "Bangladesh"
            else:
                user_countries[user_id] = "Japan"

            current_country = user_countries[user_id]
            msg = I18N[current_lang]["country_selected"].format(country=current_country)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=msg, quick_reply=get_language_selection_menu())]
                )
            )
            return

        # ভাষা নির্বাচন
        if raw_text.startswith("Set:"):
            target = raw_text.replace("Set:", "").strip().lower()
            if "english" in target:
                user_languages[user_id] = "English"
            elif "indonesia" in target:
                user_languages[user_id] = "Indonesian"
            elif "japan" in target:
                user_languages[user_id] = "Japanese"
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

        # রিচ মেনু বাটন C: হারাম উপাদান
        if any(k in text for k in ["haram", "হারাম", "ハラーム"]):
            country_haram_text = COUNTRY_DETAILS.get(current_country, COUNTRY_DETAILS["Japan"])["haram"]
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=country_haram_text)])
            )
            return

        # রিচ মেনু বাটন D: সন্দেহজনক উপাদান
        if any(k in text for k in ["syubhah", "doubtful", "সন্দেহ", "シュブハ", "شبهة"]):
            country_syubhah_text = COUNTRY_DETAILS.get(current_country, COUNTRY_DETAILS["Japan"])["syubhah"]
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=country_syubhah_text)])
            )
            return

        # রিচ মেনু বাটন E: শপিং টিপস
        if any(k in text for k in ["tip", "কেনাকাটা", "tips"]):
            country_tips_text = COUNTRY_DETAILS.get(current_country, COUNTRY_DETAILS["Japan"])["tips"]
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=country_tips_text)])
            )
            return

        # রিচ মেনু বাটন F: গাইড ও তথ্য
        if any(k in text for k in ["info", "guide", "সাহায্য", "তথ্য", "bantuan", "ガイド"]):
            country_info_text = COUNTRY_DETAILS.get(current_country, COUNTRY_DETAILS["Japan"])["info"]
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=country_info_text)])
            )
            return

        # রিচ মেনু বাটন B: দেশ ও ভাষা
        if any(k in text for k in ["language", "ভাষা", "bahasa", "言語", "لغة", "country", "দেশ", "change language"]):
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
        if any(k in text for k in ["take a photo", "camera", "ক্যামেরা", "scan", "ছবি", "kamera", "カメラ"]):
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

def call_gemini_vision(prompt, image_b64):
    candidate_models = [
        "models/gemini-2.5-flash",
        "models/gemini-2.5-flash-lite"
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
            "maxOutputTokens": 700,
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
    global user_languages, user_countries, user_last_scans
    user_id = event.source.user_id
    selected_lang = user_languages.get(user_id, "Bengali")
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
        1. Accurately detect and transcribe ingredients or barcode information from the packaging.
        2. Detect all Haram ingredients (pork derivatives, non-halal meat extracts, cooking alcohol/sake/mirin/liaojiu/cheongju, carmine/E120, animal fats).
        3. Detect any Syubhah/Doubtful components (shortening, emulsifiers E471/E472, unspecified animal gelatin, collagen, enzymes, yeast food).
        4. Verdict Hierarchy: If ANY Haram found -> 'HARAM'. Else if ANY Syubhah found -> 'SYUBHAH'. Otherwise -> 'HALAL'.
        5. Smart Halal Alternative: If status is 'HARAM' or 'SYUBHAH', suggest 1-2 widely available Halal alternative brands/items in {selected_country} (e.g. halal certified potato chips, halal soy sauce, or plant-based cookies). If HALAL, leave 'alternatives' empty.

        You MUST respond ONLY with a valid JSON matching this schema:
        {{
            "status": "HALAL" or "HARAM" or "SYUBHAH",
            "reason": "Accurate, concise analysis strictly written in {selected_lang}",
            "items": "Detected specific key ingredients (original text + translation) strictly written in {selected_lang}",
            "alternatives": "Suggested halal alternatives in {selected_lang} (or empty string if Halal)"
        }}
        """

        result_raw = call_gemini_vision(prompt, image_b64)
        result_json = json.loads(result_raw)

        status = result_json.get("status", "SYUBHAH")
        reason = result_json.get("reason", "")
        items = result_json.get("items", "")
        alternatives = result_json.get("alternatives", "")

        # শেষ স্ক্যান ক্যাশ করা
        user_last_scans[user_id] = {
            "status": status,
            "reason": reason,
            "items": items,
            "alternatives": alternatives
        }

        flex_container = create_halal_flex_card(status, reason, items, alternatives, selected_lang, selected_country)
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
