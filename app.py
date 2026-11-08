import os
import io
from flask import Flask, request, abort
from PIL import Image
import google.generativeai as genai

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
    MessageAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, ImageMessageContent

app = Flask(__name__)

CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# মেমোরি ক্র্যাশ ঠেকাতে gRPC বাদ দিয়ে হালকা REST ট্রান্সপোর্ট ব্যবহার
genai.configure(api_key=GEMINI_API_KEY, transport="rest")

user_languages = {}

def get_language_selection_menu():
    items = [
        QuickReplyItem(action=MessageAction(label="🇧🇩 বাংলা", text="Set: বাংলা")),
        QuickReplyItem(action=MessageAction(label="🇬🇧 English", text="Set: English")),
        QuickReplyItem(action=MessageAction(label="🇯🇵 日本語", text="Set: 日本語")),
        QuickReplyItem(action=MessageAction(label="🇸🇦 العربية", text="Set: العربية")),
    ]
    return QuickReply(items=items)

CHECKED_DATA = {
    "Bengali": {
        "haram": (
            "🚫 হারাম উপাদানসমূহ (Haram Ingredients):\n"
            "豚肉、ポーク | শুকরের মাংস (Pork)\n"
            "豚脂肪、豚脂 | শুকরের চর্বি (Pork Fat)\n"
            "ラード、ハム | লার্ড, হ্যাম (Lard, Ham)\n"
            "牛肉、牛脂 | গরুর মাংস, চর্বি (Beef, Tallow)\n"
            "動物性油脂 | প্রাণিজ চর্বি (Animal Fat)\n"
            "混合油脂 | মিশ্র চর্বি (Mixed Fat)\n"
            "コンソメ | কনসোমে ব্রোথ (Consomme)\n"
            "鶏肉、チキン | মুরগির মাংস (Chicken)\n"
            "アルコール | অ্যালকোহল (Alcohol)\n"
            "洋酒 | পশ্চিমা মদ (Western Liquor)\n"
            "酒精 | ইথাইল অ্যালকোহল (Ethyl Alcohol)\n"
            "ラム、ワイン | রাম, ওয়াইন (Rum, Wine)\n"
            "ブランディ | ব্র্যান্ডি (Brandy)\n"
            "ウィスキー | হুইস্কি (Whiskey)\n"
            "酒 | সাকে মদ (Japanese Sake)\n"
            "味醂、みりん | মিরিন কুকিং অ্যালকোহল (Mirin)\n"
            "ゼラチン | জেলাটিন (Gelatine - অ-হালাল উৎস)"
        ),
        "syubhah": (
            "⚠️ সন্দেহজনক উপাদানসমূহ (Syubhah Ingredients):\n"
            "加工油脂 | প্রক্রিয়াজাত চর্বি (Processed Fat)\n"
            "食用油脂 | রান্নার তেল/চর্বি (Fat for cooking)\n"
            "マーガリン | মার্জারিন (Margarine)\n"
            "ショートニング | শর্টনিং (Shortening)\n"
            "ファットスプレッド | ফ্যাটস্প্রেড (Fatspread)\n"
            "コラーゲン | কোলাজেন (Collagen)\n"
            "乳化剤 | ইমালসিফায়ার (Emulsifier)\n\n"
            "💡 দ্রষ্টব্য: ইসলামে সন্দেহজনক বিষয় পরিহার করা সুন্নাহ। নিশ্চিত উৎস না জেনে এগুলো পরিহার করাই উত্তম।"
        ),
        "info": (
            "ℹ️ বটের পরিচিতি ও নিয়মাবলি:\n\n"
            "যারা জাপানি কাঞ্জি পড়তে পারেন না, তাদের সুবিধার্থে এই বটটি তৈরি করা হয়েছে। পণ্যের প্যাকেটের কাঞ্জি পড়ে এটি হারাম বা সন্দেহজনক উপাদান শনাক্ত করতে সহায়তা করে।\n\n"
            "ব্যবহার করার নিয়ম:\n"
            "১. পণ্যের উপাদানের তালিকার (原材料名) স্পষ্ট ছবি তুলুন।\n"
            "২. ছবিটি সরাসরি এই চ্যাটে পাঠিয়ে দিন।\n\n"
            "যাচাইকৃত তালিকা দেখতে নিচের 'Checked Ingredients' অপশনে চাপ দিন।"
        ),
        "lang_confirm": "ভাষা 'বাংলা' হিসেবে সেট করা হয়েছে! পণ্যের উপাদানের (原材料名) পরিষ্কার ছবি পাঠান।"
    },
    "English": {
        "haram": (
            "🚫 Haram Ingredients:\n"
            "豚肉、ポーク | Pork\n"
            "豚脂肪、豚脂 | Pork Fat\n"
            "ラード、ハム | Lard, Ham\n"
            "牛肉、牛脂 | Beef, Beef Fat\n"
            "動物性油脂 | Animal Fat\n"
            "混合油脂 | Mixed Fat\n"
            "コンソメ | Consomme\n"
            "鶏肉、チキン | Chicken\n"
            "アルコール | Alcohol\n"
            "洋酒 | Western Alcohol\n"
            "酒精 | Ethyl Alcohol\n"
            "ラム、ワイン | Rum, Wine\n"
            "ブランディ | Brandy\n"
            "ウィスキー | Whiskey\n"
            "酒 | Sake\n"
            "味醂、みりん | Mirin\n"
            "ゼラチン | Gelatine"
        ),
        "syubhah": (
            "⚠️ Syubhah (Doubtful) Ingredients:\n"
            "加工油脂 | Processed Fat\n"
            "食用油脂 | Fat for cooking\n"
            "マーガリン | Margarine\n"
            "ショートニング | Shortening\n"
            "ファットスプレッド | Fatspread\n"
            "コラーゲン | Collagen\n"
            "乳化剤 | Emulsifier\n\n"
            "💡 Note: Avoiding doubtful matters is Sunnah in Islam. It is best to avoid unless plant-based origin is verified."
        ),
        "info": (
            "ℹ️ About Halal Check Japan:\n\n"
            "I was developed for people who cannot read kanji but wish to look up ingredients on Japanese goods. I analyze text on images and identify ingredients that are haram or syubhah.\n\n"
            "How to use:\n"
            "1. Take a clear picture of the product label (原材料名).\n"
            "2. Send it directly to this chat.\n\n"
            "To view the checked ingredient lists, click 'Checked Ingredients'."
        ),
        "lang_confirm": "Language set to English! Please send a clear picture of the ingredient label (原材料名)."
    },
    "Japanese": {
        "haram": (
            "🚫 ハラーム原材料 (Haram Ingredients):\n"
            "豚肉、ポーク | 豚肉\n"
            "豚脂肪、豚脂 | ラード・豚脂\n"
            "ラード、ハム | ハムなど豚肉加工品\n"
            "牛肉、牛脂 | 非ハラール牛肉・牛脂\n"
            "動物性油脂 | 動物性油脂\n"
            "混合油脂 | 混合油脂\n"
            "コンソメ | コンソメ\n"
            "鶏肉、チキン | 非ハラール鶏肉\n"
            "アルコール | アルコール\n"
            "洋酒 | 洋酒全般\n"
            "酒精 | 酒精\n"
            "ラム、ワイン | ラム酒・ワイン\n"
            "ブランディ | ブランデー\n"
            "ウィスキー | ウイスキー\n"
            "酒 | 日本酒・料理酒\n"
            "味醂、みりん | みりん\n"
            "ゼラチン | ゼラチン（豚・牛由来）"
        ),
        "syubhah": (
            "⚠️ 疑わしい原材料 (Syubhah Ingredients):\n"
            "加工油脂 | 加工油脂\n"
            "食用油脂 | 食用油脂\n"
            "マーガリン | マーガリン\n"
            "ショートニング | ショートニング\n"
            "ファットスプレッド | ファットスプレッド\n"
            "コラーゲン | コラーゲン\n"
            "乳化剤 | 乳化剤\n\n"
            "💡 留意点: 出所が植物性であると確認できない場合は、摂取を控えることが推奨されます。"
        ),
        "info": (
            "ℹ️ Halal Check Japanについて:\n\n"
            "日本の食品表示（原材料名）の漢字が読めない方のために開発されました。画像から原材料を読み取り、ハラームや疑わしい成分を判定します。\n\n"
            "使い方:\n"
            "1. 原材料名がはっきりと写った写真を撮影してください。\n"
            "2. このチャットにそのまま送信してください。"
        ),
        "lang_confirm": "言語が「日本語」に設定されました。原材料名の写真を送信してください。"
    },
    "Arabic": {
        "haram": (
            "🚫 المكونات المحرمة (Haram Ingredients):\n"
            "豚肉、ポーク | لحم الخنزير\n"
            "豚脂肪、豚脂 | دهن الخنزير\n"
            "ラード、ハム | شحم الخنزير، لحم الخنزير المقدد\n"
            "牛肉、牛脂 | لحم وشحم البقر (غير المذبوح حلالاً)\n"
            "動物性油脂 | دهون حيوانية\n"
            "混合油脂 | دهون مختلطة\n"
            "コンソメ | مرقة اللحم\n"
            "鶏肉、チキン | لحم الدجاج (غير الحلال)\n"
            "アルコール | كحول\n"
            "洋酒 | كحول غربي\n"
            "酒精 | كحول الإيثيل\n"
            "ラム、ワイン | رم، نبيذ\n"
            "ブランディ | براندي\n"
            "ウィスキー | ويسكي\n"
            "酒 | ساكي (خمور يابانية)\n"
            "味醂、みりん | ميرين (نبيذ طبخ)\n"
            "ゼラチン | جيلاتين (حيواني)"
        ),
        "syubhah": (
            "⚠️ المكونات المشتبه فيها (الشبهات - Syubhah):\n"
            "加工油脂 | دهون معالجة\n"
            "食用油脂 | دهون الطبخ\n"
            "マーガリン | سمن نباتي/مارجرين\n"
            "ショートニング | شورتنينج\n"
            "ファットスプレッド | سمن دهني\n"
            "コラーゲン | كولاجين\n"
            "乳化剤 | مستحلبات\n\n"
            "💡 ملاحظة: ترك الشبهات من سنن الإسلام، والأفضل تجنب ما اشتبه أصله حتى يتبين مصدره."
        ),
        "info": (
            "ℹ️ عن هذا البوت:\n\n"
            "تم تصميم هذا البوت لمساعدة المسلمين في اليابان على قراءة قائمة المكونات (原材料名) والتحقق من احتوائها على مكونات محرمة أو مشبوهة.\n\n"
            "طريقة الاستخدام:\n"
            "1. التقط صورة واضحة لقائمة المكونات (原材料名).\n"
            "2. أرسلها هنا في المحادثة مباشرة."
        ),
        "lang_confirm": "تم ضبط اللغة إلى العربية! الرجاء إرسال صورة واضحة لقائمة المكونات (原材料名)."
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
    text = event.message.text.strip()
    current_lang = user_languages.get(user_id, "Bengali")

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        if text.lower() == "checked ingredients":
            data = CHECKED_DATA[current_lang]
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=data["haram"]), TextMessage(text=data["syubhah"])]
                )
            )
        elif text.lower() == "info":
            data = CHECKED_DATA[current_lang]
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=data["info"])]
                )
            )
        elif text.startswith("Set: "):
            chosen = text.replace("Set: ", "").strip()
            if "বাংলা" in chosen:
                user_languages[user_id] = "Bengali"
            elif "日本語" in chosen:
                user_languages[user_id] = "Japanese"
            elif "العربية" in chosen:
                user_languages[user_id] = "Arabic"
            else:
                user_languages[user_id] = "English"

            new_lang = user_languages[user_id]
            reply = CHECKED_DATA[new_lang]["lang_confirm"]

            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply)]
                )
            )
        else:
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(
                            text="Select Language / ভাষা বেছে নিন / 言語を選択 / اختر اللغة:",
                            quick_reply=get_language_selection_menu()
                        )
                    ]
                )
            )

@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event):
    user_id = event.source.user_id
    selected_lang = user_languages.get(user_id, "Bengali")

    try:
        with ApiClient(configuration) as api_client:
            blob_api = MessagingApiBlob(api_client)
            raw_bytes = blob_api.get_message_content(event.message.id)

        # মেমোরি রক্ষা করতে ছবি অপ্টিমাইজ করা
        img = Image.open(io.BytesIO(raw_bytes))
        img.thumbnail((1024, 1024))
        img_buffer = io.BytesIO()
        img.convert('RGB').save(img_buffer, format="JPEG", quality=80)
        optimized_bytes = img_buffer.getvalue()

        prompt = f"""
        You are an expert Islamic Halal Food Inspector in Japan.
        Inspect the Japanese food label (原材料名) in this image.

        Forbidden Haram ingredients to flag:
        - Pork / Swine: 豚肉, ポーク, 豚脂, 豚脂肪, ラード, ハム, 豚エキス
        - Animal Meat/Fats: 牛肉, 牛脂, 動物性油脂, 混合油脂, コンソメ, 鶏肉, チキン
        - Alcohol: アルコール, 洋酒, 酒精, ラム, ワイン, ブランディ, ウィスキー, 酒, 料理酒, 清酒, 味醂, みりん
        - Gelatin: ゼラチン (unless specified as fish/plant)

        Doubtful Syubhah ingredients to flag:
        - 加工油脂, 食用油脂, マーガリン, ショートニング, ファットスプレッド, コラーゲン, 乳化剤

        Respond clearly in {selected_lang}:
        1. Final Verdict: [✅ হালাল / HALAL] or [❌ হারাম / HARAM] or [⚠️ সন্দেহজনক / SYUBHAH]
        2. Found Ingredients & Explanation: Kanji, meaning, and why.
        3. Clarification for Syubhah: Mention that avoiding doubtful matters is Sunnah.
        """

        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content([
            prompt,
            {"mime_type": "image/jpeg", "data": optimized_bytes}
        ])
        result_text = response.text.strip()

    except Exception as e:
        result_text = f"দুঃখিত, ছবিটি বিশ্লেষণ করতে সমস্যা হচ্ছে। ত্রুটি: {str(e)}"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=result_text)]
            )
        )
