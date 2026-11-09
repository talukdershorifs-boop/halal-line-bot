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

# ব্যবহারকারীর পছন্দের ভাষা সংরক্ষণ
user_languages = {}

# বহুভাষিক টেক্সট এবং কার্ডের লেবেল ডিকশনারি
I18N = {
    "Bengali": {
        "status_halal": "✅ HALAL (হালাল)",
        "status_haram": "❌ HARAM (হারাম)",
        "status_syubhah": "⚠️ SYUBHAH (সন্দেহজনক)",
        "label_reason": "পর্যবেক্ষণ ও কারণ:",
        "label_items": "শনাক্তকৃত উপাদান (Detected Items):",
        "label_hadith_title": "📜 হাদিসের আলোকে সতর্কতা:",
        "hadith_text": "রাসূলুল্লাহ ﷺ বলেছেন: 'হালালও স্পষ্ট এবং হারামও স্পষ্ট। আর এ দুয়ের মাঝে রয়েছে বহু সন্দেহজনক বিষয়... যে ব্যক্তি সন্দেহজনক বিষয় থেকে নিজেকে বাঁচিয়ে রাখল, সে তার দ্বীন ও সম্মান রক্ষা করল।' [সহিহ বুখারি: ৫২, সহিহ মুসলিম: ১৫৯৯]",
        "label_advice_title": "💡 গুরুত্বপূর্ণ পরামর্শ:",
        "advice_text": "আমাদের এই বটটি একটি ফ্রি এআই টুল। খাদ্য নির্বাচনে ১০০% নির্ভুলতা ও শতভাগ নিরাপদ থাকার জন্য অফিশিয়ালি ভেরিফাইড পেইড অ্যাপ 'Halal Japan' ব্যবহার করার জন্য বিনীত অনুরোধ করা হচ্ছে।",
        "cam_btn": "📷 ক্যামেরা খুলুন",
        "cam_prompt": "নিচের '📷 ক্যামেরা খুলুন' বাটনে চাপ দিয়ে পণ্যের উপাদানের স্পষ্ট ছবি তুলুন:",
        "lang_confirm": "ভাষা 'বাংলা' সেট করা হয়েছে! পণ্যের উপাদানের স্পষ্ট ছবি পাঠান।",
        "default_prompt": "দয়া করে মেনু থেকে অপশন বেছে নিন অথবা পণ্যের উপাদানের (原材料名) স্পষ্ট ছবি পাঠান।",
        "haram_info": """🚫 নিশ্চিত হারাম উপাদানসমূহ:
• 豚肉、ポーク | শুকরের মাংস (Pork)
• 豚脂肪、豚脂 | শুকরের চর্বি (Pork Fat)
• ラード、ハム、ベーコン | লার্ড, হ্যাম, বেকন
• 豚エキス | শুকরের নির্যাস
• 豚ゼラチン | শুকরের জেলাটিন
• 牛肉、牛脂 | সাধারণ গরুর মাংস ও চর্বি
• 鶏肉、チキン | সাধারণ মুরগির মাংস
• 動物性油脂、混合油脂 | প্রাণিজ চর্বি / মিশ্র চর্বি
• コンソメ | কনসোমে স্যুপ ব্রোথ
• アルコール、洋酒、酒精 | অ্যালকোহল, মদ
• 酒、清酒、料理酒、味醂、みりん | জাপানি রান্নার মদ, মিরিন""",
        "syubhah_info": """⚠️ সন্দেহজনক উপাদানসমূহ (Syubhah):
• 乳化剤 (ইমালসিফায়ার) - সোর্স স্পষ্ট না হলে
• ショートニング (শর্টনিং) - বেকারি ফ্যাট
• マーガリン (মার্জারিন) - প্রাণিজ তেলের মিশ্রণ
• ファットスプレッド (ফ্যাটস্প্রেড)
• 加工油脂 (প্রক্রিয়াজাত চর্বি)
• コラーゲン / ゼラチン (জেলেটিন - মাছের না হলে)

📜 রাসূলুল্লাহ ﷺ বলেছেন: 'যে ব্যক্তি সন্দেহজনক বিষয় থেকে নিজেকে বাঁচিয়ে রাখল, সে তার দ্বীন রক্ষা করল।' [বুখারি: ৫২]""",
        "tips_info": """🛒 জাপানে কেনাকাটার টিপস:
১. প্যাকেটে '植物性' বা '植物油脂' (উদ্ভিজ্জ তেল) লেখা থাকলে তা নিরাপদ।
২. মিষ্টি, কেক ও আইসক্রিমে প্রায়ই '洋酒' (মদ) বা 'ゼラチン' থাকে, খেয়াল রাখুন।
৩. সন্দেহজনক খাবার এড়িয়ে চলা সুন্নাহর নির্দেশ।""",
        "general_info": "ℹ️ JP Halal Food Checker:\nজাপানি খাবারের উপাদানের তালিকা (原材料名) স্ক্যান করে হালাল যাচাই করুন। ১০০% নিশ্চিত তথ্যের জন্য 'Halal Japan' পেইড অ্যাপ ব্যবহার করুন।"
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
        "cam_prompt": "Tap the '📷 Open Camera' button below to take a clear picture of ingredients:",
        "lang_confirm": "Language set to English! Please send a clear ingredient picture.",
        "default_prompt": "Please select an option from the menu or send a photo of the ingredients list (原材料名).",
        "haram_info": """🚫 Confirmed Haram Ingredients:
• Pork, Pork Fat, Lard, Bacon, Ham (豚肉, 豚脂, ラード)
• General Beef, Chicken (non-halal slaughtered)
• Animal Fat, Mixed Fat (動物性油脂, 混合油脂)
• Consomme broth (コンソメ)
• Alcohol, Western Liquor, Ethyl Alcohol (アルコール, 洋酒, 酒精)
• Sake, Cooking Sake, Mirin (酒, 料理酒, 清酒, 味醂)""",
        "syubhah_info": """⚠️ Doubtful Ingredients (Syubhah):
• Emulsifier (乳化剤) - unless plant-derived
• Shortening (ショートニング) - bakery fat
• Margarine & Fat Spread (マーガリン, ファットスプレッド)
• Processed Fat (加工油脂)
• Gelatin / Collagen (ゼラチン) - unless fish-based

📜 Prophet ﷺ said: 'He who guards against doubtful matters clears himself regarding his religion.' [Bukhari: 52]""",
        "tips_info": """🛒 Japan Shopping Tips:
1. Look for '植物性' or '植物油脂' (plant-based oil) on bread and snacks.
2. Desserts and baked goods often contain '洋酒' (alcohol) or animal gelatin.
3. When in doubt, leaving it is a Sunnah.""",
        "general_info": "ℹ️ JP Halal Food Checker:\nScan the Japanese ingredient list (原材料名) to inspect Halal status. For 100% verified certainty, use the 'Halal Japan' paid app."
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
        "lang_confirm": "Bahasa diatur ke Bahasa Indonesia! Silakan kirim foto komposisi makanan.",
        "default_prompt": "Silakan pilih menu atau kirim foto daftar komposisi bahan (原材料名).",
        "haram_info": """🚫 Bahan Haram:
• Babi, Minyak Babi, Lard, Ham, Bacon (豚肉, 豚脂, ラード)
• Daging Sapi/Ayam non-halal (牛肉, 鶏肉)
• Lemak Hewani (動物性油脂, 混合油脂)
• Kaldu Consomme (コンソメ)
• Alkohol, Mirin, Sake, Shusei (アルコール, 洋酒, 酒精, みりん, 料理酒)""",
        "syubhah_info": """⚠️ Bahan Syubhat:
• Emulsifier (乳化剤) - jika sumbernya belum jelas
• Shortening & Margarin (ショートニング, マーガリン)
• Gelatin / Kolagen (ゼラチン) - jika bukan dari ikan

📜 Sabda Nabi ﷺ: 'Barangsiapa menjauhi perkara syubhat, berarti ia telah menyelamatkan agamanya.' [HR. Bukhari: 52]""",
        "tips_info": """🛒 Tips Belanja di Jepang:
1. Cari tulisan '植物性' atau '植物油脂' (nabati) pada roti dan biskuit.
2. Kue dan manisan sering menggunakan '洋酒' (minuman keras) atau gelatin hewani.
3. Menghindari makanan yang meragukan adalah sunnah.""",
        "general_info": "ℹ️ JP Halal Food Checker:\nScan daftar bahan (原材料名) untuk memeriksa kehalalan. Untuk kepastian 100%, gunakan aplikasi 'Halal Japan'."
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
        "lang_confirm": "言語を『日本語』に設定しました。原材料名の写真を送信してください。",
        "default_prompt": "メニューから選択するか、商品の原材料名（原材料表示）の写真を送信してください。",
        "haram_info": """🚫 ハラーム（禁止）成分:
• 豚肉、ポーク、豚脂、ラード、ハム、ベーコン、豚エキス
• 一般の牛肉・鶏肉（非ハラール屠殺）
• 動物性油脂、混合油脂
• コンソメ
• アルコール、洋酒、酒精、ラム、ブランデー
• 酒、清酒、料理酒、味醂、みりん""",
        "syubhah_info": """⚠️ シュブハ（疑わしい）成分:
• 乳化剤（植物性由来の明記がないもの）
• ショートニング、マーガリン、ファットスプレッド
• 加工油脂
• ゼラチン、コラーゲン（魚由来と明記がないもの）

📜 預言者 ﷺ:『疑わしきを避ける者は自らの信仰を守る』[ブハーリー: 52]""",
        "tips_info": """🛒 日本でのお買い物ヒント:
1. パンやお菓子は『植物性油脂』の表示を確認しましょう。
2. 洋菓子やデザートには『洋酒』や豚ゼラチンが使われることが多いです。
3. 疑わしいものは避けることが推奨されます。""",
        "general_info": "ℹ️ JP Halal Food Checker:\n商品の原材料表示をAIで分析します。100%確実な判定には有料アプリ『Halal Japan』のご利用を推奨します。"
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
        "lang_confirm": "تم ضبط اللغة إلى 'العربية'! يرجى إرسال صورة واضحة لقائمة المكونات.",
        "default_prompt": "يرجى الاختيار من القائمة أو إرسال صورة واضحة لقائمة المكونات (原材料名).",
        "haram_info": """🚫 المكونات المحرمة قطعيًا:
• لحم الخنزير، دهن الخنزير، لارد، شحم الخنزير (豚肉, 豚脂, ラード)
• اللحوم والدواجن غير المذكاة إسلاميًا (牛肉, 鶏肉)
• الدهون الحيوانية المختلطة (動物性油脂, 混合油脂)
• مرقة اللحم كونسوميه (コンソメ)
• الكحول، الخمور، الكحول الإيثيلي (アルコール, 洋酒, 酒精)
• نبيذ الطهي، الساكي، الميرين (酒, 料理酒, 清酒, 味醂)""",
        "syubhah_info": """⚠️ المكونات المشتبهة (شبهة):
• المستحلبات (乳化剤) - ما لم يُنص على أنها نباتية
• السمن النباتي/شورتنينج والمارجرين (ショートニング, マーガリン)
• الزيوت المعالجة (加工油脂)
• الجيلاتين والكولاجين (ゼラチン) - ما لم يُحدد أنه سمكي

📜 قال ﷺ: 'فمن اتقى الشبهات فقد استبرأ لدينه وعرضه' [البخاري: ٥٢]""",
        "tips_info": """🛒 نصائح التسوق في اليابان:
١. ابحث عن عبارة '植物性' أو '植物油脂' (نباتي) في المخبوزات.
٢. تحتوي الحلويات والآيس كريم كثيرًا على '洋酒' (خمور غربية) أو جيلاتين خنزيري.
٣. ترك الشبهات سلامة للدين.""",
        "general_info": "ℹ️ JP Halal Food Checker:\nفحص قائمة المكونات اليابانية (原材料名) للتأكد من حليتها. للتحقق النهائي بنسبة 100%، استخدم تطبيق 'Halal Japan' المعتمد."
    }
}

def get_direct_camera_quick_reply(lang="Bengali"):
    label = I18N.get(lang, I18N["Bengali"])["cam_btn"]
    return QuickReply(items=[
        QuickReplyItem(action=CameraAction(label=label))
    ])

def get_language_selection_menu():
    return QuickReply(items=[
        QuickReplyItem(action=MessageAction(label="🇧🇩 বাংলা", text="Set: Bengali")),
        QuickReplyItem(action=MessageAction(label="🇬🇧 English", text="Set: English")),
        QuickReplyItem(action=MessageAction(label="🇮🇩 Indonesia", text="Set: Indonesian")),
        QuickReplyItem(action=MessageAction(label="🇯🇵 日本語", text="Set: Japanese")),
        QuickReplyItem(action=MessageAction(label="🇸🇦 العربية", text="Set: Arabic")),
    ])

def create_halal_flex_card(status, reason, items_text, lang="Bengali"):
    """নির্বাচিত ভাষায় সম্পূর্ণ ডায়নামিক Flex Message কার্ড তৈরি করে"""
    lang_data = I18N.get(lang, I18N["Bengali"])
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
    return "JP Halal Food Checker Bot Running Multi-Language."

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
    
    # ব্যবহারকারী পূর্বে ভাষা সেট না করলে ডিফল্ট বাংলা
    current_lang = user_languages.get(user_id, "Bengali")

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # ভাষা পরিবর্তন সেটআপ লজিক
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
            reply = I18N[current_lang]["lang_confirm"]
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token, 
                    messages=[TextMessage(text=reply, quick_reply=get_direct_camera_quick_reply(current_lang))]
                )
            )
            return

        # রিচ মেনু ও বাটন অ্যাকশন
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
        elif "haram" in text or "হারাম" in text or "ハラーム" in text:
            reply = I18N[current_lang]["haram_info"]
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply)])
            )
        elif "syubhah" in text or "doubtful" in text or "সন্দেহ" in text or "シュブハ" in text or "شبهة" in text:
            reply = I18N[current_lang]["syubhah_info"]
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply)])
            )
        elif "tip" in text or "কেনাকাটা" in text or "tips" in text:
            reply = I18N[current_lang]["tips_info"]
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply)])
            )
        elif "info" in text or "guide" in text or "সাহায্য" in text or "bantuan" in text or "ガイド" in text:
            reply = I18N[current_lang]["general_info"]
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply)])
            )
        elif "language" in text or "ভাষা" in text or "bahasa" in text or "言語" in text or "لغة" in text:
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(
                            text="Select Language / Pilih Bahasa / ভাষা বেছে নিন / 言語を選択してください:",
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
                            text=I18N[current_lang]["default_prompt"],
                            quick_reply=get_language_selection_menu()
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
            "reason": "Clear explanation strictly in {selected_lang}",
            "items": "Detected specific Japanese ingredients with Kanji and translated explanation strictly in {selected_lang}"
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
        reply_payload = [TextMessage(text=f"Error analyzing image: {str(e)}")]

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=reply_payload
            )
        )
