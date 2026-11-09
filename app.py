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

# ব্যবহারকারীর ডেটা সংরক্ষণ
user_languages = {}
user_countries = {}

# বহুভাষিক টেক্সট এবং কার্ড কনফিগারেশন
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
        "advice_text": "আমাদের এই বটটি একটি ফ্রি এআই টুল। খাদ্য নির্বাচনে ১০০% নির্ভুলতা ও শতভাগ নিরাপদ থাকার জন্য অফিশিয়ালি ভেরিফাইড পেইড অ্যাপ 'Halal Japan' ব্যবহার করার জন্য বিনীত অনুরোধ করা হচ্ছে।",
        "cam_btn": "📷 ক্যামেরা খুলুন",
        "cam_prompt": "নিচের '📷 ক্যামেরা খুলুন' বাটনে চাপ দিয়ে পণ্যের উপাদানের স্পষ্ট ছবি তুলুন:",
        "lang_confirm": "ভাষা 'বাংলা' সেট করা হয়েছে!",
        "country_confirm": "নির্বাচিত দেশ: {country}। এখন এই দেশের খাদ্যতালিকা অনুযায়ী স্ক্যান করা হবে।",
        "default_prompt": "মেনু থেকে অপশন বেছে নিন অথবা পণ্যের উপাদানের স্পষ্ট ছবি পাঠান।",
        "select_country_prompt": "ভ্রমণ বা অবস্থানের দেশ নির্বাচন করুন / Select Country:"
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
        "advice_text": "This bot is a free AI tool. For 100% verified accuracy and safety, we kindly advise using the officially verified paid app 'Halal Japan'.",
        "cam_btn": "📷 Open Camera",
        "cam_prompt": "Tap '📷 Open Camera' below to take a clear picture of the ingredient list:",
        "lang_confirm": "Language set to English!",
        "country_confirm": "Target country set to: {country}. Food analysis will follow this region's standards.",
        "default_prompt": "Please choose from the menu or send a photo of the ingredients list.",
        "select_country_prompt": "Select your country / দেশ বেছে নিন:"
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
        "advice_text": "Bot ini adalah alat AI gratis. Untuk keakuratan dan keamanan terverifikasi 100%, disarankan menggunakan aplikasi berbayar resmi 'Halal Japan'.",
        "cam_btn": "📷 Buka Kamera",
        "cam_prompt": "Tekan tombol '📷 Buka Kamera' di bawah untuk mengambil foto komposisi:",
        "lang_confirm": "Bahasa diatur ke Bahasa Indonesia!",
        "country_confirm": "Negara dipilih: {country}. Pemeriksaan makanan akan disesuaikan dengan negara ini.",
        "default_prompt": "Silakan pilih menu atau kirim foto daftar komposisi bahan.",
        "select_country_prompt": "Pilih Negara:"
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
        "advice_text": "当ボットは無料のAIツールです。100%安全かつ確実な情報をお求めの場合は、公式認証アプリ『Halal Japan』(有料)のご利用を強くお勧めいたします。",
        "cam_btn": "📷 カメラを起動",
        "cam_prompt": "下の『📷 カメラを起動』ボタンを押して原材料名の写真を撮影してください:",
        "lang_confirm": "言語を『日本語』に設定しました。",
        "country_confirm": "対象国を【{country}】に設定しました。この国の基準に基づいて判定します。",
        "default_prompt": "メニューから選択するか、商品の原材料名（原材料表示）の写真を送信してください。",
        "select_country_prompt": "対象国を選択してください:"
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
        "advice_text": "هذا البوت أداة ذكاء اصطناعي مجانية. للحصول على أقصى درجات الدقة والتحقق الموثوق بنسبة 100%، نوصي باستخدام التطبيق المدفوع المعتمد 'Halal Japan'.",
        "cam_btn": "📷 فتح الكاميرا",
        "cam_prompt": "اضغط على زر '📷 فتح الكاميرا' بالأسفل لتصوير قائمة المكونات بوضوح:",
        "lang_confirm": "تم ضبط اللغة إلى 'العربية'!",
        "country_confirm": "الدولة المحددة: {country}. سيتم فحص الأطعمة وفق معايير هذا البلد.",
        "default_prompt": "يرجى الاختيار من القائمة أو إرسال صورة واضحة لقائمة المكونات.",
        "select_country_prompt": "اختر الدولة المراد فحص أطعمتها:"
    }
}

# দেশ অনুযায়ী হারাম ও সন্দেহজনক উপাদানের ডাটাবেস
COUNTRY_RULES = {
    "Japan": {
        "title": "JP HALAL FOOD CHECKER 🇯🇵",
        "label_name": "原材料名 (Raw Materials)",
        "haram_prompt": """
        TARGET REGION: JAPAN.
        Target label header to locate: 原材料名.
        Confirmed HARAM ingredients in Japan:
        - Pork derivatives: 豚肉, ポーク, 豚脂, 豚脂肪, ラード (lard), ハム (ham), ベーコン (bacon), 豚エキス, 豚ゼラチン, ポークエキス, ポークパウダー, 豚血.
        - Non-halal meat & general broths: 牛肉, 牛脂, 鶏肉, チキン, チキンエキス, チキンパウダー, ビーフエキス, 肉エキス, コンソメ, ブイヨン.
        - Animal/mixed fats: 動物性油脂, 混合油脂, ヘット.
        - Alcohol & cooking wine: アルコール, 洋酒, 酒精, ラム, ワイン, ブランディ, ウィスキー, リキュール, 酒, 料理酒, 清酒, 醸造調味料 (if alcoholic), 味醂, みりん, 発酵調味料 (with alcohol).
        - Non-fish Gelatin: ゼラチン, 豚コラーゲン.
        SYUBHAH ingredients in Japan:
        - 加工油脂, 食用油脂, 植物油脂 (usually ok, verify if mixed), マーガリン, ショートニング, ファットスプレッド, 乳化剤 (emulsifier), コラーゲン.
        """
    },
    "China": {
        "title": "CN HALAL FOOD CHECKER 🇨🇳",
        "label_name": "配料 / 配料表 (Ingredients)",
        "haram_prompt": """
        TARGET REGION: MAINLAND CHINA & CHINESE PACKAGED FOODS.
        Target label header to locate: 配料 or 配料表.
        Confirmed HARAM ingredients in China:
        - Pork derivatives: 猪肉, 猪油, 猪脂, 猪皮, 猪血 (blood curd), 猪肉浸膏, 猪肉粉, 培根 (bacon), 火腿 (ham), 猪骨汤, 猪肉精.
        - Non-halal meats & meat broths: 牛肉, 鸡肉, 鸭肉, 鹅肉, 动物油脂, 混合油, 鸡精, 鸡汁, 鸡粉, 浓汤宝, 牛肉膏.
        - Chinese cooking wine & alcohol: 料酒, 黄酒, 白酒, 花雕酒, 米酒, 烹调酒, 食用酒精, 朗姆酒, 红酒, 葡萄酒, 啤酒, 乙醇. (Pay critical attention: Chinese savory dishes, seasonings, and packaged noodles frequently contain 料酒 or 黄酒).
        - Blood products: 血旺, 鸭血, 猪血.
        - Non-halal gelatin: 明胶, 动物明胶, 猪皮明胶, 阿胶 (donkey gelatin).
        SYUBHAH ingredients in China:
        - 起酥油 (shortening), 人造奶油, 人造黄油, 动植物微球油脂, 单双甘油脂肪酸酯, 乳化剂 (emulsifier), 食用香精 (flavoring - check if alcohol solvent), 骨胶原.
        """
    }
}

def get_country_selection_menu():
    return QuickReply(items=[
        QuickReplyItem(action=MessageAction(label="🇯🇵 Japan (日本)", text="Country: Japan")),
        QuickReplyItem(action=MessageAction(label="🇨🇳 China (中国)", text="Country: China"))
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

def create_halal_flex_card(status, reason, items_text, lang="Bengali", country="Japan"):
    lang_data = I18N.get(lang, I18N["Bengali"])
    country_header = COUNTRY_RULES.get(country, COUNTRY_RULES["Japan"])["title"]
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
                            "text": lang_data["advice_text"],
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

@app.route("/", methods=['GET'])
def index():
    return "JP/CN Multi-Country Halal Food Checker Running."

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
    global user_languages, user_countries
    user_id = event.source.user_id
    raw_text = event.message.text.strip()
    text = raw_text.lower()

    current_lang = user_languages.get(user_id, "Bengali")
    current_country = user_countries.get(user_id, "Japan")

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # দেশ নির্বাচন প্রক্রিয়া
        if raw_text.startswith("Country:"):
            chosen = raw_text.replace("Country:", "").strip()
            if "china" in chosen.lower():
                user_countries[user_id] = "China"
            else:
                user_countries[user_id] = "Japan"

            current_country = user_countries[user_id]
            msg = I18N[current_lang]["country_confirm"].format(country=current_country)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=msg, quick_reply=get_direct_camera_quick_reply(current_lang))]
                )
            )
            return

        # ভাষা পরিবর্তন প্রক্রিয়া
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
            msg = I18N[current_lang]["lang_confirm"]
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=msg, quick_reply=get_direct_camera_quick_reply(current_lang))]
                )
            )
            return

        # কমান্ড ও মেনু অ্যাকশন
        if any(k in text for k in ["country", "দেশ", "negara", "国", "بلد"]):
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(
                            text=I18N[current_lang]["select_country_prompt"],
                            quick_reply=get_country_selection_menu()
                        )
                    ]
                )
            )
        elif any(k in text for k in ["take a photo", "camera", "ক্যামেরা", "scan", "ছবি", "kamera", "カメラ"]):
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
        elif any(k in text for k in ["language", "ভাষা", "bahasa", "言語", "لغة"]):
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(
                            text="Select Language / ভাষা বেছে নিন / Pilih Bahasa / 言語選択:",
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
                            text=f"📍 Current Country: {current_country}\n" + I18N[current_lang]["default_prompt"],
                            quick_reply=get_country_selection_menu()
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
            "maxOutputTokens": 500,
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
    global user_languages, user_countries
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
        Act as Halal Food Inspector specialized in East Asian packaged products.
        Selected Country to inspect: {selected_country}
        
        {country_context}

        Your task:
        1. Find the ingredient list on the packaging based on the country's label standard.
        2. Detect all Haram, Syubhah, and Halal ingredients accurately.
        3. Determine the final verdict: 'HALAL', 'HARAM', or 'SYUBHAH'.

        You MUST respond ONLY with a valid JSON matching this schema:
        {{
            "status": "HALAL" or "HARAM" or "SYUBHAH",
            "reason": "Clear explanation strictly in {selected_lang}",
            "items": "Detected specific ingredients with original Kanji/Hanzi and clear explanation strictly in {selected_lang}"
        }}
        """

        result_raw = call_gemini_vision(prompt, image_b64)
        result_json = json.loads(result_raw)

        status = result_json.get("status", "SYUBHAH")
        reason = result_json.get("reason", "")
        items = result_json.get("items", "")

        flex_container = create_halal_flex_card(status, reason, items, selected_lang, selected_country)
        reply_payload = [FlexMessage(alt_text=f"Check Result: {status}", contents=flex_container)]

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
