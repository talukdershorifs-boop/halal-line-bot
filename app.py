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
    MessageAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, ImageMessageContent

app = Flask(__name__)

CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

user_languages = {}

def get_language_selection_menu():
    items = [
        QuickReplyItem(action=MessageAction(label="🇧🇩 বাংলা", text="Set: বাংলা")),
        QuickReplyItem(action=MessageAction(label="🇬🇧 English", text="Set: English")),
        QuickReplyItem(action=MessageAction(label="🇯🇵 日本語", text="Set: 日本語")),
        QuickReplyItem(action=MessageAction(label="🇸🇦 العربية", text="Set: العربية")),
    ]
    return QuickReply(items=items)

# বহুভাষিক ডাটাবেজ
CHECKED_DATA = {
    "Bengali": {
        "haram": (
            "🚫 হারাম উপাদানসমূহ (Strictly Haram):\n\n"
            "🐖 শুকর ও শুকরজাত উপাদান:\n"
            "豚肉、ポーク | শুকরের মাংস (Pork)\n"
            "豚脂肪、豚脂 | শুকরের চর্বি (Pork Fat)\n"
            "ラード、ハム、ベーコン | লার্ড, হ্যাম, বেকন\n"
            "豚エキス | শুকরের নির্যাস (Pork Extract)\n"
            "豚ゼラチン | শুকরের জেলাটিন\n\n"
            "🥩 অ-হালাল মাংস ও প্রাণিজ চর্বি:\n"
            "牛肉、牛脂 | সাধারণ গরুর মাংস, চর্বি (Tallow)\n"
            "鶏肉、チキン | অ-হালাল মুরগির মাংস\n"
            "動物性油脂、混合油脂 | প্রাণিজ চর্বি / মিশ্র চর্বি\n"
            "コンソメ | কনসোমে স্যুপ ব্রোথ\n\n"
            "🍷 অ্যালকোহল ও মদজাতীয় উপাদান:\n"
            "アルコール、洋酒 | অ্যালকোহল, পশ্চিমা মদ\n"
            "酒、清酒、料理酒 | জাপানি সাকে মদ, রান্নার মদ\n"
            "味醂、みりん | মিরিন কুকিং অ্যালকোহল\n"
            "酒精 | ইথাইল অ্যালকোহল\n"
            "ラム、ワイン、ブランディ | রাম, ওয়াইন, ব্র্যান্ডি"
        ),
        "syubhah": (
            "⚠️ সন্দেহজনক উপাদানসমূহ (Syubhah):\n\n"
            "乳化剤 (ইমালসিফায়ার) - উদ্ভিদ নাকি প্রাণিজ স্পষ্ট না হলে সন্দেহজনক।\n"
            "ショートニング (শর্টনিং) - অনেক বেকারি আইটেমে শুকর বা গরুর ফ্যাট থাকতে পারে।\n"
            "マーガリン (মার্জারিন) - প্রাণিজ তেলের সংমিশ্রণ থাকতে পারে।\n"
            "ファットスプレッド (ফ্যাটস্প্রেড) - মিশ্র চর্বি।\n"
            "加工油脂 (প্রক্রিয়াজাত চর্বি) - সোর্স অনির্দিষ্ট থাকলে।\n"
            "コラーゲン (কোলাজেন) - মাছের না হলে প্রাণিজ উৎস।\n"
            "ゼラチン (সাধারণ জেলাটিন) - মাছের উল্লেখ না থাকলে এড়িয়ে চলুন।\n\n"
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
        "lang_confirm": "ভাষা 'বাংলা' হিসেবে সেট করা হয়েছে! পণ্যের উপাদানের স্পষ্ট ছবি পাঠান।"
    },
    "English": {
        "haram": (
            "🚫 Strictly Haram Ingredients:\n\n"
            "🐖 Pork & Swine Products:\n"
            "豚肉、ポーク | Pork\n"
            "豚脂肪、豚脂 | Pork Fat\n"
            "ラード、ハム、ベーコン | Lard, Ham, Bacon\n"
            "豚エキス | Pork Extract\n"
            "豚ゼラチン | Pork Gelatin\n\n"
            "🥩 Non-Halal Meat & Animal Fat:\n"
            "牛肉、牛脂 | Non-halal Beef, Tallow\n"
            "鶏肉、チキン | Non-halal Chicken\n"
            "動物性油脂、混合油脂 | Animal Fat, Mixed Fat\n"
            "コンソメ | Consomme Soup Stock\n\n"
            "🍷 Alcohol & Intoxicants:\n"
            "アルコール、洋酒 | Alcohol, Western Liquor\n"
            "酒、清酒、料理酒 | Japanese Sake, Cooking Rice Wine\n"
            "味醂、みりん | Mirin (Cooking Alcohol)\n"
            "酒精 | Ethyl Alcohol\n"
            "ラム、ワイン、ブランディ | Rum, Wine, Brandy"
        ),
        "syubhah": (
            "⚠️ Syubhah (Doubtful) Ingredients:\n\n"
            "乳化剤 (Emulsifier) - Syubhah unless plant-based (植物性).\n"
            "ショートニング (Shortening) - May contain animal fats.\n"
            "マーガリン (Margarine) - May contain animal oils.\n"
            "ファットスプレッド (Fatspread) - Processed blend.\n"
            "加工油脂 (Processed Fat) - Unknown fat sources.\n"
            "コラーゲン (Collagen) - Syubhah unless fish origin.\n"
            "ゼラチン (Gelatine) - Avoid unless marked 魚由来 (fish).\n\n"
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
        "lang_confirm": "Language set to English! Please send a clear picture of the ingredient label."
    },
    "Japanese": {
        "haram": (
            "🚫 ハラーム原材料 (Strictly Haram):\n\n"
            "豚肉、ポーク | 豚肉\n"
            "豚脂肪、豚脂 | 豚脂、ラード\n"
            "ラード、ハム、ベーコン | ラード、ハム、ベーコン\n"
            "豚エキス | ポークエキス\n"
            "豚ゼラチン | 豚ゼラチン\n"
            "牛肉、牛脂 | 非ハラール牛肉、牛脂\n"
            "鶏肉、チキン | 非ハラール鶏肉\n"
            "動物性油脂、混合油脂 | 動物性・混合油脂\n"
            "コンソメ | 肉エキス入りコンソメ\n"
            "アルコール、洋酒 | アルコール、洋酒全般\n"
            "酒、清酒、料理酒 | 酒、料理酒\n"
            "味醂、みりん | みりん\n"
            "酒精 | 酒精\n"
            "ラム、ワイン | ラム酒、ワイン"
        ),
        "syubhah": (
            "⚠️ 疑わしい原材料 (Syubhah):\n\n"
            "乳化剤 - 植物性か動物性か不明な場合。\n"
            "ショートニング - 動物性油脂混入の可能性あり。\n"
            "マーガリン - 動物性由来の可能性あり。\n"
            "ファットスプレッド - 加工油脂。\n"
            "加工油脂 - 出所不明な油脂。\n"
            "コラーゲン / ゼラチン - 魚由来の明記がないもの。"
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
        "lang_confirm": "言語が「日本語」に設定されました。原材料名の写真を送信してください。"
    },
    "Arabic": {
        "haram": (
            "🚫 المكونات المحرمة قطعيًا (Haram):\n\n"
            "豚肉、ポーク | لحم الخنزير\n"
            "豚脂肪、豚脂、ラード | دهن وشحم الخنزير\n"
            "ハム、ベーコン | لحم خنزير مقدد\n"
            "豚エキス | خلاصة الخنزير\n"
            "牛肉、牛脂 | لحم وشحم بقر غير مذبوح إسلاميًا\n"
            "鶏肉、チキン | لحم دجاج غير حلال\n"
            "動物性油脂 | دهون حيوانية\n"
            "コンソメ | مرقة لحم غير حلال\n"
            "アルコール、洋酒 | كحول وخمور غربية\n"
            "酒、清酒、料理酒 | ساكي ونبيذ طبخ ياباني\n"
            "味醂、みりん | ميرين (كحول طبخ)\n"
            "酒精 | كحول إيثيلي"
        ),
        "syubhah": (
            "⚠️ المكونات المشتبه فيها (الشبهات):\n\n"
            "乳化剤 (مستحلب) - مشتبه إلا إذا ذكر أنه نباتي (植物性).\n"
            "ショートニング (شورتنينج) - قد يحتوي دهون حيوانية.\n"
            "マーガリン (مارجرين) - قد يحتوي زيوتاً حيوانية.\n"
            "加工油脂 (دهون معالجة) - مصدرها مجهول.\n"
            "ゼラチン (جيلاتين) - مشتبه إلا إذا ذكر أنه سمكي (魚由来)."
        ),
        "tips": (
            "🛒 نصائح التسوق الحلال في اليابان:\n\n"
            "1. عند شراء الخبز، تأكد من وجود كلمة 植物性 (مصدر نباتي).\n"
            "2. الحلويات والكعك تحتوي غالبًا على 洋酒 (خمور غربية) أو ميرين للنكهة.\n"
            "3. اللحوم والدواجن الطازجة في السوبرماركت العادي ليست حلالاً، يرجى الشراء من المتاجر الإسلامية المعتمدة."
        ),
        "info": (
            "ℹ️ عن Halal Check Japan:\n\n"
            "بوت ذكي لقراءة قائمة المكونات (原材料名) على الأطعمة اليابانية وتحديد الحلال والحرام والشبهات.\n\n"
            "📷 طريقة التصوير:\n"
            "• صور قائمة المكونات بوضوح وإضاءة جيدة وليس الباركود."
        ),
        "lang_confirm": "تم ضبط اللغة إلى العربية! الرجاء إرسال صورة واضحة لقائمة المكونات."
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
    text = event.message.text.strip().lower()
    current_lang = user_languages.get(user_id, "Bengali")

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        if text in ["checked haram", "haram list", "হারাম তালিকা"]:
            reply = CHECKED_DATA[current_lang]["haram"]
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply)]
                )
            )
        elif text in ["checked syubhah", "syubhah list", "সন্দেহজনক"]:
            reply = CHECKED_DATA[current_lang]["syubhah"]
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply)]
                )
            )
        elif text in ["shopping tips", "tips", "টিপস"]:
            reply = CHECKED_DATA[current_lang]["tips"]
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply)]
                )
            )
        elif text in ["info", "about", "সাহায্য"]:
            reply = CHECKED_DATA[current_lang]["info"]
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply)]
                )
            )
        elif text in ["change language", "language", "ভাষা"]:
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
        elif event.message.text.startswith("Set: "):
            chosen = event.message.text.replace("Set: ", "").strip()
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
                            text="নিচের মেনু থেকে অপশন বেছে নিন অথবা পণ্যের উপাদানের (原材料名) ছবি পাঠান।",
                            quick_reply=get_language_selection_menu()
                        )
                    ]
                )
            )

def get_active_model_endpoint():
    try:
        list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
        resp = requests.get(list_url, timeout=10)
        if resp.status_code == 200:
            models_data = resp.json().get("models", [])
            for m in models_data:
                name = m.get("name", "")
                methods = m.get("supportedGenerationMethods", [])
                if "generateContent" in methods and "flash" in name.lower():
                    return name
    except Exception:
        pass
    return "models/gemini-3.8-flash"

def call_gemini_vision(prompt, image_b64):
    active_model = get_active_model_endpoint()
    if not active_model.startswith("models/"):
        active_model = f"models/{active_model}"
        
    url = f"https://generativelanguage.googleapis.com/v1beta/{active_model}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}}
            ]
        }],
        "generationConfig": {"temperature": 0.2}
    }
    res = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=45)
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

        img = Image.open(io.BytesIO(raw_bytes))
        img.thumbnail((900, 900))
        out_buf = io.BytesIO()
        img.convert('RGB').save(out_buf, format="JPEG", quality=75, optimize=True)
        image_b64 = base64.b64encode(out_buf.getvalue()).decode("utf-8")

        del raw_bytes, img, out_buf
        gc.collect()

        prompt = f"""
        You are an expert Islamic Halal Food Inspector in Japan.
        Inspect the Japanese food ingredient label (原材料名) shown in the image.

        HARAM INGREDIENTS:
        - Pork / Swine: 豚肉, ポーク, 豚脂, 豚脂肪, ラード, ハム, ベーコン, 豚エキス, 豚ゼラチン
        - Animal Meat/Fats: 牛肉, 牛脂, 動物性油脂, 混合油脂, コンソメ, 鶏肉, チキン
        - Alcohol & Intoxicants: アルコール, 洋酒, 酒精, ラム, ワイン, ブランディ, ウィスキー, 酒, 料理酒, 清酒, 味醂, みりん
        - Gelatin: ゼラチン (unless specified as fish/plant)

        SYUBHAH INGREDIENTS:
        - 加工油脂, 食用油脂, マーガリン, ショートニング, ファットスプレッド, コラーゲン, 乳化剤

        OUTPUT RULES:
        1. Write the evaluation in {selected_lang}.
        2. Verdict header: [✅ হালাল / HALAL] or [❌ হারাম / HARAM] or [⚠️ সন্দেহজনক / SYUBHAH]
        3. Breakdown: Kanji keyword, meaning, and reason.
        4. If Syubhah: Advise that avoiding doubtful matters is Sunnah.
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
