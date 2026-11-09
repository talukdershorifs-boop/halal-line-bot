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

# ভাষাভিত্তিক ইউজার ইন্টারফেস টেক্সট
I18N = {
    "Bengali": {
        "status_halal": "✅ HALAL (হালাল)",
        "status_haram": "❌ HARAM (হারাম)",
        "status_syubhah": "⚠️ SYUBHAH (সন্দেহজনক)",
        "label_reason": "পর্যবেক্ষণ ও কারণ:",
        "label_items": "শনাক্তকৃত উপাদান:",
        "label_hadith_title": "📜 হাদিসের আলোকে সতর্কতা:",
        "hadith_text": "রাসূলুল্লাহ ﷺ বলেছেন: 'হালালও স্পষ্ট এবং হারামও স্পষ্ট। আর এ দুয়ের মাঝে রয়েছে বহু সন্দেহজনক বিষয়... যে ব্যক্তি সন্দেহজনক বিষয় থেকে নিজেকে বাঁচিয়ে রাখল, সে তার দ্বীন ও সম্মান রক্ষা করল।' [সহিহ বুখারি: ৫২, সহিহ মুসলিম: ১৫৯৯]",
        "label_advice_title": "💡 গুরুত্বপূর্ণ পরামর্শ:",
        "cam_btn": "📷 ক্যামেরা খুলুন",
        "cam_prompt": "নিচের '📷 ক্যামেরা খুলুন' বাটনে চাপ দিয়ে পণ্যের উপাদানের স্পষ্ট ছবি তুলুন:",
        "lang_confirm": "✅ সেটিংস সম্পন্ন হয়েছে!\n📍 দেশ: {country}\n🌐 ভাষা: বাংলা\n\nএখন খাবারের উপাদানের স্পষ্ট ছবি পাঠান।",
        "country_selected": "📍 দেশ নির্বাচিত: {country}\nএখন আপনার পছন্দের ভাষা বেছে নিন:",
        "default_prompt": "মেনু থেকে অপশন বেছে নিন অথবা পণ্যের উপাদানের স্পষ্ট ছবি পাঠান।",
        "select_country_first": "🌍 প্রথমে আপনার অবস্থান বা ভ্রমণের দেশ নির্বাচন করুন:"
    },
    "English": {
        "status_halal": "✅ HALAL",
        "status_haram": "❌ HARAM",
        "status_syubhah": "⚠️ SYUBHAH (Doubtful)",
        "label_reason": "Observation & Reason:",
        "label_items": "Detected Ingredients:",
        "label_hadith_title": "📜 Warning from Hadith:",
        "hadith_text": "The Prophet ﷺ said: 'What is lawful is clear and what is unlawful is clear, and between them are matters that are doubtful... So he who guards against doubtful matters clears himself in regard to his religion and his honor.' [Sahih al-Bukhari: 52, Sahih Muslim: 1599]",
        "label_advice_title": "💡 Important Recommendation:",
        "cam_btn": "📷 Open Camera",
        "cam_prompt": "Tap '📷 Open Camera' below to take a clear picture of the ingredient list:",
        "lang_confirm": "✅ Settings configured!\n📍 Country: {country}\n🌐 Language: English\n\nPlease send a clear photo of the ingredient list.",
        "country_selected": "📍 Country selected: {country}\nNow, please select your language:",
        "default_prompt": "Please choose from the menu or send a photo of the ingredients list.",
        "select_country_first": "🌍 Please select your country first:"
    },
    "Indonesian": {
        "status_halal": "✅ HALAL",
        "status_haram": "❌ HARAM",
        "status_syubhah": "⚠️ SYUBHAH (Meragukan)",
        "label_reason": "Alasan & Observasi:",
        "label_items": "Bahan Terdeteksi:",
        "label_hadith_title": "📜 Peringatan Hadits:",
        "hadith_text": "Rasulullah ﷺ bersabda: 'Sesungguhnya yang halal itu jelas dan yang haram itu jelas, dan di antara keduanya ada perkara-perkara syubhat... Barangsiapa menjauhi syubhat, maka ia telah membersihkan agama dan kehormatannya.' [HR. Bukhari: 52, Muslim: 1599]",
        "label_advice_title": "💡 Rekomendasi Penting:",
        "cam_btn": "📷 Buka Kamera",
        "cam_prompt": "Tekan tombol '📷 Buka Kamera' di bawah untuk mengambil foto komposisi:",
        "lang_confirm": "✅ Pengaturan selesai!\n📍 Negara: {country}\n🌐 Bahasa: Bahasa Indonesia\n\nSilakan kirim foto komposisi makanan.",
        "country_selected": "📍 Negara dipilih: {country}\nSekarang, silakan pilih bahasa Anda:",
        "default_prompt": "Silakan pilih menu atau kirim foto daftar komposisi bahan.",
        "select_country_first": "🌍 Silakan pilih negara Anda terlebih dahulu:"
    },
    "Japanese": {
        "status_halal": "✅ ハラール (HALAL)",
        "status_haram": "❌ ハラーム (HARAM)",
        "status_syubhah": "⚠️ シュブハ (疑わしい)",
        "label_reason": "判定理由・観察:",
        "label_items": "検出された原材料:",
        "label_hadith_title": "📜 ハディースによる教え:",
        "hadith_text": "預言者ムハンマド ﷺ は仰いました:『合法（ハラール）なものは明白であり、非合法（ハラーム）なものも明白である。そして両者の間には疑わしい事柄がある...疑わしいものを避ける者は、自らの宗教と名誉を守ることになる。』[サヒーフ・ブハーリー: 52, サヒーフ・ムスリム: 1599]",
        "label_advice_title": "💡 重要なお知らせ:",
        "cam_btn": "📷 カメラを起動",
        "cam_prompt": "下の『📷 カメラを起動』ボタンを押して原材料名の写真を撮影してください:",
        "lang_confirm": "✅ 設定が完了しました！\n📍 対象国: {country}\n🌐 言語: 日本語\n\n原材料名の写真を送信してください。",
        "country_selected": "📍 国を選択しました: {country}\n次に言語を選択してください:",
        "default_prompt": "メニューから選択するか、商品の原材料名（原材料表示）の写真を送信してください。",
        "select_country_first": "🌍 まず対象の国を選択してください:"
    },
    "Arabic": {
        "status_halal": "✅ حلال (HALAL)",
        "status_haram": "❌ حرام (HARAM)",
        "status_syubhah": "⚠️ شبهة (SYUBHAH)",
        "label_reason": "الملاحظة والسبب:",
        "label_items": "المكونات المكتشفة:",
        "label_hadith_title": "📜 التحذير النبوي الشريف:",
        "hadith_text": "قال رسول الله ﷺ: 'إن الحلال بيّن وإن الحرام بيّن، وبينهما أمور مشتبهات... فمن اتقى الشبهات فقد استبرأ لدينه وعِرضه.' [صحيح البخاري: ٥٢، صحيح مسلم: ١٥٩٩]",
        "label_advice_title": "💡 نصيحة هامة:",
        "cam_btn": "📷 فتح الكاميرا",
        "cam_prompt": "اضغط على زر '📷 فتح الكاميرا' بالأسفل لتصوير قائمة المكونات بوضوح:",
        "lang_confirm": "✅ تم ضبط الإعدادات بنجاح!\n📍 الدولة: {country}\n🌐 اللغة: العربية\n\nيرجى إرسال صورة واضحة لقائمة المكونات.",
        "country_selected": "📍 تم تحديد الدولة: {country}\nالآن يرجى اختيار اللغة:",
        "default_prompt": "يرجى الاختيار من القائمة أو إرسال صورة واضحة لقائمة المكونات.",
        "select_country_first": "🌍 يرجى اختيار الدولة أولاً:"
    }
}

# দেশভিত্তিক সম্পূর্ণ তথ্য ভাণ্ডার (Haram, Syubhah, Tips, Info)
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
• 花雕酒、米酒、食用酒精 | চালের মদ ও অ্যালকোহ
