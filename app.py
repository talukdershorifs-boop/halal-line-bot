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
    return QuickReply(items=[
        QuickReplyItem(action=CameraAction(label="📷 ক্যামেরা (Camera)")),
        QuickReplyItem(action=CameraRollAction(label="🖼️ গ্যালারি (Gallery)"))
    ])

def get_language_selection_menu():
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
            "🚫 নিশ্চিত হারাম উপাদানসমূহ:\n\n"
            "• 豚肉、ポーク | শুকরের মাংস (Pork)\n"
            "• 豚脂肪、豚脂 | শুকরের চর্বি (Pork Fat)\n"
            "• ラード、ハム、ベーコン | লার্ড, হ্যাম, বেকন\n"
            "• 豚エキス | শুকরের নির্যাস (Pork Extract)\n"
            "• 豚ゼラチン | শুকরের জেলাটিন\n"
            "• 牛肉、牛脂 | সাধারণ গরুর মাংস ও চর্বি\n"
            "• 鶏肉、チキン | সাধারণ মুরগির মাংস\n"
            "• 動物性油脂、混合油脂 | প্রাণিজ চর্বি / মিশ্র চর্বি\n"
            "• コンソメ | কনসোমে স্যুপ ব্রোথ\n"
            "• アルコール、洋酒 | অ্যালকোহল, পশ্চিমা মদ\n"
            "• 酒、清酒、料理酒 | জাপানি সাকে মদ, রান্নার মদ\n"
            "• 味醂、みりん | মিরিন কুকিং অ্যালকোহল\n"
            "• 酒精 | ইথাইল অ্যালকোহল\n"
            "• ラム、ワイン、ブランディ | রাম, ওয়াইন, ব্র্যান্ডি"
        ),
        "syubhah": (
            "⚠️ সন্দেহজনক উপাদানসমূহ (Syubhah):\n\n"
            "• 乳化剤 (ইমালসিফায়ার) - উদ্ভিদ নাকি প্রাণিজ স্পষ্ট না হলে সন্দেহজনক।\n"
            "• ショートニング (শর্টনিং) - অনেক বেকারি আইটেমে প্রাণিজ ফ্যাট থাকতে পারে।\n"
            "• マーガリン (মার্জারিন) - প্রাণিজ তেলের সংমিশ্রণ থাকতে পারে।\n"
            "• ファットスプレッド (ফ্যাটস্প্রেড) - মিশ্র চর্বি।\n"
            "• 加工油脂 (প্রক্রিয়াজাত চর্বি) - সোর্স অনির্দিষ্ট থাকলে।\n"
            "• コラーゲン (কোলাজেন) - মাছের উল্লেখ না থাকলে।\n"
            "• ゼラチン (সাধারণ জেলাটিন) - মাছের না হলে পরিহার্য।"
        ),
        "tips": (
            "🛒 জাপানে হালাল কেনাকাটার টিপস:\n\n"
            "১. পাউরুটি/ব্রেড কেনার সময় প্যাকেটে '植物性' বা '植物油脂' লেখা আছে কি না লক্ষ্য করুন।\n"
            "২. সাধারণ সুপারমার্কেট থেকে মাংস কেনা পরিহার করুন, হালাল শপ থেকে সংগ্রহ করুন।\n"
            "৩. মিষ্টি ও কেক-পেস্ট্রিতে প্রায়শই '洋酒' (মদ) থাকে, তাই উপাদান দেখে নিন।\n"
            "৪. সিফুড বা মাছের তৈরি খাবারে অনেক সময় ফ্লেভার হিসেবে 'みりん' বা '料理酒' ব্যবহার করা হয়।"
        ),
        "info": (
            "ℹ️ Halal Check Japan পরিচিতি ও নিয়ম:\n\n"
            "এই বটটি জাপানি খাদ্যপণ্যের লেবেল (原材料名) পড়ে হারাম ও সন্দেহজনক উপাদান শনাক্ত করতে সাহায্য করে।\n\n"
            "📷 কীভাবে ছবি পাঠাবেন:\n"
            "• প্যাকেটের বারকোড নয়, উপাদানের তালিকার (原材料名) সোজা ও স্পষ্ট ছবি তুলুন।"
        ),
        "lang_confirm": "ভাষা 'বাংলা' হিসেবে সেট করা হয়েছে! নিচের মেনু ব্যবহার করুন বা ছবি পাঠান।"
    },
    "Indonesian": {
        "haram": (
            "🚫 Bahan yang Pasti Haram:\n\n"
            "• 豚肉、ポーク | Daging Babi\n"
            "• 豚脂肪、豚脂 | Lemak Babi\n"
            "• ラード、ハム、ベーコン | Lard, Ham, Bacon\n"
            "• 豚エキス | Ekstrak Babi\n"
            "• 豚ゼラチン | Gelatin Babi\n"
            "• 牛肉、牛脂 | Daging/Lemak Sapi Non-Halal\n"
            "• 鶏肉、チキン | Daging Ayam Non-Halal\n"
            "• 動物性油脂、混合油脂 | Lemak Hewani / Campuran\n"
            "• コンソメ | Kaldu Sup Consomme\n"
            "• アルコール、洋酒 | Alkohol, Minuman Keras\n"
            "• 酒、清酒、料理酒 | Sake, Cooking Rice Wine\n"
            "• 味醂、みりん | Mirin\n"
            "• 酒精 | Alkohol Etil\n"
            "• ラム、ワイン、ブランディ | Rum, Wine, Brandy"
        ),
        "syubhah": (
            "⚠️ Bahan yang Diragukan (Syubhah):\n\n"
            "• 乳化剤 (Emulsifier) - Syubhah kecuali nabati (植物性).\n"
            "• ショートニング (Shortening) - Sering mengandung lemak hewani.\n"
            "• マーガリン (Margarine) - Mungkin mengandung lemak hewani.\n"
            "• ファットスプレッド (Fatspread) - Campuran lemak olahan.\n"
            "• 加工油脂 (Processed Fat) - Sumber lemak tidak spesifik.\n"
            "• コラーゲン / ゼラチン - Hindari kecuali dari ikan (魚由来)."
        ),
        "tips": (
            "🛒 Tips Berbelanja Halal di Jepang:\n\n"
            "1. Saat membeli roti, pastikan ada tulisan 植物性 (nabati) atau 植物油脂.\n"
            "2. Hindari membeli daging mentah dari supermarket biasa kecuali bersertifikasi halal.\n"
            "3. Kue dan permen sering mengandung 洋酒 (alkohol barat) untuk aroma.\n"
            "4. Camilan ikan atau crackers sering menggunakan みりん atau sake."
        ),
        "info": (
            "ℹ️ Tentang Halal Check Japan:\n\n"
            "Bot ini menganalisis label bahan makanan Jepang (原材料名) untuk mendeteksi kandungan haram atau syubhah.\n\n"
            "📷 Panduan Foto:\n"
            "• Foto daftar bahan (原材料名), BUKAN barcode."
        ),
        "lang_confirm": "Bahasa telah diatur ke Bahasa Indonesia! Silakan gunakan menu atau kirim foto."
    },
    "English": {
        "haram": (
            "🚫 Strictly Haram Ingredients:\n\n"
            "• 豚肉、ポーク | Pork\n"
            "• 豚脂肪、豚脂 | Pork Fat\n"
            "• ラード、ハム、ベーコン | Lard, Ham, Bacon\n"
            "• 豚エキス | Pork Extract\n"
            "• 豚ゼラチン | Pork Gelatin\n"
            "• 牛肉、牛脂 | Non-halal Beef, Tallow\n"
            "• 鶏肉、チキン | Non-halal Chicken\n"
            "• 動物性油脂、混合油脂 | Animal Fat, Mixed Fat\n"
            "• コンソメ | Consomme Soup Stock\n"
            "• アルコール、洋酒 | Alcohol, Western Liquor\n"
            "• 酒、清酒、料理酒 | Japanese Sake, Cooking Wine\n"
            "• 味醂、みりん | Mirin\n"
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
            "• コラーゲン / ゼラチン - Avoid unless marked 魚由来 (fish)."
        ),
        "tips": (
            "🛒 Halal Shopping Tips in Japan:\n\n"
            "1. When buying bread, look for 植物性 (plant-derived) or 植物油脂.\n"
            "2. Avoid buying raw meat from general supermarkets unless certified Halal.\n"
            "3. Confectionery and desserts frequently contain 洋酒 (Western alcohol).\n"
            "4. Many fish snacks contain Mirin or cooking sake."
        ),
        "info": (
            "ℹ️ About Halal Check Japan:\n\n"
            "Analyzes Japanese ingredient labels (原材料名) to identify haram or syubhah components.\n\n"
            "📷 Photo Guidelines:\n"
            "• Capture the ingredient list (原材料名), NOT the barcode."
        ),
        "lang_confirm": "Language set to English! Please use the menu or send a clear picture."
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
            "• アルコール、洋酒
