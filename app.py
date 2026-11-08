import os
from flask import Flask, request, abort
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
genai.configure(api_key=GEMINI_API_KEY)

user_languages = {}

def get_language_selection_menu():
    items = [
        QuickReplyItem(action=MessageAction(label="🇯🇵 日本語", text="Set: 日本語")),
        QuickReplyItem(action=MessageAction(label="🇬🇧 English", text="Set: English")),
        QuickReplyItem(action=MessageAction(label="🇧🇩 বাংলা", text="Set: বাংলা")),
        QuickReplyItem(action=MessageAction(label="🇪🇸 Español", text="Set: Español")),
        QuickReplyItem(action=MessageAction(label="🇨🇳 中文", text="Set: 中文")),
    ]
    return QuickReply(items=items)

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

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # ১. Checked Ingredients বাটনের রেসপন্স
        if text.lower() == "checked ingredients":
            msg1 = (
                "Haram Ingredients\n"
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
            )
            msg2 = (
                "Syubhah Ingredients\n"
                "加工油脂 | Processed Fat\n"
                "食用油脂 | Fat for cooking\n"
                "マーガリン | Margarine\n"
                "ショートニング | Shortening\n"
                "ファットスプレッド | Fatspread\n"
                "コラーゲン | Collagen\n"
                "乳化剤 | Emulsifier"
            )
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=msg1), TextMessage(text=msg2)]
                )
            )

        # ২. Info বাটনের রেসপন্স
        elif text.lower() == "info":
            info_text = (
                "I was developed for people who can't read kanji but wish to look up the ingredients "
                "on any Japanese-language goods. I can read the text on an image and filter out any "
                "ingredients that are haram or syubhah.\n\n"
                "Please only use me as a helper and verification tool. To view the checked ingredients list, "
                "click 'Checked Ingredients'.\n\n"
                "How to use:\n"
                "1. Take or upload a clear picture of the product label (原材料名).\n"
                "2. Send it directly to Halal Check Japan."
            )
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=info_text)]
                )
            )

        # ৩. ভাষা সেট করার অপশন
        elif text.startswith("Set: "):
            chosen = text.replace("Set: ", "")
            if "日本語" in chosen:
                user_languages[user_id] = "Japanese"
                reply = "言語が「日本語」に設定されました。原材料名の写真を送信してください。"
            elif "English" in chosen:
                user_languages[user_id] = "English"
                reply = "Language set to English! Please send a clear picture of the ingredient label (原材料名)."
            elif "বাংলা" in chosen:
                user_languages[user_id] = "Bengali"
                reply = "ভাষা 'বাংলা' হিসেবে সেট করা হয়েছে! পণ্যের উপাদানের (原材料名) পরিষ্কার ছবি পাঠান।"
            elif "Español" in chosen:
                user_languages[user_id] = "Spanish"
                reply = "¡Idioma configurado en Español! Envíe una imagen clara de la lista de ingredientes (原材料名)."
            elif "中文" in chosen:
                user_languages[user_id] = "Simplified Chinese"
                reply = "语言已设置为中文！请发送配料表（原材料名）的清晰照片。"
            else:
                reply = "Please select a valid language."

            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply)]
                )
            )

        # ৪. সাধারণ টেক্সট মেসেজের জন্য ভাষা সিলেকশন
        else:
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(
                            text="Please select your language / ভাষা বেছে নিন / 言語を選択してください:",
                            quick_reply=get_language_selection_menu()
                        )
                    ]
                )
            )

@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event):
    user_id = event.source.user_id
    selected_lang = user_languages.get(user_id, "English")

    with ApiClient(configuration) as api_client:
        blob_api = MessagingApiBlob(api_client)
        image_bytes = blob_api.get_message_content(event.message.id)

    prompt = f"""
    You are an expert Islamic Halal Food Inspector in Japan.
    Inspect the provided food packaging image, focusing carefully on the Japanese ingredient list (原材料名).

    LIST OF HARAM INGREDIENTS:
    - Pork: 豚肉, ポーク, 豚脂, 豚脂肪, ラード, ハム, 豚エキス, 豚ゼラチン
    - Non-Halal Meat/Fat: 牛肉, 牛脂, 動物性油脂, 混合油脂, コンソメ, 鶏肉, チキン
    - Alcohol & Liquor: アルコール, 洋酒, 酒精, ラム, ワイン, ブランディ, ウィスキー, 酒, 料理酒, 清酒, 味醂, みりん
    - Gelatin: ゼラチン (unless 魚/植物性 origin is stated)

    LIST OF SYUBHAH (DOUBTFUL) INGREDIENTS:
    - 加工油脂 (Processed Fat)
    - 食用油脂 (Fat for cooking)
    - マーガリン (Margarine)
    - ショートニング (Shortening)
    - ファットスプレッド (Fatspread)
    - コラーゲン (Collagen)
    - 乳化剤 (Emulsifier)

    OUTPUT RULES:
    1. Respond entirely in {selected_lang}.
    2. Verdict headers:
       - [✅ HALAL / হালাল / ハラール] - If completely free from Haram and Syubhah ingredients.
       - [❌ HARAM / হারাম / ハラーム] - If any forbidden ingredient is found.
       - [⚠️ DOUBTFUL (SYUBHAH) / সন্দেহজনক / 疑わしい] - If any Syubhah ingredient is found without origin specified.
    3. Breakdown:
       Mention the detected Kanji/Japanese word, its meaning, and reason.
    4. Note on Syubhah:
       If Syubhah, advise clearly: "ইসলামে সন্দেহজনক বিষয় পরিহার করা সুন্নাহ। নিশ্চিত হওয়া ছাড়া এটি পরিহার করাই উত্তম।" (translated to {selected_lang}).
    """

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content([
            prompt,
            {"mime_type": "image/jpeg", "data": image_bytes}
        ])
        result_text = response.text.strip()
    except Exception as e:
        result_text = f"Sorry, error analyzing image: {str(e)}"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=result_text)]
            )
        )
