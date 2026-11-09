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

# দেশভিত্তিক নিয়ম ও অনুমোদিত বিশ্বস্ত অ্যাপের তালিকা
COUNTRY_RULES = {
    "Japan": {
        "title": "JP HALAL FOOD CHECKER 🇯🇵",
        "app_name": "'Halal Japan'",
        "advice": {
            "Bengali": "আমাদের এই বটটি একটি ফ্রি এআই টুল। খাদ্য নির্বাচনে ১০০% নির্ভুলতা ও শতভাগ নিরাপদ থাকার জন্য অফিশিয়ালি ভেরিফাইড পেইড অ্যাপ 'Halal Japan' ব্যবহার করার জন্য বিনীত অনুরোধ করা হচ্ছে।",
            "English": "This bot is a free AI tool. For 100% verified accuracy and safety in Japan, we kindly advise using the officially verified paid app 'Halal Japan'.",
            "Indonesian": "Bot ini adalah alat AI gratis. Untuk keakuratan 100% dan keamanan terverifikasi di Jepang, disarankan menggunakan aplikasi resmi berbayar 'Halal Japan'.",
            "Japanese": "当ボットは無料のAIツールです。日本国内での100%確実な判定をお求めの場合は、公式認証アプリ『Halal Japan』(有料)のご利用を推奨します。",
            "Arabic": "هذا البوت أداة مجانية. للتحقق الموثوق بنسبة 100% في اليابان، نوصي بشدة باستخدام التطبيق المدفوع المعتمد 'Halal Japan'."
        },
        "haram_prompt": """
        TARGET REGION: JAPAN.
        Header: 原材料名.
        - HARAM: 豚肉, 豚脂, ラード, 豚骨, ポークエキス, 豚ゼラチン, ハム, ベーコン, 牛肉/鶏肉 (unless Halal marked), 動物性油脂, 混合油脂, コンソメ, アルコール, 洋酒, 酒精, 酒, 料理酒, 清酒, 味醂 (みりん), 発酵調味料 (with alcohol).
        - SYUBHAH: ショートニング, マーガリン, ファットスプレッド, 乳化剤 (E471/E472), 加工油脂, コラーゲン, ゼラチン (unless fish origin).
        """
    },
    "China": {
        "title": "CN HALAL FOOD CHECKER 🇨🇳",
        "app_name": "Official Chinese Halal Certification Authorities (伊协清真认证)",
        "advice": {
            "Bengali": "আমাদের এই বটটি একটি ফ্রি এআই টুল। চীনে খাদ্যদ্রব্যের ক্ষেত্রে ১০০% নিশ্চয়তা ও নিরাপত্তার জন্য অফিশিয়াল 'Green Halal (清真)' লোগো ও ভেরিফাইড গাইডলাইন অনুসরণ করার অনুরোধ করা হচ্ছে।",
            "English": "This bot is a free AI tool. For 100% verified safety in China, please prioritize certified 'Halal (清真)' marks or trusted local halal monitoring guides.",
            "Indonesian": "Bot ini alat AI gratis. Untuk kepastian 100% di Tiongkok, pastikan mencari label resmi 'Halal (清真)' atau panduan sertifikasi lokal.",
            "Japanese": "当ボットは無料AIツールです。中国製品の100%確実な安全のため、公式の『清真（Halal）』マークや認証機関の確認を推奨します。",
            "Arabic": "هذا البوت أداة مجانية. لضمان الأمان التام بنسبة 100% في الصين، يرجى البحث عن علامة 'حلال (清真)' المعتمدة رسمياً."
        },
        "haram_prompt": """
        TARGET REGION: CHINA.
        Header: 配料 / 配料表.
        - HARAM: 猪肉, 猪油, 猪脂, 猪皮, 猪血, 培根, 火腿, 动物油脂, 鸡精, 浓汤宝, 料酒 (Chinese cooking wine), 黄酒, 白酒, 花雕酒, 米酒, 食用酒精, 啤酒, 明胶, 阿胶, 鸭血.
        - SYUBHAH: 起酥油, 人造奶油, 人造黄油, 乳化剂, 酶制剂, 食用香精.
        """
    },
    "Korea": {
        "title": "KR HALAL FOOD CHECKER 🇰🇷",
        "app_name": "'Mufko' & 'KMF Halal'",
        "advice": {
            "Bengali": "আমাদের এই বটটি একটি ফ্রি এআই টুল। দক্ষিণ কোরিয়ায় শতভাগ নিরাপদ খাদ্য বাছাই করতে 'Mufko' অথবা 'KMF Halal' ভেরিফাইড অ্যাপ ব্যবহারের অনুরোধ করা হচ্ছে।",
            "English": "This bot is a free AI tool. For 100% verified accuracy in South Korea, consider using the verified apps 'Mufko' or 'KMF Halal'.",
            "Indonesian": "Bot ini alat AI gratis. Untuk keakuratan 100% di Korea Selatan, disarankan menggunakan aplikasi terverifikasi seperti 'Mufko' atau 'KMF Halal'.",
            "Japanese": "当ボットは無料AIツールです。韓国国内での100%安全な食品選びには、公式アプリ『Mufko』や『KMF Halal』の併用を推奨します。",
            "Arabic": "هذا البوت أداة مجانية. للتحقق بنسبة 100% في كوريا الجنوبية، نوصي باستخدام التطبيقات المعتمدة مثل 'Mufko' أو 'KMF Halal'."
        },
        "haram_prompt": """
        TARGET REGION: SOUTH KOREA.
        Header: 원재료명 (Ingredients).
        - HARAM: 돼지고기 (Pork), 돈지/라드 (Lard), 햄 (Ham), 베이컨 (Bacon), 젤라틴 (돼지), 쇠고기/닭고기 (unless Halal certified), 맛술 (Cooking wine / Mirin), 청주 (Cheongju), 주정 (Fermented ethyl alcohol), 양조주, 알코올 (Alcohol), 동물성유지 (Animal fat). Note: Korean sauces (Gochujang, Ssamjang, Doenjang) often contain fermented alcohol/spirits.
        - SYUBHAH: 쇼트닝 (Shortening), 마가린 (Margarine), 유화제 (Emulsifier / E471), 가공유지 (Processed fat), 콜라겐 (Collagen), 효소제제 (Enzymes).
        - HALAL: 식물성유지 (Vegetable oil), 콩기름, 밀가루, 설탕, 천일염.
        """
    },
    "USA": {
        "title": "US HALAL FOOD CHECKER 🇺🇸",
        "app_name": "'Scan Halal' & 'Crescent Halal'",
        "advice": {
            "Bengali": "আমাদের এই বটটি একটি ফ্রি এআই টুল। যুক্তরাষ্ট্রে ১০০% নির্ভুল ও হালাল পণ্য নিশ্চিত করতে 'Scan Halal' অথবা 'Crescent Halal' অ্যাপ ব্যবহারের অনুরোধ করা হচ্ছে।",
            "English": "This bot is a free AI tool. For 100% verified accuracy in the US, we kindly advise using dedicated apps like 'Scan Halal' or 'Crescent Halal'.",
            "Indonesian": "Bot ini alat AI gratis. Untuk kepastian 100% di Amerika Serikat, disarankan menggunakan aplikasi seperti 'Scan Halal' atau 'Crescent Halal'.",
            "Japanese": "当ボットは無料AIツールです。米国での確実な判定には『Scan Halal』などの認証アプリのご利用をお勧めします。",
            "Arabic": "هذا البوت أداة مجانية. للتحقق التام بنسبة 100% في الولايات المتحدة، نوصي باستخدام تطبيقات متخصصة مثل 'Scan Halal'."
        },
        "haram_prompt": """
        TARGET REGION: USA (FDA Standard).
        Header: Ingredients.
        - HARAM: Pork, Bacon, Ham, Lard, Pork Gelatin, Non-Zabiha Beef/Chicken extracts, Animal Shortening, Carmine/Cochineal extract (E120), Pure Vanilla Extract (naturally contains at least 35% alcohol), Brewer's yeast (from brewing beer), Alcohol, Wine, Rum flavoring with alcohol.
        - SYUBHAH: Gelatin (unless specified Fish or Halal bovine), Mono and diglycerides (E471), Polysorbate 60/80, Whey powder (unless microbial rennet verified), Enzymes (animal vs microbial), Lipase, Pepsin, Natural and Artificial Flavors.
        - HALAL: 100% Vegetable oil, Plant-derived shortening, Soy lecithin, Agar-agar, Pectin, Certified Halal/Kosher Pareve (OU/KOF-K).
        """
    },
    "Bangladesh": {
        "title": "BD HALAL FOOD CHECKER 🇧🇩",
        "app_name": "ইফা হালাল সনদ (Islamic Foundation Halal)",
        "advice": {
            "Bengali": "আমাদের এই বটটি একটি ফ্রি এআই টুল। স্থানীয় ও আমদানিকৃত খাদ্য নির্বাচনে শতভাগ নিশ্চয়তার জন্য 'ইসলামিক ফাউন্ডেশন বাংলাদেশ' সনদ ও বিএসটিআই হালাল লোগো অনুসরণ করুন।",
            "English": "This bot is a free AI tool. For 100% verified certainty in Bangladesh, please prioritize products certified by Islamic Foundation Bangladesh & BSTI Halal.",
            "Indonesian": "Bot ini alat AI gratis. Untuk kepastian 100% di Bangladesh, utamakan produk bersertifikat Islamic Foundation Bangladesh.",
            "Japanese": "当ボットは無料AIツールです。バングラデシュではバングラデシュ・イスラム財団やBSTI認証マークの確認を推奨します。",
            "Arabic": "هذا البوت أداة مجانية. لضمان الحلية بنسبة 100% في بنغلاديش، يرجى التحقق من ختم المؤسسة الإسلامية البنغلاديشية."
        },
        "haram_prompt": """
        TARGET REGION: BANGLADESH.
        Header: উপাদান, উপাদানসমূহ, Ingredients.
        - HARAM: শুয়োরের মাংস/চর্বি (Pork, Lard), অ-হালাল প্রাণিজ জেলাটিন, ক্যারমাইন/E120, অ্যালকোহল, রাম এসেন্স, অ-হালাল আমদানিকৃত মাংসের ব্রোথ।
        - SYUBHAH: ইমালসিফায়ার (E471, E472), শর্টনিং, মার্জারিন, পনিরের রেনেট, হুই পাউডার, কৃত্রিম ফ্লেভার।
        """
    }
}

def get_country_selection_menu():
    return QuickReply(items=[
        QuickReplyItem(action=MessageAction(label="🇯🇵 Japan", text="Country: Japan")),
        QuickReplyItem(action=MessageAction(label="🇨🇳 China", text="Country: China")),
        QuickReplyItem(action=MessageAction(label="🇰🇷 Korea", text="Country: Korea")),
        QuickReplyItem(action=MessageAction(label="🇺🇸 USA", text="Country: USA")),
        QuickReplyItem(action=MessageAction(label="🇧🇩 Bangladesh", text="Country: Bangladesh"))
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
    country_info = COUNTRY_RULES.get(country, COUNTRY_RULES["Japan"])
    country_header = country_info["title"]
    advice_text = country_info["advice"].get(lang, country_info["advice"]["Bengali"])
    
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
                            "text": advice_text,
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
    return "Global Halal Food Checker Running (JP, CN, KR, US, BD)."

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

        # ধাপ ১: ৫টি দেশের নির্বাচন
        if raw_text.startswith("Country:"):
            chosen = raw_text.replace("Country:", "").strip().lower()
            if "china" in chosen:
                user_countries[user_id] = "China"
            elif "korea" in chosen or "한국" in chosen:
                user_countries[user_id] = "Korea"
            elif "usa" in chosen or "america" in chosen:
                user_countries[user_id] = "USA"
            elif "bangladesh" in chosen or "bd" in chosen:
                user_countries[user_id] = "Bangladesh"
            else:
                user_countries[user_id] = "Japan"

            current_country = user_countries[user_id]
            msg = I18N[current_lang]["country_selected"].format(country=current_country)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=msg, quick_reply=get_language_selection_menu())]
                )
            )
            return

        # ধাপ ২: ভাষা নির্বাচন
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
            msg = I18N[current_lang]["lang_confirm"].format(country=current_country)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=msg, quick_reply=get_direct_camera_quick_reply(current_lang))]
                )
            )
            return

        # রিচ মেনুর অ্যাকশন হ্যান্ডলিং
        if any(k in text for k in ["language", "ভাষা", "bahasa", "言語", "لغة", "country", "দেশ", "change language"]):
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(
                            text=I18N[current_lang]["select_country_first"],
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
        else:
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(
                            text=f"📍 Country: {current_country} | 🌐 Language: {current_lang}\n" + I18N[current_lang]["default_prompt"],
                            quick_reply=get_country_selection_menu()
                        )
                    ]
                )
            )

def call_gemini_vision(prompt, image_b64):
    candidate_models = [
        "models/gemini-2.5-flash",
        "models/gemini-2.5-flash-lite"
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
            "maxOutputTokens": 600,
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
        Act as a professional Global Halal Food Inspector specialized in packaged foods for target country: {selected_country}.
        
        Rules & Standards for {selected_country}:
        {country_context}

        Inspection Procedure:
        1. Accurately detect and transcribe the ingredient list from the packaging based on the country's label standard.
        2. Detect all Haram ingredients (pork derivatives, non-halal meat extracts, cooking alcohol/sake/mirin/liaojiu/cheongju, carmine/E120, animal fats).
        3. Detect any Syubhah/Doubtful components (shortening, emulsifiers E471/E472, unspecified animal gelatin, collagen, enzymes, yeast food) where animal vs plant origin is unstated.
        4. Strict Verdict Hierarchy: If ANY Haram ingredient is found -> status is 'HARAM'. Else if any Syubhah ingredient is found -> status is 'SYUBHAH'. If all ingredients are verified pure plant/mineral/permissible -> status is 'HALAL'.

        You MUST respond ONLY with a valid JSON matching this schema:
        {{
            "status": "HALAL" or "HARAM" or "SYUBHAH",
            "reason": "Accurate, concise analysis strictly written in {selected_lang}",
            "items": "Detected specific key ingredients (original text + translation) strictly written in {selected_lang}"
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
