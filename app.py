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

def get_direct_camera_quick_reply():
    return QuickReply(items=[
        QuickReplyItem(action=CameraAction(label="📷 ক্যামেরা খুলুন"))
    ])

def get_language_selection_menu():
    return QuickReply(items=[
        QuickReplyItem(action=MessageAction(label="🇧🇩 বাংলা", text="Set: Bengali")),
        QuickReplyItem(action=MessageAction(label="🇮🇩 Bahasa Indonesia", text="Set: Indonesian")),
        QuickReplyItem(action=MessageAction(label="🇬🇧 English", text="Set: English")),
        QuickReplyItem(action=MessageAction(label="🇯🇵 日本語", text="Set: Japanese")),
        QuickReplyItem(action=MessageAction(label="🇸🇦 العربية", text="Set: Arabic")),
    ])

def create_halal_flex_card(status, reason, items_text, lang_title):
    """স্ট্যাটাস অনুযায়ী কালারফুল Flex Message কার্ড জেনারেট করে (হাদিস রেফারেন্স ও Halal Japan রিকমেন্ডেশনসহ)"""
    status_upper = status.upper().strip()
    
    if "HALAL" in status_upper:
        header_color = "#107C41"  # হালাল ডিপ গ্রিন
        status_title = "✅ HALAL (হালাল)"
        badge_bg = "#E8F5E9"
        badge_color = "#1B5E20"
    elif "HARAM" in status_upper:
        header_color = "#D32F2F"  # হারাম রেড
        status_title = "❌ HARAM (হারাম)"
        badge_bg = "#FFEBEE"
        badge_color = "#B71C1C"
    else:
        header_color = "#E65100"  # সন্দেহজনক অ্যাম্বার
        status_title = "⚠️ SYUBHAH (সন্দেহজনক)"
        badge_bg = "#FFF3E0"
        badge_color = "#E65100"

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
                    "text": "JP HALAL FOOD CHECKER",
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
            "contents": [
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": badge_bg,
                    "cornerRadius": "8px",
                    "paddingAll": "12px",
                    "contents": [
                        {
                            "type": "text",
                            "text": "পর্যবেক্ষণ ও কারণ:",
                            "weight": "bold",
                            "size": "xs",
                            "color": badge_color
                        },
                        {
                            "type": "text",
                            "text": reason if reason else "উপাদান বিশ্লেষণ সম্পন্ন হয়েছে।",
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
                            "text": "শনাক্তকৃত উপাদান (Detected Items):",
                            "weight": "bold",
                            "size": "xs",
                            "color": "#666666"
                        },
                        {
                            "type": "text",
                            "text": items_text if items_text else "কোনো ক্ষতিকর উপাদান শনাক্ত হয়নি।",
                            "size": "sm",
                            "color": "#111111",
                            "wrap": True,
                            "margin": "xs"
                        }
                    ]
                },
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
                            "text": "📜 হাদিসের আলোকে সতর্কতা:",
                            "weight": "bold",
                            "size": "xxs",
                            "color": "#F57F17"
                        },
                        {
                            "type": "text",
                            "text": "রাসূলুল্লাহ ﷺ বলেছেন: 'হালালও স্পষ্ট এবং হারামও স্পষ্ট। আর এ দুয়ের মাঝে রয়েছে বহু সন্দেহজনক বিষয়... যে ব্যক্তি সন্দেহজনক বিষয় থেকে নিজেকে বাঁচিয়ে রাখল, সে তার দ্বীন ও সম্মান রক্ষা করল।' [সহিহ বুখারি: ৫২, সহিহ মুসলিম: ১৫৯৯]",
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
                            "text": "💡 গুরুত্বপূর্ণ পরামর্শ:",
                            "weight": "bold",
                            "size": "xxs",
                            "color": "#1A73E8"
                        },
                        {
                            "type": "text",
                            "text": "আমাদের এই বটটি একটি ফ্রি এআই টুল। খাদ্য নির্বাচনে ১০০% নির্ভুলতা ও শতভাগ নিরাপদ থাকার জন্য অফিশিয়ালি ভেরিফাইড পেইড অ্যাপ 'Halal Japan' ব্যবহার করার জন্য বিনীত অনুরোধ করা হচ্ছে।",
                            "size": "xxs",
                            "color": "#555555",
                            "wrap": True,
                            "margin": "xs"
                        }
                    ]
                }
            ]
        }
    }
    return FlexContainer.from_json(json.dumps(flex_json))

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

• 乳化剤 (ইমালসিফায়ার) - উদ্ভিদ না প্রাণিজ স্পষ্ট না হলে।
• ショートニング (শর্টনিং) - বেকারি আইটেমে প্রাণিজ ফ্যাট থাকতে পারে।
• マーガリン (মার্জারিন) - প্রাণিজ তেলের মিশ্রণ থাকতে পারে।
• ファットスプレッド (ফ্যাটস্প্রেড) - মিশ্র চর্বি।
• 加工油脂 (প্রক্রিয়াজাত চর্বি) - সোর্স অনির্দিষ্ট থাকলে।
• コラーゲン / ゼラチン - মাছের নিশ্চিত উল্লেখ না থাকলে।

📜 রাসূলুল্লাহ ﷺ বলেছেন: 'যে ব্যক্তি সন্দেহজনক বিষয় থেকে নিজেকে বাঁচিয়ে রাখল, সে তার দ্বীন ও সম্মান রক্ষা করল।' [সহিহ বুখারি: ৫২]""",

        "tips": """🛒 জাপানে কেনাকাটার টিপস ও সুন্নত আমল:

১. পাউরুটি বা বিস্কুটে '植物性' বা '植物油脂' লেখা আছে কি না লক্ষ্য করুন।
২. সাধারণ সুপারমার্কেট থেকে মাংস বা সসেজ কেনা পরিহার করুন, হালাল দোকান থেকে কিনুন।
৩. মিষ্টি ও কেক-পেস্ট্রিতে প্রায়শই '洋酒' (মদ) থাকে, তাই উপাদান দেখে নিন।
৪. খাবারে সামান্যতম সন্দেহ থাকলে তা পরিহার করাই সুন্নাহর নির্দেশ।""",

        "info": """ℹ️ JP Halal Food Checker:

জাপানি খাদ্যপণ্যের উপাদানের তালিকা (原材料名) এআই স্বয়ংক্রিয়ভাবে পড়ে যাচাই করে।

📷 ছবি তোলার নিয়ম:
• বারকোড নয়, উপাদানের তালিকার (原材料名) সোজা ও স্পষ্ট ছবি তুলুন।

💡 নির্ভরযোগ্য তথ্যের জন্য আমরা 'Halal Japan' পেইড অ্যাপ ব্যবহারের পরামর্শ দিই।""",

        "lang_confirm": "ভাষা 'বাংলা' সেট করা হয়েছে! পণ্যের উপাদানের স্পষ্ট ছবি পাঠান।"
    },
    "English": {
        "haram": "🚫 Pork, Alcohol, Animal Fat, Mirin, Gelatin (non-fish), Sake are Haram.",
        "syubhah": "⚠️ Emulsifier, Shortening, Margarine, Processed Fat can be Syubhah.\n\nHadith: 'He who avoids doubtful matters clears himself in regard to his religion and his honor.' [Sahih al-Bukhari: 52]",
        "tips": "🛒 Check for 植物性 (plant-based) and avoid doubtful meat products.",
        "info": "ℹ️ Send a photo of the ingredient list (原材料名). For guaranteed safety, consider using the verified 'Halal Japan' paid app.",
        "lang_confirm": "Language set to English! Please send a clear ingredient picture."
    }
}

@app.route("/", methods=['GET'])
def index():
    return "JP Halal Food Checker Bot Running."

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
    global user_languages
    user_id = event.source.user_id
    raw_text = event.message.text.strip()
    text = raw_text.lower()
    current_lang = user_languages.get(user_id, "Bengali")

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        if raw_text.startswith("Set:"):
            target = raw_text.replace("Set:", "").strip().lower()
            if "english" in target:
                user_languages[user_id] = "English"
            else:
                user_languages[user_id] = "Bengali"

            reply = CHECKED_DATA[user_languages[user_id]]["lang_confirm"]
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply)])
            )
            return

        if any(k in text for k in ["take a photo", "camera", "ক্যামেরা", "scan", "ছবি"]):
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(
                            text="নিচের '📷 ক্যামেরা খুলুন' বাটনে চাপ দিয়ে পণ্যের উপাদানের স্পষ্ট ছবি তুলুন:",
                            quick_reply=get_direct_camera_quick_reply()
                        )
                    ]
                )
            )
        elif "haram" in text:
            reply = CHECKED_DATA.get(current_lang, CHECKED_DATA["Bengali"])["haram"]
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply)])
            )
        elif "syubhah" in text or "doubtful" in text or "সন্দেহ" in text:
            reply = CHECKED_DATA.get(current_lang, CHECKED_DATA["Bengali"])["syubhah"]
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply)])
            )
        elif "tip" in text or "কেনাকাটা" in text:
            reply = CHECKED_DATA.get(current_lang, CHECKED_DATA["Bengali"])["tips"]
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply)])
            )
        elif "info" in text or "guide" in text or "সাহায্য" in text:
            reply = CHECKED_DATA.get(current_lang, CHECKED_DATA["Bengali"])["info"]
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply)])
            )
        elif "language" in text or "ভাষা" in text:
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(
                            text="Select Language / ভাষা বেছে নিন:",
                            quick_reply=get_language_selection_menu()
                        )
                    ]
                )
            )
        else:
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(
                            text="দয়া করে মেনু থেকে অপশন বেছে নিন অথবা পণ্যের উপাদানের (原材料名) স্পষ্ট ছবি পাঠান।"
                        )
                    ]
                )
            )

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
            "maxOutputTokens": 400,
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
    global user_languages
    user_id = event.source.user_id
    selected_lang = user_languages.get(user_id, "Bengali")

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

        prompt = f"""
        Act as Halal Food Inspector Japan.
        Inspect the Japanese ingredients list (原材料名).
        Haram components: 豚肉, ポーク, 豚脂, 豚脂肪, ラード, ハム, ベーコン, 豚エキス, 豚ゼラチン, 牛肉, 牛脂, 動物性油脂, 混合油脂, コンソメ, 鶏肉, チキン, アルコール, 洋酒, 酒精, ラム, ワイン, ブランディ, ウィスキー, 酒, 料理酒, 清酒, 味醂, みりん, ゼラチン.
        Syubhah components: 加工油脂, 食用油脂, マーガリン, ショートニング, ファットスプレッド, コラーゲン, 乳化剤.

        You MUST respond ONLY with a valid JSON matching this schema:
        {{
            "status": "HALAL" or "HARAM" or "SYUBHAH",
            "reason": "Brief explanation in {selected_lang}",
            "items": "Detected specific Japanese ingredients with Kanji and translated explanation in {selected_lang} (or 'কোনো ক্ষতিকর উপাদান নেই')"
        }}
        """

        result_raw = call_gemini_vision(prompt, image_b64)
        result_json = json.loads(result_raw)

        status = result_json.get("status", "SYUBHAH")
        reason = result_json.get("reason", "")
        items = result_json.get("items", "")

        flex_container = create_halal_flex_card(status, reason, items, selected_lang)
        reply_payload = [FlexMessage(alt_text=f"Check Result: {status}", contents=flex_container)]

    except Exception as e:
        reply_payload = [TextMessage(text=f"ছবি বিশ্লেষণে সাময়িক সমস্যা হয়েছে: {str(e)}")]

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=reply_payload
            )
        )
