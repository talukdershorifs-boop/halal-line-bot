import os
import io
import gc
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
    QuickReply,
    QuickReplyItem,
    MessageAction,
    CameraAction,
    CameraRollAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, ImageMessageContent

app = Flask(__name__)

CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

user_languages = {}

def get_image_source_quick_reply():
    """ক্যামেরা এবং গ্যালারি একসাথে পপ-আপ করার অপশন"""
    return QuickReply(items=[
        QuickReplyItem(action=CameraAction(label="📷 ক্যামেরা (Camera)")),
        QuickReplyItem(action=CameraRollAction(label="🖼️ গ্যালারি (Gallery)"))
    ])

def get_language_selection_menu():
    """ইন্দোনেশিয়ান ভাষা যুক্ত করে ৫-ভাষার কুইক রিপ্লাই"""
    return QuickReply(items=[
        QuickReplyItem(action=MessageAction(label="🇧🇩 বাংলা", text="Set: বাংলা")),
        QuickReplyItem(action=MessageAction(label="🇮🇩 Bahasa Indonesia", text="Set: Bahasa Indonesia")),
        QuickReplyItem(action=MessageAction(label="🇬🇧 English", text="Set: English")),
        QuickReplyItem(action=MessageAction(label="🇯🇵 日本語", text="Set: 日本語")),
        QuickReplyItem(action=MessageAction(label="🇸🇦 العربية", text="Set: العربية")),
    ])

CHECKED_DATA = {
    "Bengali": {
        "haram": (
            "🚫 নিশ্চিত হারাম উপাদানসমূহ (Strictly Haram):\n\n"
            "🐖 শুকর ও শুকরজাত উপাদান:\n"
            "• 豚肉、ポーク | শুকরের মাংস (Pork)\n"
            "• 豚脂肪、豚脂 | শুকরের চর্বি (Pork Fat)\n"
            "• ラード、ハム、ベーコン | লার্ড, হ্যাম, বেকন\n"
            "• 豚エキス | শুকরের নির্যাস (Pork Extract)\n"
            "• 豚ゼラチン | শুকরের জেলাটিন\n\n"
            "🥩 অ-হালাল মাংস ও প্রাণিজ চর্বি:\n"
            "• 牛肉、牛脂 | সাধারণ গরুর মাংস, চর্বি (Tallow)\n"
            "• 鶏肉、チキン | অ-হালাল মুরগির মাংস\n"
            "• 動物性油脂、混合油脂 | প্রাণিজ চর্বি / মিশ্র চর্বি\n"
            "• コンソメ | কনসোমে স্যুপ ব্রোথ\n\n"
            "🍷 অ্যালকোহল ও মদজাতীয় উপাদান:\n"
            "• アルコール、洋酒 | অ্যালকোহল, পশ্চিমা মদ\n"
            "• 酒、清酒、料理酒 | জাপানি সাকে মদ, রান্নার মদ\n"
            "• 味醂、みりん | মিরিন কুকিং অ্যালকোহল\n"
            "• 酒精 | ইথাইল অ্যালকোহল\n"
            "• ラム、ワイン、ブランディ | রাম, ওয়াইন, ব্র্যান্ডি"
        ),
        "syubhah": (
            "⚠️ সন্দেহজনক উপাদানসমূহ (Syubhah):\n\n"
            "• 乳化剤 (ইমালসিফায়ার) - উদ্ভিদ নাকি প্রাণিজ স্পষ্ট না হলে সন্দেহজনক।\n"
            "• ショートニング (শর্টনিং) - অনেক বেকারি আইটেমে শুকর বা গরুর ফ্যাট থাকতে পারে।\n"
            "• マーガリン (মার্জারিন) - প্রাণিজ তেলের সংমিশ্রণ থাকতে পারে।\n"
            "• ファットスプレッド (ফ্যাটস্প্রেড) - মিশ্র চর্বি।\n"
            "• 加工油脂 (প্রক্রিয়াজাত চর্বি) - সোর্স অনির্দিষ্ট থাকলে।\n"
            "• コラーゲン (কোলাজেন) - মাছের না হলে প্রাণিজ উৎস।\n"
            "• ゼラチン (সাধারণ জেলাটিন) - মাছের উল্লেখ না থাকলে এড়িয়ে চলুন।\n\n"
            "💡 দ্রষ্টব্য: রাসুলুল্লাহ (সা.) সন্দেহজনক বিষয় পরিহার করার নির্দেশ দিয়েছেন।"
        ),
        "tips": (
            "🛒 জাপানে হালাল কেনাকাটার টিপস:\n\n"
            "১. পাউরুটি/ব্রেড কেনার সময় প্যাকেটে '植物性' (উদ্ভিজ্জ) অথবা '植物油脂' লেখা আছে কি না লক্ষ্য করুন।\n"
            "২. সাধারণ সুপারমার্কেট থেকে মাংস বা সসেজ কেনা পরিহার করুন, হালাল গ্রোসারি শপ থেকে জবেহকৃত মাংস সংগ্রহ করুন।\n"
            "৩. মিষ্টি ও কেক-পেস্ট্রিতে প্রায়শই '洋酒' (মদ) বা 'ラム酒' থাকে, তাই ইনগ্রেডিয়েন্ট দেখে নিন।\n"
            "৪. সিফুড বা মাছের তৈরি খাবারে অনেক সময় ফ্লেভার হিসেবে 'みりん' (মিরিন) বা '料理酒' (কুকিং রাইস ওয়াইন) ব্যবহার করা হয়।"
        ),
        "info": (
            "ℹ️ Halal Check Japan পরিচিতি ও নিয়ম:\n\n"
            "এই বটটি জাপানি খাদ্যপণ্যের লেবেল (原材料名) পড়ে হারাম ও সন্দেহজনক উপাদান শনাক্ত করতে সাহায্য করে।\n\n"
            "📷 কীভাবে ছবি পাঠাবেন:\n"
            "• প্যাকেটের বারকোড নয়, উপাদানের তালিকার (原材料名) সোজা ও স্পষ্ট ছবি তুলুন।\n"
            "• আলো ভালো রাখুন যাতে কাঞ্জি অক্ষরগুলো পরিষ্কার বোঝা যায়।\n\n"
            "⚠️ ডিসক্লেইমার: বটটি প্রাথমিক যাচাইয়ের জন্য সহায়ক। কোনো উপাদানের উৎস অস্পষ্ট থাকলে এড়িয়ে চলাই উত্তম।"
        ),
        "lang_confirm": "ভাষা 'বাংলা' হিসেবে সেট করা হয়েছে! নিচের মেনু ব্যবহার করুন বা ছবি পাঠান।"
    },
    "Indonesian": {
        "haram": (
            "🚫 Bahan yang Pasti Haram (Strictly Haram):\n\n"
            "🐖 Produk Babi & Turunannya:\n"
            "• 豚肉、ポーク | Daging Babi (Pork)\n"
            "• 豚脂肪、豚脂 | Lemak Babi (Pork Fat)\n"
            "• ラード、ハム、ベーコン | Lard, Ham, Bacon\n"
            "• 豚エキス | Ekstrak Babi (Pork Extract)\n"
            "• 豚ゼラチン | Gelatin Babi\n\n"
            "🥩 Daging & Lemak Hewan Non-Halal:\n"
            "• 牛肉、牛脂 | Daging/Lemak Sapi Non-Halal\n"
            "• 鶏肉、チキン | Daging Ayam Non-Halal\n"
            "• 動物性油脂、混合油脂 | Lemak Hewani / Campuran\n"
            "• コンソメ | Kaldu Sup Consomme\n\n"
            "🍷 Alkohol & Bahan Memabukkan:\n"
            "• アルコール、洋酒 | Alkohol, Minuman Keras\n"
            "• 酒、清酒、料理酒 | Sake, Cooking Rice Wine\n"
            "• 味醂、みりん | Mirin (Sake Manis)\n"
            "• 酒精 | Alkohol Etil (Preservative)\n"
            "• ラム、ワイン、ブランディ | Rum, Wine, Brandy"
        ),
        "syubhah": (
            "⚠️ Bahan yang Diragukan (Syubhah):\n\n"
            "• 乳化剤 (Emulsifier) - Syubhah kecuali ada keterangan berasal dari tumbuhan (植物性).\n"
            "• ショートニング (Shortening) - Sering kali mengandung lemak babi atau sapi.\n"
            "• マーガリン (Margarine) - Mungkin mengandung lemak hewani.\n"
            "• ファットスプレッド (Fatspread) - Lemak olesan olahan campuran.\n"
            "• 加工油脂 (Processed Fat) - Sumber lemak tidak spesifik.\n"
            "• コラーゲン (Collagen) - Syubhah kecuali berasal dari ikan (魚由来).\n"
            "• ゼラチン (Gelatin) - Hindari kecuali tertulis berasal dari ikan.\n\n"
            "💡 Catatan: Menghindari hal-hal yang syubhah adalah Sunnah dalam Islam."
        ),
        "tips": (
            "🛒 Tips Berbelanja Halal di Jepang:\n\n"
            "1. Saat membeli roti, pastikan ada tulisan '植物性' (nabati) atau '植物油脂' (minyak nabati).\n"
            "2. Hindari membeli daging mentah, sosis, atau ham dari supermarket Jepang biasa kecuali tersertifikasi halal.\n"
            "3. Makanan manis dan kue (cake/pastry) sangat sering mengandung '洋酒' (alkohol barat) atau 'ラム酒' (rum).\n"
            "4. Banyak camilan ikan atau crackers (Senbei) menggunakan 'みりん' (mirin) atau sake sebagai perasa."
        ),
        "info": (
            "ℹ️ Tentang Halal Check Japan:\n\n"
            "Bot ini membantu menganalisis label bahan makanan Jepang (原材料名) untuk mengidentifikasi kandungan haram atau syubhah.\n\n"
            "📷 Panduan Mengirim Foto:\n"
            "• Ambil foto pada daftar bahan makanan (原材料名), BUKAN barcode.\n"
            "• Pastikan pencahayaan terang dan teks terlihat jelas.\n\n"
            "⚠️ Disclaimer: AI ini berfungsi sebagai alat bantu pemeriksaan awal. Tetap berhati-hatilah."
        ),
        "lang_confirm": "Bahasa telah diatur ke Bahasa Indonesia! Silakan gunakan menu di bawah atau kirim foto daftar bahan."
    },
    "English": {
        "haram": (
            "🚫 Strictly Haram Ingredients:\n\n"
            "🐖 Pork & Swine Products:\n"
            "• 豚肉、ポーク | Pork\n"
            "• 豚脂肪、豚脂 | Pork Fat\n"
            "• ラード、ハム、ベーコン | Lard, Ham, Bacon\n"
            "• 豚エキス | Pork Extract\n"
            "• 豚ゼラチン | Pork Gelatin\n\n"
            "🥩 Non-Halal Meat & Animal Fat:\n"
            "• 牛肉、牛脂 | Non-halal Beef, Tallow\n"
            "• 鶏肉、チキン | Non-halal Chicken\n"
            "• 動物性油脂、混合油脂 | Animal Fat, Mixed Fat\n"
            "• コンソメ | Consomme Soup Stock\n\n"
            "🍷 Alcohol & Intoxicants:\n"
            "• アルコール、洋酒 | Alcohol, Western Liquor\n"
            "• 酒、清酒、料理酒 | Japanese Sake, Cooking Rice Wine\n"
            "• 味醂、みりん | Mirin (Cooking Alcohol)\n"
            "• 酒精 | Ethyl Alcohol\n"
            "• ラム、ワイン、ブランディ | Rum, Wine, Brandy"
        ),
        "syubhah": (
            "⚠️ Syubhah (Doubtful) Ingredients:\n\n"
            "• 乳化剤 (Emulsifier) - Syubhah unless plant-based (植物性).\n"
            "• ショートニング (Shortening) - May contain animal fats.\n"
            "• マーガリン (Margarine) - May contain animal oils.\n"
            "• ファットスプレッド (Fatspread) - Processed blend.\n"
            "• 加工油脂 (Processed Fat) - Unknown fat sources.\n"
            "• コラーゲン (Collagen) - Syubhah unless fish origin.\n"
            "• ゼラチン (Gelatine) - Avoid unless marked 魚由来 (fish).\n\n"
            "💡 Note: Leaving doubtful matters is Sunnah in Islam."
        ),
        "tips": (
            "🛒 Halal Shopping Tips in Japan:\n\n"
            "1. When buying bread, look for 植物性 (plant-derived) or 植物油脂.\n"
            "2. Avoid buying raw meat, sausages, or deli meat from general Japanese supermarkets unless Halal certified.\n"
            "3. Confectionery and desserts frequently contain 洋酒 (Western alcohol) or Mirin for flavoring.\n"
            "4. Many fish and rice snacks (Senbei) contain Mirin or cooking sake."
        ),
        "info": (
            "ℹ️ About Halal Check Japan:\n\n"
            "This bot analyzes Japanese ingredient labels (原材料名) to help identify haram or syubhah components.\n\n"
            "📷 Photo Guidelines:\n"
            "• Capture the ingredient list (原材料名), NOT the barcode.\n"
            "• Keep lighting bright and text fully readable.\n\n"
            "⚠️ Disclaimer: AI serves as a preliminary checking tool. Consult authentic sources if doubt remains."
        ),
        "lang_confirm": "Language set to English! Please use the menu below or send a clear picture of the ingredient label."
    },
    "Japanese": {
        "haram": (
            "🚫 ハラーム原材料 (Strictly Haram):\n\n"
            "• 豚肉、ポーク | 豚肉\n"
            "• 豚脂肪、豚脂 | 豚脂、ラード\n"
            "• ラード、ハム、ベーコン | ラード、ハム、ベーコン\n"
            "• 豚エキス | ポークエキス\n"
            "• 豚ゼラチン | 豚ゼラチン\n"
            "• 牛肉、牛脂 | 非ハラール牛肉、牛脂\n"
            "• 鶏肉、チキン | 非ハラール鶏肉\n"
            "• 動物性油脂、混合油脂 | 動物性・混合油脂\n"
            "• コンソメ | 肉エキス入りコンソメ\n"
            "• アルコール、洋酒 | アルコール、洋酒全般\n"
            "• 酒、清酒、料理酒 | 酒、料理酒\n"
            "• 味醂、みりん | みりん\n"
            "• 酒精 | 酒精\n"
            "• ラム、ワイン | ラム酒、ワイン"
        ),
        "syubhah": (
            "⚠️ 疑わしい原材料 (Syubhah):\n\n"
            "• 乳化剤 - 植物性か動物性か不明な場合。\n"
            "• ショートニング - 動物性油脂混入の可能性あり。\n"
            "• マーガリン - 動物性由来の可能性あり。\n"
            "• ファットスプレッド - 加工油脂。\n"
            "• 加工油脂 - 出所不明な油脂。\n"
            "• コラーゲン / ゼラチン - 魚由来の明記がないもの。"
        ),
        "tips": (
            "🛒 日本でのハラールショッピングのヒント:\n\n"
            "1. パンを購入する際は「植物油脂」や「植物性」の表示を確認してください。\n"
            "2. デザートや洋菓子には風味付けで「洋酒」や「酒精」が多用されます。\n"
            "3. お惣菜や練り製品には「みりん」や肉エキスが含まれることが一般的です。"
        ),
        "info": (
            "ℹ️ Halal Check Japan について:\n\n"
            "原材料名（食品表示ラベル）を撮影して送信するだけで、AIがハラームや疑わしい成分を判定します。\n\n"
            "📷 撮影のコツ:\n"
            "• バーコードではなく「原材料名」の枠内を大きく撮影してください。"
        ),
        "lang_confirm": "言語が「日本語」に設定されました。メニューを使用するか、原材料名の写真を送信してください。"
    },
    "Arabic": {
        "haram": (
            "🚫 المكونات المحرمة قطعيًا (Haram):\n\n"
            "• 豚肉、ポーク | لحم الخنزير\n"
            "• 豚脂肪、豚脂、ラード | دهن وشحم الخنزير\n"
            "• ハム、ベーコン | لحم خنزير مقدد\n"
            "• 豚エキス | خلاصة الخنزير\n"
            "• 牛肉、牛脂 | لح
