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
        "haram": """🚫 নিশ্চিত হারাম উপাদানসমূহ:

• 豚肉、ポーク | শুকরের মাংস (Pork)
• 豚脂肪、豚脂 | শুকরের চর্বি (Pork Fat)
• ラード、ハム、ベーコン | লার্ড, হ্যাম, বেকন
• 豚エキス | শুকরের নির্যাস (Pork Extract)
• 豚ゼラチン | শুকরের জেলাটিন
• 牛肉、牛脂 | সাধারণ গরুর মাংস ও চর্বি
• 鶏肉、チキン | সাধারণ মুরগির মাংস
• 動物性油脂、混合油脂 | প্রাণিজ চর্বি / মিশ্র চর্বি
• コンソメ | কনসোমে স্যুপ ব্রোথ
• アルコール、洋酒 | অ্যালকোহল, পশ্চিমা মদ
• 酒、清酒、料理酒 | জাপানি সাকে মদ, রান্নার মদ
• 味醂、みりん | মিরিন কুকিং অ্যালকোহল
• 酒精 | ইথাইল অ্যালকোহল
• ラム、ワイン、ブランディ | রাম, ওয়াইন, ব্র্যান্ডি""",

        "syubhah": """⚠️ সন্দেহজনক উপাদানসমূহ (Syubhah):

• 乳化剤 (ইমালসিফায়ার) - উৎস উদ্ভিদ না প্রাণিজ তা স্পষ্ট না হলে সন্দেহজনক।
• ショートニング (শর্টনিং) - বেকারি আইটেমে প্রাণিজ ফ্যাট থাকতে পারে।
• マーガリン (মার্জারিন) - প্রাণিজ তেলের সংমিশ্রণ থাকতে পারে।
• ファットスプレッド (ফ্যাটস্প্রেড) - মিশ্র প্রক্রিয়াজাত চর্বি।
• 加工油脂 (প্রক্রিয়াজাত চর্বি) - সোর্স অনির্দিষ্ট থাকলে।
• コラーゲン / ゼラチン - মাছের নিশ্চিত উল্লেখ না থাকলে পরিহার্য।""",

        "tips": """🛒 জাপানে হালাল কেনাকাটার টিপস:

১. পাউরুটি/ব্রেড কেনার সময় প্যাকেটে '植物性' বা '植物油脂' লেখা আছে কি না লক্ষ্য করুন।
২. সাধারণ সুপারমার্কেট থেকে মাংস বা সসেজ কেনা পরিহার করুন, হালাল গ্রোসারি থেকে সংগ্রহ করুন।
৩. মিষ্টি ও কেক-পেস্ট্রিতে প্রায়শই '洋酒' (মদ) থাকে, তাই উপাদান দেখে নিন।
৪. সিফুড বা স্ন্যাক্সে অনেক সময় ফ্লেভার হিসেবে 'みりん' বা '料理酒' ব্যবহার করা হয়।""",

        "info": """ℹ️ Halal Check Japan পরিচিতি ও নিয়ম:

এই বটটি জাপানি খাদ্যপণ্যের লেবেল (原材料名) পড়ে হারাম ও সন্দেহজনক উপাদান শনাক্ত করতে সাহায্য করে।

📷 ছবি তোলার নিয়ম:
• বারকোড নয়, উপাদানের তালিকার (原材料名) সোজা ও স্পষ্ট ছবি তুলুন।""",

        "lang_confirm": "ভাষা 'বাংলা' হিসেবে সেট করা হয়েছে! নিচের মেনু ব্যবহার করুন বা ছবি পাঠান।"
    },

    "Indonesian": {
        "haram": """🚫 Bahan yang Pasti Haram:

• 豚肉、ポーク | Daging Babi (Pork)
• 豚脂肪、豚脂 | Lemak Babi (Pork Fat)
• ラード、ハム、ベーコン | Lard, Ham, Bacon
• 豚エキス | Ekstrak Babi
• 豚ゼラチン | Gelatin Babi
• 牛肉、牛脂 | Daging/Lemak Sapi Non-Halal
• 鶏肉、チキン | Daging Ayam Non-Halal
• 動物性油脂、混合油脂 | Lemak Hewani / Campuran
• コンソメ | Kaldu Sup Consomme
• アルコール、洋酒 | Alkohol, Minuman Keras
• 酒、清酒、料理酒 | Sake, Cooking Rice Wine
• 味醂、みりん | Mirin
• 酒精 | Alkohol Etil
• ラム、ワイン、ブランディ | Rum, Wine, Brandy""",

        "syubhah": """⚠️ Bahan yang Diragukan (Syubhah):

• 乳化剤 (Emulsifier) - Syubhah kecuali nabati (植物性).
• ショートニング (Shortening) - Sering mengandung lemak hewani.
• マーガリン (Margarine) - Mungkin mengandung lemak hewani.
• ファットスプレッド (Fatspread) - Campuran lemak olahan.
• 加工油脂 (Processed Fat) - Sumber lemak tidak spesifik.
• コラーゲン / ゼラチン - Hindari kecuali dari ikan (魚由来).""",

        "tips": """🛒 Tips Berbelanja Halal di Jepang:

1. Saat membeli roti, pastikan ada tulisan 植物性 (nabati) atau 植物油脂.
2. Hindari membeli daging mentah dari supermarket biasa kecuali bersertifikasi halal.
3. Kue dan permen sering mengandung 洋酒 (alkohol barat) untuk aroma.
4. Camilan ikan atau crackers sering menggunakan みりん atau sake.""",

        "info": """ℹ️ Tentang Halal Check Japan:

Bot ini menganalisis label bahan makanan Jepang (原材料名) untuk mendeteksi kandungan haram atau syubhah.

📷 Panduan Foto:
• Foto daftar bahan (原材料名), BUKAN barcode.""",

        "lang_confirm": "Bahasa telah diatur ke Bahasa Indonesia! Silakan gunakan menu atau kirim foto."
    },

    "English": {
        "haram": """🚫 Strictly Haram Ingredients:

• 豚肉、ポーク | Pork
• 豚脂肪、豚脂 | Pork Fat
• ラード、ハム、ベーコン | Lard, Ham, Bacon
• 豚エキス | Pork Extract
• 豚ゼラチン | Pork Gelatin
• 牛肉、牛脂 | Non-halal Beef, Tallow
• 鶏肉、チキン | Non-halal Chicken
• 動物性油脂、混合油脂 | Animal Fat, Mixed Fat
• コンソメ | Consomme Soup Stock
• アルコール、洋酒 | Alcohol, Western Liquor
• 酒、清酒、料理酒 | Japanese Sake, Cooking Wine
• 味醂、みりん | Mirin
• 酒精 | Ethyl Alcohol
• ラム、ワイン、ブランディ | Rum, Wine, Brandy""",

        "syubhah": """⚠️ Syubhah (Doubtful) Ingredients:

• 乳化剤 (Emulsifier) - Syubhah unless plant-based (植物性).
• ショートニング (Shortening) - May contain animal fats.
• マーガリン (Margarine) - May contain animal oils.
• ファットスプレッド (Fatspread) - Processed blend.
• 加工油脂 (Processed Fat) - Unknown fat sources.
• コラーゲン / ゼラチン - Avoid unless marked 魚由来 (fish).""",

        "tips": """🛒 Halal Shopping Tips in Japan:

1. When buying bread, look for 植物性 (plant-derived) or 植物油脂.
2. Avoid buying raw meat from general supermarkets unless certified Halal.
3. Confectionery and desserts frequently contain 洋酒 (Western alcohol).
4. Many fish snacks contain Mirin or cooking sake.""",

        "info": """ℹ️ About Halal Check Japan:

Analyzes Japanese ingredient labels (原材料名) to identify haram or syubhah components.

📷 Photo Guidelines:
• Capture the ingredient list (原材料名), NOT the barcode.""",

        "lang_confirm": "Language set to English! Please use the menu or send a clear picture."
    },

    "Japanese": {
        "haram": """🚫 ハラーム原材料 (Strictly Haram):

• 豚肉、ポーク | 豚肉
• 豚脂肪、豚脂 | 豚脂、ラード
• ラード、ハム、ベーコン | ラード、ハム、ベーコン
• 豚エキス | ポークエキス
• 豚ゼラチン | 豚ゼラチン
• 牛肉、牛脂 | 非ハラール牛肉、牛脂
• 鶏肉、チキン | 非ハラール鶏肉
• 動物性油脂、混合油脂 | 動物性・混合油脂
• コンソメ | 肉エキス入りコンソメ
• アルコール、洋酒 | アルコール、洋酒全般
• 酒、清酒、料理酒 | 酒、料理酒
• 味醂、みりん | みりん
• 酒精 | 酒精
• ラム、ワイン | ラム酒、ワイン""",

        "syubhah": """⚠️ 疑わしい原材料 (Syubhah):

• 乳化剤 - 植物性か動物性か不明な場合。
• ショートニング - 動物性油脂混入の可能性あり。
• マーガリン - 動物性由来の可能性あり。
• ファットスプレッド - 加工油脂。
• 加工油脂 - 出所不明な油脂。
• コラーゲン / ゼラチン - 魚由来の明記がないもの。""",

        "tips": """🛒 日本でのハラールショッピングのヒント:

1. パンを購入する際は「植物油脂」や「植物性」の表示を確認してください。
2. デザートや洋菓子には風味付けで「洋酒」や「酒精」が多用されます。
3. お惣菜や練り製品には「みりん」や肉エキスが含まれることが一般的です。""",

        "info": """ℹ️ Halal Check Japan について:

原材料名（食品表示ラベル）を撮影して送信するだけで、AIがハラームや疑わしい成分を判定します。

📷 撮影のコツ:
• バーコードではなく「原材料名」の枠内を撮影してください。""",

        "lang_confirm": "言語が「日本語」に設定されました。メニューを使用するか、原材料名の写真を送信してください。"
    },

    "Arabic": {
        "haram": """🚫 Haram:

• 豚肉, ポーク | Pork
• 豚脂肪, 豚脂, ラード | Pork Fat, Lard
• ハム, ベーコン | Ham, Bacon
• 豚エキス | Pork Extract
• 牛肉, 牛脂 | Non-halal Beef, Tallow
• 鶏肉, チキン | Non-halal Chicken
• 動物性油脂 | Animal Fat
• コンソメ | Consomme
• アルコール, 洋酒 | Alcohol, Liquor
• 酒, 清酒, 料理酒 | Sake, Cooking Rice Wine
• 味醂, みりん | Mirin
• 酒精 | Ethyl Alcohol""",

        "syubhah": """⚠️ Syubhah:

• 乳化剤 (Emulsifier) - Syubhah unless plant-based (植物性)
• ショートニング (Shortening)
• マーガリン (Margarine)
• 加工油脂 (Processed Fat)
• ゼラチン (Gelatine) - Avoid unless marked 魚由来 (fish)""",

        "tips": """🛒 Halal Tips:

1. When buying bread, look for 植物性 (plant-derived).
2. Western alcohol (洋酒) is commonly used in Japanese desserts.
3. Mirin and cooking wine are frequently added to snacks and seafood.""",

        "info": """ℹ️ Halal Check Japan:

Photo Guidelines:
• Capture the ingredient list (原材料名), NOT the barcode.""",

        "lang_confirm": "Language set to Arabic! Please send a clear picture."
    }
}

@app.route("/", methods=['GET'])
def index():
    return "Halal Checker Bot is running successfully!"

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
    user_id = event.source.user_id
    raw_text = event.message.text.strip()
    text = raw_text.lower()
    current_lang = user_languages.get(user_id, "Bengali")

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        if any(k in text for k in ["scan", "take a picture", "ছবি", "potret", "kamera"]):
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(
                            text="নিচের কোনটি দিয়ে পণ্যের উপাদানের (原材料名) ছবি দিতে চান তা বেছে নিন:",
                            quick_reply=get_image_source_quick_reply()
                        )
                    ]
                )
            )
        elif any(k in text for k in ["haram", "হারাম"]):
            reply = CHECKED_DATA[current_lang]["haram"]
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply)])
            )
        elif any(k in text for k in ["syubhah", "সন্দেহজনক"]):
            reply = CHECKED_DATA[current_lang]["syubhah"]
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply)])
            )
        elif any(k in text for k in ["tip", "টিপস"]):
            reply = CHECKED_DATA[current_lang]["tips"]
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply)])
            )
        elif any(k in text for k in ["info", "guide", "সাহায্য", "tentang", "about"]):
            reply = CHECKED_DATA[current_lang]["info"]
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply)])
            )
        elif any(k in text for k in ["language", "ভাষা", "bahasa"]):
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(
                            text="Select Language / ভাষা বেছে নিন / Pilih Bahasa:",
                            quick_reply=get_language_selection_menu()
                        )
                    ]
                )
            )
        elif raw_text.startswith("Set: "):
            chosen = raw_text.replace("Set: ", "").strip()
            if "বাংলা" in chosen:
                user_languages[user_id] = "Bengali"
            elif "indonesia" in chosen.lower():
                user_languages[user_id] = "Indonesian"
            elif "日本語" in chosen:
                user_languages[user_id] = "Japanese"
            elif "العربية" in chosen:
                user_languages[user_id] = "Arabic"
            else:
                user_languages[user_id] = "English"

            new_lang = user_languages[user_id]
            reply = CHECKED_DATA[new_lang]["lang_confirm"]
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply)])
            )
        else:
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(
                            text="নিচের মেনু থেকে অপশন বেছে নিন অথবা পণ্যের উপাদানের (原材料名) ছবি পাঠান।",
                            quick_reply=get_language_selection_menu()
                        )
                    ]
                )
            )

def call_gemini_vision(prompt, image_b64):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}}
            ]
        }],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 800
        }
    }
    # টাইমআউট ৯০ সেকেন্ডে উন্নীত করা হলো যাতে নেটওয়ার্ক বা জেনারেশন লেটেন্সিতে ড্রপ না করে
    res = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=90)
    if res.status_code == 200:
        data = res.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    else:
        raise Exception(f"Google API Error ({res.status_code}): {res.text}")

@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event):
    user_id = event.source.user_id
    selected_lang = user_languages.get(user_id, "Bengali")

    try:
        with ApiClient(configuration) as api_client:
            blob_api = MessagingApiBlob(api_client)
            raw_bytes = blob_api.get_message_content(event.message.id)

        # ইমেজ অপ্টিমাইজেশন: দ্রুত আপলোড ও ফাস্ট প্রসেসিং নিশ্চিত করতে ৭৫০px স্কেলিং
        img = Image.open(io.BytesIO(raw_bytes))
        img.thumbnail((750, 750))
        out_buf = io.BytesIO()
        img.convert('RGB').save(out_buf, format="JPEG", quality=70, optimize=True)
        image_b64 = base64.b64encode(out_buf.getvalue()).decode("utf-8")

        del raw_bytes, img, out_buf
        gc.collect()

        prompt = f"""
        Inspect the Japanese food packaging ingredient label (原材料名) shown in the image as a Halal Inspector.

        RULES:
        - Haram: 豚肉, ポーク, 豚脂, 豚脂肪, ラード, ハム, ベーコン, 豚エキス, 豚ゼラチン, 牛肉, 牛脂, 動物性油脂, 混合油脂, コンソメ, 鶏肉, チキン, アルコール, 洋酒, 酒精, ラム, ワイン, ブランディ, ウィスキー, 酒, 料理酒, 清酒, 味醂, みりん, ゼラチン (unless fish/plant).
        - Syubhah: 加工油脂, 食用油脂, マーガリン, ショートニング, ファットスプレッド, コラーゲン, 乳化剤.

        OUTPUT REQUIREMENTS:
        1. Language: {selected_lang}.
        2. Verdict header: [✅ হালাল / HALAL] or [❌ হারাম / HARAM] or [⚠️ সন্দেহজনক / SYUBHAH].
        3. Clear, concise breakdown of detected items with Kanji and translation.
        4. If Syubhah: note that leaving doubtful matters is Sunnah.
        """

        result_text = call_gemini_vision(prompt, image_b64)

    except Exception as e:
        result_text = f"দুঃখিত, ছবিটি বিশ্লেষণ করতে সমস্যা হয়েছে। বিস্তারিত: {str(e)}"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=result_text)]
            )
        )
