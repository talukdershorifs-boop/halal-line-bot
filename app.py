import os
import io
import gc
import json
import time
import base64
import sqlite3
import requests
import pandas as pd
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

# সেশন ও ক্যাশিং
user_languages = {}
user_countries = {}
user_last_scans = {}

# ============================================================================
# ১. পারসিস্টেন্ট SQLite ডাটাবেস ইনিশিয়ালাইজেশন (রিস্টার্টেও ডেটা সুরক্ষিত)
# ============================================================================
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'halal_bot_storage.db')

def init_db():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        # স্ক্যান হিস্ট্রি টেবিল
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scan_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                product_name TEXT,
                company_name TEXT,
                status TEXT,
                reason TEXT,
                items TEXT,
                allergens TEXT,
                alternatives TEXT,
                country TEXT,
                barcode TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # বারকোড ক্যাশ টেবিল (ইনস্ট্যান্ট রেসপন্স)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS barcode_cache (
                barcode TEXT PRIMARY KEY,
                product_name TEXT,
                company_name TEXT,
                status TEXT,
                reason TEXT,
                items TEXT,
                allergens TEXT,
                alternatives TEXT,
                country TEXT
            )
        ''')
        # ফিডব্যাক লগ টেবিল
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                product_name TEXT,
                feedback_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Database init error: {e}")

init_db()

def get_cached_barcode(barcode):
    if not barcode:
        return None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT product_name, company_name, status, reason, items, allergens, alternatives, country FROM barcode_cache WHERE barcode = ?", (barcode,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {
                "product_name": row[0],
                "company_name": row[1],
                "status": row[2],
                "reason": row[3],
                "items": row[4],
                "allergens": row[5],
                "alternatives": row[6],
                "country": row[7]
            }
    except Exception as e:
        print(f"Cache lookup error: {e}")
    return None

def save_barcode_cache(barcode, data, country):
    if not barcode or len(barcode) < 6:
        return
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO barcode_cache (barcode, product_name, company_name, status, reason, items, allergens, alternatives, country)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (barcode, data.get('product_name'), data.get('company_name'), data.get('status'), data.get('reason'), data.get('items'), data.get('allergens'), data.get('alternatives'), country))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Cache save error: {e}")

def save_scan_history(user_id, data, country, barcode=""):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO scan_history (user_id, product_name, company_name, status, reason, items, allergens, alternatives, country, barcode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, data.get('product_name'), data.get('company_name'), data.get('status'), data.get('reason'), data.get('items'), data.get('allergens'), data.get('alternatives'), country, barcode))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"History save error: {e}")

def get_user_history_list(user_id, limit=10):
    records = []
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, product_name, company_name, status, reason, items, allergens, alternatives, country, barcode
            FROM scan_history WHERE user_id = ? ORDER BY id DESC LIMIT ?
        ''', (user_id, limit))
        rows = cursor.fetchall()
        conn.close()
        for r in rows:
            records.append({
                "id": r[0],
                "product_name": r[1],
                "company_name": r[2],
                "status": r[3],
                "reason": r[4],
                "items": r[5],
                "allergens": r[6],
                "alternatives": r[7],
                "country": r[8],
                "barcode": r[9]
            })
    except Exception as e:
        print(f"History fetch error: {e}")
    return records

def get_user_total_scans(user_id):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM scan_history WHERE user_id = ?", (user_id,))
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except:
        return 0

def log_user_feedback(user_id, product_name, feedback_type):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO user_feedback (user_id, product_name, feedback_type) VALUES (?, ?, ?)", (user_id, product_name, feedback_type))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Feedback log error: {e}")

# ============================================================================
# ২. CSV ডাটাবেস লোডার (১,৩৪২টি অনন্য উপাদান)
# ============================================================================
LOCAL_DB = {}
CSV_HARAM_KEYWORDS = []
CSV_VERIFY_KEYWORDS = []

def load_ingredients_database():
    global LOCAL_DB, CSV_HARAM_KEYWORDS, CSV_VERIFY_KEYWORDS
    base_dir = os.path.dirname(os.path.abspath(__file__))
    possible_files = [
        os.path.join(base_dir, 'halal_ingredients_ALL_app_unique.csv'),
        os.path.join(base_dir, 'halal data.csv'),
        'halal_ingredients_ALL_app_unique.csv',
        'halal data.csv'
    ]

    target_file = None
    for p in possible_files:
        if os.path.exists(p):
            target_file = p
            break

    if target_file:
        try:
            df = pd.read_csv(target_file)
            for _, row in df.iterrows():
                jp_name = str(row.get('japanese', '')).strip()
                status = str(row.get('status', 'VERIFY')).strip().upper()
                eng_name = str(row.get('english', '')).strip()
                bn_name = str(row.get('bangla', '')).strip()
                e_num = str(row.get('e_number', '')).strip() if pd.notnull(row.get('e_number')) else ""
                reason = str(row.get('reason_bn', '')).strip() if pd.notnull(row.get('reason_bn')) else ""

                item_info = {
                    "japanese": jp_name,
                    "english": eng_name,
                    "bangla": bn_name,
                    "status": status,
                    "e_number": e_num,
                    "reason": reason
                }

                if jp_name and jp_name != 'nan':
                    LOCAL_DB[jp_name] = item_info
                    if status == 'HARAM':
                        CSV_HARAM_KEYWORDS.append(jp_name)
                    elif status in ['VERIFY', 'SYUBHAH']:
                        CSV_VERIFY_KEYWORDS.append(jp_name)

                if e_num and e_num != 'nan':
                    LOCAL_DB[e_num.upper()] = item_info

            print(f"Loaded {len(LOCAL_DB)} verified item keys from {target_file}")
        except Exception as e:
            print(f"CSV read error: {e}")
    else:
        print("Notice: Running on cloud AI inspection rules.")

load_ingredients_database()

# ============================================================================
# ৩. বহুভাষিক ইন্টারফেস কনফিগারেশন
# ============================================================================
I18N = {
    "English": {
        "status_halal": "✅ HALAL",
        "status_haram": "❌ HARAM",
        "status_syubhah": "⚠️ SYUBHAH (Doubtful)",
        "label_reason": "Observation & Reason:",
        "label_items": "Detected Ingredients:",
        "label_alternatives": "💡 Recommended Halal Alternatives:",
        "label_allergens": "⚠️ Allergen Alert:",
        "label_hadith_title": "📜 Warning from Hadith:",
        "hadith_text": "The Prophet ﷺ said: 'What is lawful is clear and what is unlawful is clear, and between them are matters that are doubtful... So he who guards against doubtful matters clears himself in regard to his religion and his honor.' [Sahih al-Bukhari: 52, Sahih Muslim: 1599]",
        "label_advice_title": "💡 Important Recommendation:",
        "cam_btn": "📷 Open Camera",
        "cam_prompt": "Tap '📷 Open Camera' below to take a clear picture of the ingredient list:",
        "lang_confirm": "✅ Settings updated!\n📍 Country: {country}\n🌐 Language: English\n\nPlease send a clear photo of the ingredient list.",
        "country_selected": "📍 Country selected: {country}\nLanguage set to English. You can also pick another language below:",
        "default_prompt": "Please choose from the menu or send a photo of the ingredients list.",
        "select_country_first": "🌍 Please select your country or destination:",
        "btn_explain": "❓ Explain Ingredients",
        "btn_history": "📜 Scan History",
        "btn_share": "📤 Share Result",
        "btn_brand_guide": "🛒 Safe Brands Guide",
        "btn_feedback_ok": "🎯 Accurate Info",
        "btn_feedback_doubt": "🚩 Report / Review",
        "feedback_ok_msg": "Thank you! Your feedback helps keep this platform accurate. 🌟",
        "feedback_doubt_msg": "Noted! This product has been flagged for administrative review and double-checking. 🔍",
        "blurry_error": "⚠️ The image is blurry or the ingredients text is unreadable. Please take a closer, well-lit photo of the ingredients list.",
        "history_title": "📋 Your Food Check History (Total: {count}):\n",
        "history_empty": "You have no food scan history yet. Send an ingredient image to start checking.",
        "history_hint": "\n👉 Type the item number (e.g. 1, 2) to view the full result card again.",
        "counter_text": "📊 Total Checked: {total} (Item #{item_no})"
    },
    "Bengali": {
        "status_halal": "✅ HALAL (হালাল)",
        "status_haram": "❌ HARAM (হারাম)",
        "status_syubhah": "⚠️ SYUBHAH (সন্দেহজনক)",
        "label_reason": "পর্যবেক্ষণ ও কারণ:",
        "label_items": "শনাক্তকৃত উপাদান:",
        "label_alternatives": "💡 হালাল বিকল্প সাজেশন:",
        "label_allergens": "⚠️ অ্যালার্জি সতর্কতা:",
        "label_hadith_title": "📜 হাদিসের আলোকে সতর্কতা:",
        "hadith_text": "রাসূলুল্লাহ ﷺ বলেছেন: 'হালালও স্পষ্ট এবং হারামও স্পষ্ট। আর এ দুয়ের মাঝে রয়েছে বহু সন্দেহজনক বিষয়... যে ব্যক্তি সন্দেহজনক বিষয় থেকে নিজেকে বাঁচিয়ে রাখল, সে তার দ্বীন ও সম্মান রক্ষা করল।' [সহিহ বুখারি: ৫২, সহিহ মুসলিম: ১৫৯৯]",
        "label_advice_title": "💡 গুরুত্বপূর্ণ পরামর্শ:",
        "cam_btn": "📷 ক্যামেরা খুলুন",
        "cam_prompt": "নিচের '📷 ক্যামেরা খুলুন' বাটনে চাপ দিয়ে পণ্যের উপাদানের স্পষ্ট ছবি তুলুন:",
        "lang_confirm": "✅ সেটিংস সম্পন্ন হয়েছে!\n📍 দেশ: {country}\n🌐 ভাষা: বাংলা\n\nএখন খাবারের উপাদানের স্পষ্ট ছবি পাঠান।",
        "country_selected": "📍 দেশ নির্বাচিত: {country}\nভাষা বাংলায় সেট করা হয়েছে। চাইলে নিচে অন্য ভাষাও বেছে নিতে পারেন:",
        "default_prompt": "মেনু থেকে অপশন বেছে নিন অথবা পণ্যের উপাদানের স্পষ্ট ছবি পাঠান।",
        "select_country_first": "🌍 প্রথমে আপনার অবস্থান বা ভ্রমণের দেশ নির্বাচন করুন:",
        "btn_explain": "❓ উপাদান বিস্তারিত জানাও",
        "btn_history": "📜 হিস্ট্রি তালিকা",
        "btn_share": "📤 শেয়ার করুন",
        "btn_brand_guide": "🛒 নিরাপদ ব্র্যান্ড তালিকা",
        "btn_feedback_ok": "🎯 নির্ভুল তথ্য",
        "btn_feedback_doubt": "🚩 সংশয় / রিভিউ",
        "feedback_ok_msg": "ধন্যবাদ! আপনার ফিডব্যাক প্ল্যাটফর্মকে আরও নির্ভুল রাখবে। 🌟",
        "feedback_doubt_msg": "আপনার সংশয় নোট করা হয়েছে! পণ্যটি এডমিন রিচেকের তালিকায় যোগ করা হলো। 🔍",
        "blurry_error": "⚠️ ছবিটি অস্পষ্ট বা উপাদানের লেখা পড়া যাচ্ছে না। দয়া করে ভালো আলোতে সোজাভাবে উপাদানের স্পষ্ট ছবি তুলুন।",
        "history_title": "📋 আপনার চেক করা খাবারের ইতিহাস (মোট: {count}টি):\n",
        "history_empty": "আপনার এখনও কোনো খাবারের স্ক্যান ইতিহাস সংরক্ষিত নেই। উপাদানের ছবি পাঠিয়ে চেক করুন।",
        "history_hint": "\n👉 যে কোনো খাবারের বিস্তারিত কার্ড দেখতে তার নম্বর লিখে পাঠান (যেমন: 1, 2)।",
        "counter_text": "📊 মোট চেক করা হয়েছে: {total}টি (আইটেম #{item_no})"
    },
    "Indonesian": {
        "status_halal": "✅ HALAL",
        "status_haram": "❌ HARAM",
        "status_syubhah": "⚠️ SYUBHAH (Meragukan)",
        "label_reason": "Alasan & Observasi:",
        "label_items": "Bahan Terdeteksi:",
        "label_alternatives": "💡 Alternatif Halal Disarankan:",
        "label_allergens": "⚠️ Peringatan Alergen:",
        "label_hadith_title": "📜 Peringatan Hadits:",
        "hadith_text": "Rasulullah ﷺ bersabda: 'Sesungguhnya yang halal itu jelas dan yang haram itu jelas, dan di antara keduanya ada perkara-perkara syubhat... Barangsiapa menjauhi syubhat, maka ia telah membersihkan agama dan kehormatannya.' [HR. Bukhari: 52, Muslim: 1599]",
        "label_advice_title": "💡 Rekomendasi Penting:",
        "cam_btn": "📷 Buka Kamera",
        "cam_prompt": "Tekan tombol '📷 Buka Kamera' di bawah untuk mengambil foto komposisi:",
        "lang_confirm": "✅ Pengaturan selesai!\n📍 Negara: {country}\n🌐 Bahasa: Bahasa Indonesia\n\nSilakan kirim foto komposisi makanan.",
        "country_selected": "📍 Negara dipilih: {country}\nBahasa telah diatur ke Bahasa Indonesia. Anda juga dapat memilih bahasa lain di bawah ini:",
        "default_prompt": "Silakan pilih menu atau kirim foto daftar komposisi bahan.",
        "select_country_first": "🌍 Silakan pilih negara Anda terlebih dahulu:",
        "btn_explain": "❓ Jelaskan Bahan",
        "btn_history": "📜 Riwayat Cek",
        "btn_share": "📤 Bagikan Hasil",
        "btn_brand_guide": "🛒 Panduan Brand Aman",
        "btn_feedback_ok": "🎯 Informasi Akurat",
        "btn_feedback_doubt": "🚩 Laporkan / Tinjau",
        "feedback_ok_msg": "Terima kasih! Umpan balik Anda membantu menjaga keakuratan bot ini. 🌟",
        "feedback_doubt_msg": "Laporan diterima! Produk ini telah dicatat untuk ditinjau ulang oleh tim. 🔍",
        "blurry_error": "⚠️ Foto kurang jelas atau teks komposisi tidak terbaca. Harap ambil foto ulang dengan pencahayaan yang baik.",
        "history_title": "📋 Riwayat Pemeriksaan Makanan (Total: {count}):\n",
        "history_empty": "Belum ada riwayat pemeriksaan makanan tersimpan. Kirim foto bahan untuk memulai.",
        "history_hint": "\n👉 Ketik nomor item (misal: 1, 2) untuk melihat kartu hasil lengkap kembali.",
        "counter_text": "📊 Total Diperiksa: {total} (Item #{item_no})"
    },
    "Chinese": {
        "status_halal": "✅ 清真 (HALAL)",
        "status_haram": "❌ 非清真 (HARAM)",
        "status_syubhah": "⚠️ 疑似/存疑 (SYUBHAH)",
        "label_reason": "判断原因与分析:",
        "label_items": "检测到的主要配料:",
        "label_alternatives": "💡 推荐清真替代品:",
        "label_allergens": "⚠️ 过敏原警示:",
        "label_hadith_title": "📜 圣训警示:",
        "hadith_text": "先知穆罕默德 ﷺ 说：‘合法的（清真）是明白的，非法的也是明白的，在这两者之间有许多疑似的事物...避开疑似事物的人，确已保全了他的宗教和名节。’ [布哈里圣训: 52, 穆斯林圣训: 1599]",
        "label_advice_title": "💡 重要建议:",
        "cam_btn": "📷 打开相机",
        "cam_prompt": "点击下方‘📷 打开相机’按钮，清晰拍摄食品包装上的配料表:",
        "lang_confirm": "✅ 设置已完成！\n📍 国家: {country}\n🌐 语言: 简体中文\n\n请发送食品配料表清晰照片。",
        "country_selected": "📍 已选择国家: {country}\n语言已自动设为中文。您也可以在下方更改语言:",
        "default_prompt": "请从菜单选择功能，或直接发送配料表图片进行检查。",
        "select_country_first": "🌍 请先选择您所在的国家或目的地:",
        "btn_explain": "❓ 详细成分分析",
        "btn_history": "📜 检查历史",
        "btn_share": "📤 分享结果",
        "btn_brand_guide": "🛒 安全品牌指南",
        "btn_feedback_ok": "🎯 信息准确",
        "btn_feedback_doubt": "🚩 存疑 / 复核",
        "feedback_ok_msg": "感谢您的反馈！您的支持帮助我们维护更准确的数据。🌟",
        "feedback_doubt_msg": "已记录您的反馈！该商品已提交人工复核通道。🔍",
        "blurry_error": "⚠️ 照片模糊或配料文字无法清晰识别。请在光线良好处重新平整拍摄配料表。",
        "history_title": "📋 您的食品检查历史记录 (总计: {count}):\n",
        "history_empty": "暂无检查记录。请拍摄并发送食品配料表照片开始使用。",
        "history_hint": "\n👉 发送对应编号（如：1, 2）可重新查看完整结果卡片。",
        "counter_text": "📊 已检查总数: {total} (第 #{item_no} 件)"
    },
    "Japanese": {
        "status_halal": "✅ ハラール (HALAL)",
        "status_haram": "❌ ハラーム (HARAM)",
        "status_syubhah": "⚠️ シュブハ (疑わしい)",
        "label_reason": "判定理由・観察:",
        "label_items": "検出された原材料:",
        "label_alternatives": "💡 推奨されるハラール代替品:",
        "label_allergens": "⚠️ アレルギー注意:",
        "label_hadith_title": "📜 ハディースによる教え:",
        "hadith_text": "預言者ムハンマド ﷺ は仰いました:『合法（ハラール）なものは明白であり、非合法（ハラーム）なものも明白である。そして両者の間には疑わしい事柄がある...疑わしいものを避ける者は、自らの宗教と名誉を守ることになる。』[サヒーフ・ブハーリー: 52, サヒーフ・ムスリム: 1599]",
        "label_advice_title": "💡 重要なお知らせ:",
        "cam_btn": "📷 カメラを起動",
        "cam_prompt": "下の『📷 カメラを起動』ボタンを押して原材料名の写真を撮影してください:",
        "lang_confirm": "✅ 設定が完了しました！\n📍 対象国: {country}\n🌐 言語: 日本語\n\n原材料名の写真を送信してください。",
        "country_selected": "📍 国を選択しました: {country}\n言語が日本語に設定されました。別の言語を選ぶことも可能です:",
        "default_prompt": "メニューから選択するか、商品の原材料名（原材料表示）の写真を送信してください。",
        "select_country_first": "🌍 まず対象の国を選択してください:",
        "btn_explain": "❓ 成分の詳細解説",
        "btn_history": "📜 履歴一覧",
        "btn_share": "📤 結果を共有",
        "btn_brand_guide": "🛒 安全商品ガイド",
        "btn_feedback_ok": "🎯 正確な情報",
        "btn_feedback_doubt": "🚩 疑義 / 再確認",
        "feedback_ok_msg": "フィードバックありがとうございます！正確な情報維持に役立てられます。🌟",
        "feedback_doubt_msg": "承知いたしました！該当製品を管理者の再確認対象として登録しました。🔍",
        "blurry_error": "⚠️ 画像が不鮮明か原材料の文字が読み取れませんでした。明るい場所で正面から再度撮影してください。",
        "history_title": "📋 食品判定履歴 (合計: {count}件):\n",
        "history_empty": "まだ履歴がありません。原材料の写真を送信して判定を開始してください。",
        "history_hint": "\n👉 番号（例: 1, 2）を送信すると、詳細結果を再確認できます。",
        "counter_text": "📊 チェック済み総数: {total}件 (アイテム #{item_no})"
    },
    "Arabic": {
        "status_halal": "✅ حلال (HALAL)",
        "status_haram": "❌ حرام (HARAM)",
        "status_syubhah": "⚠️ شبهة (SYUBHAH)",
        "label_reason": "الملاحظة والسبب:",
        "label_items": "المكونات المكتشفة:",
        "label_alternatives": "💡 البدائل الحلال المقترحة:",
        "label_allergens": "⚠️ تنبيه مسببات الحساسية:",
        "label_hadith_title": "📜 التحذير النبوي الشريف:",
        "hadith_text": "قال رسول الله ﷺ: 'إن الحلال بيّن وإن الحرام بيّن، وبينهما أمور مشتبهات... فمن اتقى الشبهات فقد استبرأ لدينه وعِرضه.' [صحيح البخاري: ٥٢، صحيح مسلم: ١٥٩٩]",
        "label_advice_title": "💡 نصيحة هامة:",
        "cam_btn": "📷 فتح الكاميرا",
        "cam_prompt": "اضغط على زر '📷 فتح الكاميرا' بالأسفل لتصوير قائمة المكونات بوضوح:",
        "lang_confirm": "✅ تم ضبط الإعدادات بنجاح!\n📍 الدولة: {country}\n🌐 اللغة: العربية\n\nيرجى إرسال صورة واضحة لقائمة المكونات.",
        "country_selected": "📍 تم تحديد الدولة: {country}\nتم تعيين اللغة. يمكنك أيضاً تغيير اللغة بالأسفل:",
        "default_prompt": "يرجى الاختيار من القائمة أو إرسال صورة واضحة لقائمة المكونات.",
        "select_country_first": "🌍 يرجى اختيار الدولة أولاً:",
        "btn_explain": "❓ تفاصيل المكونات",
        "btn_history": "📜 سجل الفحص",
        "btn_share": "📤 مشاركة النتيجة",
        "btn_brand_guide": "🛒 دليل العلامات الآمنة",
        "btn_feedback_ok": "🎯 معلومات دقيقة",
        "btn_feedback_doubt": "🚩 شك / مراجعة",
        "feedback_ok_msg": "شكراً لك! يساعدنا تقييمك في تحسين دقة المنصة. 🌟",
        "feedback_doubt_msg": "تم تسجيل ملاحظتك! سيتم فحص هذا المنتج والتحقق منه من قبل المشرفين. 🔍",
        "blurry_error": "⚠️ الصورة غير واضحة أو يتعذر قراءة قائمة المكونات. يرجى إعادة التقاط الصورة بوضوح وإضاءة جيدة.",
        "history_title": "📋 سجل فحص الأطعمة الخاص بك (الإجمالي: {count}):\n",
        "history_empty": "لا يوجد سجل فحص حتى الآن. يرجى إرسال صورة للمكونات للبدء.",
        "history_hint": "\n👉 أرسل رقم العنصر (مثال: 1, 2) لإعادة عرض بطاقة النتيجة التفصيلية.",
        "counter_text": "📊 إجمالي العناصر المفحوصة: {total} (عنصر #{item_no})"
    }
}

# ============================================================================
# ৪. দেশভিত্তিক তথ্য ও রেডিমেড হালাল ব্র্যান্ড গাইড
# ============================================================================
SAFE_BRAND_GUIDES = {
    "Japan": """🛒 [Japan 🇯🇵] জনপ্রিয় নিরাপদ হালাল ও প্ল্যান্ট-বেসড ব্র্যান্ড:
• চকলেট: Meiji Milk Chocolate (Standard red pack), Lotte Ghana Black
• পাউরুটি: Pasco Chojuku (超熟 - 100% উদ্ভিজ্জ তেল)
• চিপস: Calbee Potato Chips Usushio (うすしお味 - শুধু লবণ ও আলু)
• নুডুলস: Halal Certified Samyang Buldak (Japan Edition)
• সয়া সস: Kikkoman Halal Gluten-Free Soy Sauce""",

    "USA": """🛒 [USA 🇺🇸] Certified Halal & Kosher Pareve Brands:
• Bread: Dave's Killer Bread, Nature's Own 100% Whole Wheat
• Snacks: Lay's Classic Potato Chips, Fritos Original
• Cookies: Oreo Original (No animal fat, dairy/alcohol free)
• Sauce: Heinz Tomato Ketchup (Certified Kosher/Pareve)
• Ice Cream: Ben & Jerry's (Kosher certified varieties)""",

    "China": """🛒 [China 🇨🇳] 常用推荐清真与安全品牌:
• 调味品: 驻马店清真十三香、老干妈香辣脆油辣椒
• 方便食品: 康师傅清真系列牛肉面、统一清真方便面
• 零食: 三只松鼠每日坚果 (原味)、恰恰原味香瓜子
• 饮料/乳品: 蒙牛纯牛奶 (伊协清真标)、伊利纯牛奶""",

    "Korea": """🛒 [Korea 🇰🇷] Verified Halal & Muslim-Friendly Items:
• Ramyun: Samyang Buldak (KMF Halal Certified Green Logo)
• Seaweed: CJ Bibigo Roasted Seaweed (Olive oil & salt)
• Snacks: Orion Choco Pie (Halal export edition only)
• Milk: Binggrae Banana Flavored Milk (Halal certified batch)""",

    "Indonesia": """🛒 [Indonesia 🇮🇩] Brand Terverifikasi Halal BPJPH/MUI:
• Mi Instan: Indomie (Semua varian berlogo Halal resmi BPJPH)
• Biskuit/Roti: Sari Roti, Khong Guan Biscuit
• Minuman: Ultra Milk, Teh Botol Sosro
• Bumbu: Bumbu Racik Indofood, Saus Sambal ABC""",

    "Bangladesh": """🛒 [Bangladesh 🇧🇩] স্বীকৃত নিরাপদ ব্র্যান্ড গাইড:
• বিস্কুট: প্রাণ অল-টাইম, অলিম্পিক এনার্জি প্লাস
• দুগ্ধজাত: মিল্ক ভিটা, আড়ং ডেইরি মিল্ক
• তেল ও মসলা: রাঁধুনী পিওর মসলা, রূপচাঁদা সয়াবিন তেল
• স্ন্যাকস: বম্বে সুইটস পটেটো ক্র্যাকার্স"""
}

COUNTRY_DETAILS = {
    "Indonesia": {
        "title": "ID HALAL FOOD CHECKER 🇮🇩",
        "advice_app": {
            "English": "In Indonesia, prioritize items with the official BPJPH Halal logo or verify via the official 'Halal MUI / BPJPH' portal.",
            "Bengali": "ইন্দোনেশিয়ায় নিশ্চিত হতে সরকারি BPJPH হালাল লোগো এবং 'Halal MUI' অ্যাপ অথবা পোর্টালে যাচাই করুন।",
            "Indonesian": "Di Indonesia, utamakan produk dengan logo Halal resmi BPJPH Indonesia atau verifikasi langsung via aplikasi Halal MUI/BPJPH.",
            "Chinese": "在印度尼西亚，请优先选购带有官方BPJPH清真标识的商品，或通过Halal MUI官方平台核实。"
        },
        "haram": {
            "English": "🚫 [Indonesia 🇮🇩] Haram Ingredients:\n• Babi, Daging Babi, Lemak Babi (Pork & Lard)\n• Ham, Bacon, Gelatin Babi (Pork Gelatin)\n• Darah, Saren / Marus (Congealed animal blood)\n• Alkohol, Minuman Beralkohol, Rum, Angciu (Cooking wine)\n• Mirin beralkohol, Arak masak",
            "Bengali": "🚫 [ইন্দোনেশিয়া 🇮🇩] নিশ্চিত হারাম উপাদান:\n• Babi, Daging Babi | শুকরের মাংস\n• Lemak Babi, Lard | শুকরের চর্বি\n• Saren, Marus | জমাট বাঁধা রক্তের খাবার\n• Angciu, Arak masak | চাইনিজ রান্নার অ্যালকোহলীয় মদ\n• Rum, Mirin beralkohol | অ্যালকোহল ও মদ",
            "Indonesian": "🚫 [Indonesia 🇮🇩] Bahan Pasti Haram:\n• Daging Babi, Lemak Babi (Lard), Porcine\n• Ham, Bacon, Gelatin Babi\n• Saren / Marus / Didih (Darah beku hewan)\n• Angciu (Arak Merah masak), Mirin beralkohol\n• Rum, Ekstrak rasa mengandung alkohol tinggi",
            "Chinese": "🚫 [印尼 🇮🇩] 严禁成分 (Haram):\n• 猪肉 (Daging Babi)、猪油 (Lemak Babi / Lard)\n• 猪明胶 (Gelatin Babi)、培根、火腿\n• 动物血制品 (Saren / Marus)\n• 料理红酒/料酒 (Angciu)、含酒精味霖 (Mirin)"
        },
        "syubhah": {
            "English": "⚠️ [Indonesia 🇮🇩] Syubhah (Doubtful):\n• Emulsifier / Pengemulsi (E471, E472) - without vegetable statement\n• Shortening / Mentega Putih (animal-fat risk)\n• Gelatin, Kolagen (unspecified origin)\n• Perisa Alami / Artifisial (unspecified alcohol solvent)",
            "Bengali": "⚠️ [ইন্দোনেশিয়া 🇮🇩] সন্দেহজনক উপাদান (Syubhah):\n• Pengemulsi / Emulsifier (E471) - উদ্ভিজ্জ উৎস নিশ্চিত না হলে\n• Mentega Putih / Shortening (প্রাণিজ চর্বির ঝুঁকি)\n• Gelatin, Kolagen (মাছের বা হালাল গরু নিশ্চিত না হলে)\n• Perisa (কৃত্রিম ফ্লেভারে অ্যালকোহল দ্রাবক)",
            "Indonesian": "⚠️ [Indonesia 🇮🇩] Bahan Syubhat (Meragukan):\n• Pengemulsi / Emulsifier (E471, E472) - jika sumber nabati/hewani tidak tertera\n• Mentega putih / Shortening (potensi lemak hewani)\n• Gelatin & Kolagen (tanpa keterangan ikan/sapi halal)\n• Perisa alami/buatan (potensi pelarut alkohol)",
            "Chinese": "⚠️ [印尼 🇮🇩] 存疑成分 (Syubhah):\n• 乳化剂 (Pengemulsi / E471) - 未标明植物来源\n• 起酥油 (Mentega Putih / Shortening)\n• 明胶、胶原蛋白 (未标明鱼类或清真牛源)\n• 食用香精 (可能含酒精溶剂)"
        },
        "tips": {
            "English": "🛒 [Indonesia 🇮🇩] Shopping Tips:\n1. Look for the official Purple 'Halal Indonesia' (BPJPH) Gunungan logo.\n2. In local Chinese restaurants, beware of dishes with 'Babi' or 'Non-Halal' labels.\n3. Check imported snacks (Korean/Japanese) carefully as they may lack local Halal certification.",
            "Bengali": "🛒 [ইন্দোনেশিয়া 🇮🇩] কেনাকাটার টিপস:\n১. প্যাকেটের গায়ে বেগুনী রঙের সরকারি 'Halal Indonesia' (BPJPH) লোগো দেখে নিন।\n২. চাইনিজ দোকানে 'Babi' বা 'Non-Halal' সাইনবোর্ড আছে কি না খেয়াল রাখুন।\n৩. কোরিয়ান বা জাপানি আমদানিকৃত স্ন্যাকসে স্থানীয় হালাল সিল না থাকলে উপাদান পরীক্ষা করুন।",
            "Indonesian": "🛒 [Indonesia 🇮🇩] Tips Belanja Aman:\n1. Pastikan terdapat logo resmi Halal Indonesia (Gunungan warna ungu) dari BPJPH.\n2. Waspadai produk impor yang belum memiliki nomor registrasi BPJPH.\n3. Periksa restoran non-halal dengan label 'Non-Halal' atau menu bertuliskan 'Babi/Pork'.",
            "Chinese": "🛒 [印尼 🇮🇩] 购物指南:\n1. 认准印尼宗教部BPJPH官方紫色‘Halal Indonesia’印章。\n2. 进口中日韩休闲零食若无本地Halal认证编号，须仔细甄别。"
        },
        "info": {
            "English": "ℹ️ [Indonesia 🇮🇩] Guide:\n• Take a clear picture of the 'Komposisi' (Ingredients) list on the package.\n• All food circulated in Indonesia is legally required to hold Halal certification or clearly declare Non-Halal.",
            "Bengali": "ℹ️ [ইন্দোনেশিয়া 🇮🇩] নির্দেশিকা:\n• প্যাকেটের উল্টো পাশের 'Komposisi' (উপাদান) অংশের স্পষ্ট ছবি তুলুন।\n• ইন্দোনেশিয়ার আইন অনুযায়ী সব খাদ্য হয় হালাল সার্টিফায়েড হবে অথবা স্পষ্ট 'Non-Halal' লেখা থাকবে।",
            "Indonesian": "ℹ️ [Indonesia 🇮🇩] Panduan:\n• Foto bagian 'Komposisi' bahan secara tegak dan jelas.\n• Berdasarkan UU JPH, semua produk makanan wajib bersertifikat halal atau mencantumkan label non-halal secara tegas.",
            "Chinese": "ℹ️ [印尼 🇮🇩] 指南:\n• 请正对食品包装背面的‘Komposisi’（配料表）部分拍照。"
        }
    },
    "Japan": {
        "title": "JP HALAL FOOD CHECKER 🇯🇵",
        "advice_app": {
            "English": "This bot is a free AI tool. For 100% verified accuracy in Japan, we highly recommend using the officially verified paid app 'Halal Japan'.",
            "Bengali": "আমাদের এই বটটি একটি ফ্রি এআই টুল। জাপানে শতভাগ নির্ভরযোগ্য তথ্যের জন্য ভেরিফাইড পেইড অ্যাপ 'Halal Japan' ব্যবহারের অনুরোধ করা হচ্ছে।",
            "Chinese": "本机器人为免费AI工具。如需在日本获取100%经过人工核实的安全信息，强烈建议使用官方认证付费App『Halal Japan』。",
            "Japanese": "当ボットは無料AIツールです。日本国内での100%確実な安全確認には、公式認証アプリ『Halal Japan』(有料)のご利用を推奨します。"
        },
        "haram": {
            "English": "🚫 [Japan 🇯🇵] Haram Ingredients:\n• 豚肉, ポーク (Pork)\n• 豚脂, ラード (Pork Fat / Lard)\n• ハム, ベーコン, 豚骨エキス (Ham, Bacon, Pork bone extract)\n• 豚ゼラチン (Pork gelatin)\n• 牛肉, 鶏肉 (Non-halal beef/chicken)\n• 動物性油脂, 混合油脂 (Animal fats)\n• アルコール, 洋酒, 酒精 (Alcohol, Spirits)\n• 酒, 清酒, 料理酒, 味醂 (Mirin / Cooking Sake)",
            "Bengali": "🚫 [জাপান 🇯🇵] নিশ্চিত হারাম উপাদান:\n• 豚肉、ポーク | শুকরের মাংস\n• 豚脂肪、豚脂、ラード | শুকরের চর্বি / লার্ড\n• ハム、ベーコン、豚骨エキス | হ্যাম, বেকন, শুকরের হাড়ের নির্যাস\n• 豚ゼラチン | শুকরের জেলাটিন\n• 動物性油脂、混合油脂 | সাধারণ প্রাণিজ চর্বি\n• アルコール、洋酒、酒精 | অ্যালকোহল, মদ\n• 酒、清酒、料理酒、味醂 (みりん) | রান্নার মদ, মিরিন",
            "Chinese": "🚫 [日本 🇯🇵] 严禁成分 (Haram):\n• 豚肉、ポーク (猪肉)\n• 豚脂、ラード (猪油/白油)\n• ハム、ベーコン、豚骨エキス (火腿、培根、猪骨提取物)\n• 豚ゼラチン (猪明胶)\n• 牛肉、鶏肉 (未经清真屠宰的肉类)\n• 動物性油脂、混合油脂 (动物油脂)\n• アルコール、洋酒、酒精 (酒精、食用酒精)\n• 酒、料理酒、味醂/みりん (日本料理酒、味霖)"
        },
        "syubhah": {
            "English": "⚠️ [Japan 🇯🇵] Syubhah (Doubtful):\n• 乳化剤 (Emulsifier / E471) - unless plant-based (植物性)\n• ショートニング (Shortening - baking fat)\n• マーガリン (Margarine)\n• 加工油脂 (Processed oils)\n• ゼラチン, コラーゲン (Gelatin/Collagen - unless fish origin)\n• アミノ酸等 (Seasoning - if origin unstated)",
            "Bengali": "⚠️ [জাপান 🇯🇵] সন্দেহজনক উপাদান (Syubhah):\n• 乳化剤 (ইমালসিফায়ার / E471) - 植物性 (উদ্ভিজ্জ) না লেখা থাকলে\n• ショートニング (শর্টনিং - বেকারি চর্বি)\n• マーガリン (মার্জারিন)\n• 加工油脂 (প্রক্রিয়াজাত চর্বি)\n• ゼラチン、コラーゲン (জেলাটিন - মাছের নিশ্চিত উল্লেখ ছাড়া)\n• アミノ酸等 (প্রাণিজ উৎসের সম্ভাবনা থাকলে)",
            "Chinese": "⚠️ [日本 🇯🇵] 存疑成分 (Syubhah):\n• 乳化剤 (乳化剂 / E471) - 未注明植物来源时\n• ショートニング (起酥油)\n• マーガリン (人造奶油)\n• 加工油脂 (加工油脂)\n• ゼラチン、コラーゲン (明胶/胶原蛋白 - 非鱼源)"
        },
        "tips": {
            "English": "🛒 [Japan 🇯🇵] Shopping Tips:\n1. Look for '植物性' or '植物油脂' (Plant-based) on breads.\n2. Avoid western pastries, chocolates with '洋酒' (Liquor).\n3. Check Onigiri rice balls for '味醂' (Mirin) flavoring.\n4. In convenience stores, look for pure salt-flavored potato chips.",
            "Bengali": "🛒 [জাপান 🇯🇵] কেনাকাটার টিপস:\n১. পাউরুটি ও বিস্কুটে '植物性' বা '植物油脂' (উদ্ভিজ্জ) লেখা থাকলে নিরাপদ।\n২. পেস্ট্রি, কেক ও চকলেট কেনার সময় '洋酒' (মদ) পরিহার করুন।\n৩. কনভিনিয়েন্স স্টোরের ওনিগিরিতে 'みりん' (মিরিন) ফ্লেভার থাকে, চেক করুন।\n৪. সাধারণ পটেটো চিপসে শুধু লবণ দেওয়া (しお味) প্যাকেটগুলো নিরাপদ থাকে।",
            "Chinese": "🛒 [日本 🇯🇵] 购物小贴士:\n1. 购买面包时注意是否有‘植物性’或‘植物油脂’标识。\n2. 糕点甜品中常含有‘洋酒’或‘酒精’，需仔细甄别。\n3. 部分便利店饭团使用‘味醂（みりん）’调味，请留意。"
        },
        "info": {
            "English": "ℹ️ [Japan 🇯🇵] Guide:\n• Take a flat, clear photo of the '原材料名' (Ingredients) table.\n• Use 'Halal Japan' paid app for full manufacturer verification.",
            "Bengali": "ℹ️ [জাপান 🇯🇵] নির্দেশিকা:\n• পণ্যের উপাদানের তালিকার (原材料名) সোজা ও স্পষ্ট ছবি স্ক্যান করুন।\n• শতভাগ নিরাপদ থাকার জন্য অফিশিয়াল 'Halal Japan' অ্যাপ ব্যবহার করুন।",
            "Chinese": "ℹ️ [日本 🇯🇵] 指南:\n• 请清晰拍摄包装上的‘原材料名’部分。\n• 建议配合『Halal Japan』官方App核实生产线交叉污染。"
        }
    },
    "USA": {
        "title": "US HALAL FOOD CHECKER 🇺🇸",
        "advice_app": {
            "English": "This bot is a free AI tool. For 100% verified certainty in the USA, consider checking with apps like 'Scan Halal' or 'Crescent Halal'.",
            "Bengali": "আমাদের এই বটটি একটি ফ্রি এআই টুল। যুক্তরাষ্ট্রে ১০০% নির্ভুলতার জন্য 'Scan Halal' অথবা 'Crescent Halal' অ্যাপ ব্যবহার করুন।",
            "Chinese": "本机器人为免费AI工具。在美国获取100%认证信息，建议参考『Scan Halal』或IFANCA认证。"
        },
        "haram": {
            "English": "🚫 [USA 🇺🇸] Haram Ingredients:\n• Pork, Bacon, Ham, Pork Lard\n• Pork Gelatin / Animal Gelatin\n• Carmine / Cochineal Extract (E120)\n• Pure Vanilla Extract (Contains 35%+ alcohol by FDA law)\n• Brewer's Yeast (from beer brewing)\n• Cooking wines, Rum flavorings",
            "Bengali": "🚫 [USA 🇺🇸] নিশ্চিত হারাম উপাদান:\n• Pork, Bacon, Ham, Lard | শুকর ও চর্বি\n• Pork Gelatin / Gelatin (অ-হালাল উৎস)\n• Carmine / Cochineal Extract (E120) | লাল পোকার রঙ\n• Pure Vanilla Extract (৩৫%+ অ্যালকোহল থাকে)\n• Wine, Rum flavoring",
            "Chinese": "🚫 [美国 🇺🇸] 严禁成分 (Haram):\n• 猪肉、培根、火腿、猪油 (Pork, Bacon, Lard)\n• 猪明胶 (Pork Gelatin)\n• 胭脂红/胭脂虫红 (Carmine / E120)\n• 纯香草精 (Pure Vanilla Extract - FDA规定含35%以上酒精)\n• 啤酒酵母 (Brewer's Yeast)\n• 料理酒、含酒精香精"
        },
        "syubhah": {
            "English": "⚠️ [USA 🇺🇸] Syubhah (Doubtful):\n• Mono and diglycerides (E471)\n• Shortening (unless marked 100% vegetable)\n• Whey powder / Animal Rennet in Cheese\n• Natural & Artificial Flavors (alcohol carriers)",
            "Bengali": "⚠️ [USA 🇺🇸] সন্দেহজনক উপাদান (Syubhah):\n• Mono and diglycerides (E471)\n• Shortening\n• Whey powder / Animal Rennet\n• Natural & Artificial Flavors",
            "Chinese": "⚠️ [美国 🇺🇸] 存疑成分 (Syubhah):\n• 单双甘油酯 (E471 - 动植物来源不明)\n• 起酥油 (Shortening - 未注明全植物)\n• 乳清粉/奶酪动物凝乳酶 (Rennet)\n• 天然与人工香精 (可能使用酒精作为溶剂)"
        },
        "tips": {
            "English": "🛒 [USA 🇺🇸] Shopping Tips:\n1. Look for 'Kosher Pareve' (OU Pareve) which guarantees meat/alcohol free.\n2. Check gummy candies and marshmallows for Pork Gelatin.\n3. Buy '100% Vegetable Shortening' for baking.",
            "Bengali": "🛒 [USA 🇺🇸] কেনাকাটার টিপস:\n১. Kosher Pareve সিল থাকলে মাংস ও অ্যালকোহলমুক্ত থাকে।\n২. মার্শমেলো ও গামিতে জেলাটিন চেক করুন।",
            "Chinese": "🛒 [美国 🇺🇸] 购物小贴士:\n1. 认准‘Kosher Pareve’(正统犹太素食洁食)标识，不含肉类和酒精。\n2. 棉花糖、软糖通常含猪明胶，请特别注意。"
        },
        "info": {
            "English": "ℹ️ [USA 🇺🇸] Guide:\n• Take a clear picture of the 'Ingredients' section on the FDA nutrition label.",
            "Bengali": "ℹ️ [USA 🇺🇸] নির্দেশিকা:\n• প্যাকেটের 'Ingredients' অংশের সোজা ছবি স্ক্যান করুন।",
            "Chinese": "ℹ️ [美国 🇺🇸] 指南:\n• 请清晰拍摄FDA营养标签下方的‘Ingredients’部分。"
        }
    },
    "China": {
        "title": "CN HALAL FOOD CHECKER 🇨🇳",
        "advice_app": {
            "English": "This bot is a free AI tool. In China, prioritize items with official 'Green Halal (清真)' certificates.",
            "Bengali": "চীনে খাদ্যের নিশ্চয়তার জন্য 'Green Halal (清真)' লোগো ও সার্টিফিকেট অনুসরণ করুন।",
            "Chinese": "本机器人为免费AI工具。在中国境内选购食品，请认准中国伊斯兰教协会或各省市伊协认证的‘清真 (Halal)’标志。"
        },
        "haram": {
            "English": "🚫 [China 🇨🇳] Haram Ingredients:\n• 猪肉, 猪油, 猪脂 (Pork & Lard)\n• 猪血, 鸭血 (Blood curds)\n• 料酒, 黄酒, 白酒 (Cooking wine & Liquor)\n• 鸡精, 浓汤宝 (Non-halal broths)\n• 明胶, 阿胶 (Gelatin & Donkey-hide gelatin)",
            "Bengali": "🚫 [চীন 🇨🇳] নিশ্চিত হারাম উপাদান:\n• 猪肉、猪油 (শুকরের মাংস ও চর্বি)\n• 猪血、鸭血 (রক্তজাত খাবার)\n• 料酒、黄酒、白酒 (চীনা রান্নার মদ)\n• 鸡精、浓汤宝 (অ-হালাল ব্রোথ)",
            "Chinese": "🚫 [中国 🇨🇳] 严禁成分 (Haram):\n• 猪肉、猪油、猪脂、猪皮、猪肉浸膏\n• 猪血、鸭血、血旺等血液制品\n• 料酒、黄酒、白酒、花雕酒、米酒、食用酒精\n• 非清真鸡精、鸡汁、浓汤宝\n• 明胶、阿胶 (驴皮胶)"
        },
        "syubhah": {
            "English": "⚠️ [China 🇨🇳] Syubhah (Doubtful):\n• 起酥油 (Shortening)\n• 人造奶油, 人造黄油 (Margarine)\n• 乳化剂 (Emulsifier / E471)\n• 食用香精 (Flavors)",
            "Bengali": "⚠️ [চীন 🇨🇳] সন্দেহজনক উপাদান (Syubhah):\n• 起酥油 (শর্টনিং)\n• 人造奶油 (মার্জারিন)\n• 乳化剂 (ইমালসিফায়ার E471)",
            "Chinese": "⚠️ [中国 🇨🇳] 存疑成分 (Syubhah):\n• 起酥油 (可能含有动物油脂)\n• 人造奶油、人造黄油 (植脂或动脂混炼)\n• 乳化剂、单双甘油脂肪酸酯\n• 食用香精 (香精载体可能含醇)"
        },
        "tips": {
            "English": "🛒 [China 🇨🇳] Shopping Tips:\n1. Look for the green '清真' logo.\n2. Instant noodles often use '料酒' (cooking wine) in sauce packets.",
            "Bengali": "🛒 [চীন 🇨🇳] কেনাকাটার টিপস:\n১. প্যাকেটের গায়ে সবুজ '清真' সিল আছে কি না দেখুন।\n২. নুডুলসের সসে '料酒' থাকতে পারে।",
            "Chinese": "🛒 [中国 🇨🇳] 购物小贴士:\n1. 优先选购带有绿色‘清真’标识的正规食品。\n2. 方便面与自热火锅的酱包中极常含有‘料酒’，务必检查。"
        },
        "info": {
            "English": "ℹ️ [China 🇨🇳] Guide:\n• Take a photo of the '配料' or '配料表' (Ingredients).",
            "Bengali": "ℹ️ [চীন 🇨🇳] নির্দেশিকা:\n• উপাদানের তালিকার (配料表) সোজা ছবি পাঠান।",
            "Chinese": "ℹ️ [中国 🇨🇳] 指南:\n• 请清晰拍摄食品包装背面的‘配料’或‘配料表’。"
        }
    },
    "Korea": {
        "title": "KR HALAL FOOD CHECKER 🇰🇷",
        "advice_app": {
            "English": "For 100% verified accuracy in South Korea, consider using apps like 'Mufko' or 'KMF Halal'.",
            "Bengali": "দক্ষিণ কোরিয়ায় শতভাগ নিশ্চয়তার জন্য 'Mufko' অথবা 'KMF Halal' অ্যাপ ব্যবহার করুন।",
            "Chinese": "在韩国请认准KMF清真认证，或使用韩国本地开发的『Mufko』App。"
        },
        "haram": {
            "English": "🚫 [Korea 🇰🇷] Haram Ingredients:\n• 돼지고기 (Pork)\n• 돈지 / 라드 (Pork Fat / Lard)\n• 햄, 베이컨 (Ham, Bacon)\n• 맛술, 미림 (Cooking wine / Mirin)\n• 청주, 주정 (Alcohol / Spirits in sauces)\n• 동물성유지 (Animal fat)",
            "Bengali": "🚫 [কোরিয়া 🇰🇷] নিশ্চিত হারাম উপাদান:\n• 돼지고기 (শুকরের মাংস)\n• 돈지 / 라드 (লার্ড)\n• 맛술, 미림 (রান্নার মদ)\n• 주정 (অ্যালকোহল)",
            "Chinese": "🚫 [韩国 🇰🇷] 严禁成分 (Haram):\n• 돼지고기 (猪肉)\n• 돈지 / 라드 (猪油)\n• 햄, 베이컨 (火腿、培根)\n• 맛술, 미림 (料酒、味霖)\n• 청주, 주정 (清酒、酒精 - 辣酱中极常见)\n• 동물성유지 (动物油脂)"
        },
        "syubhah": {
            "English": "⚠️ [Korea 🇰🇷] Syubhah (Doubtful):\n• 쇼트ニング (Shortening)\n• 마가린 (Margarine)\n• 유화제 (Emulsifier / E471)\n• 가공유지 (Processed oils)",
            "Bengali": "⚠️ [কোরিয়া 🇰🇷] সন্দেহজনক উপাদান (Syubhah):\n• 쇼트ニング (শর্টনিং)\n• 유화제 (ইমালসিফায়ার)\n• 가공유지 (প্রক্রিয়াজাত চর্বি)",
            "Chinese": "⚠️ [韩国 🇰🇷] 存疑成分 (Syubhah):\n• 쇼트ニング (起酥油)\n• 마가린 (人造黄油)\n• 유화제 (乳化剂)\n• 가공유지 (加工油脂)"
        },
        "tips": {
            "English": "🛒 [Korea 🇰🇷] Shopping Tips:\n1. Look for '식물성유지' (Vegetable oil).\n2. Ramyun (라면) soups very often contain pork extract.",
            "Bengali": "🛒 [কোরিয়া 🇰🇷] কেনাকাটার টিপস:\n১. প্যাকেটে 식물성유지 লেখা থাকলে নিরাপদ।\n২. রামিয়নের স্যুপে শুকর থাকে কি না দেখুন।",
            "Chinese": "🛒 [韩国 🇰🇷] 购物小贴士:\n1. 认准‘식물성유지 (植物油脂)’标识。\n2. 韩国泡面（라면）汤粉包绝大多数含牛猪肉提取物，须格外小心。"
        },
        "info": {
            "English": "ℹ️ [Korea 🇰🇷] Guide:\n• Take a picture of '원재료명' (Ingredients).",
            "Bengali": "ℹ️ [কোরিয়া 🇰🇷] নির্দেশিকা:\n• উপাদানের তালিকার (원재료명) স্পষ্ট ছবি পাঠান।",
            "Chinese": "ℹ️ [韩国 🇰🇷] 指南:\n• 请清晰拍摄包装背面的‘원재료명’（原材料名）部分。"
        }
    },
    "Bangladesh": {
        "title": "BD HALAL FOOD CHECKER 🇧🇩",
        "advice_app": {
            "English": "In Bangladesh, prioritize products with Islamic Foundation Bangladesh & BSTI Halal certificates.",
            "Bengali": "বাংলাদেশে শতভাগ নিশ্চয়তার জন্য ইসলামিক ফাউন্ডেশন ও বিএসটিআই হালাল লোগো অনুসরণ করুন।",
            "Chinese": "在孟加拉国，请优先认准孟加拉伊斯兰基金会或BSTI清真认证标志。"
        },
        "haram": {
            "English": "🚫 [Bangladesh 🇧🇩] Haram Ingredients:\n• Pork, Bacon, Lard (in imported snacks)\n• Non-halal Gelatin\n• Carmine (E120)\n• Alcohol, Rum flavoring",
            "Bengali": "🚫 [বাংলাদেশ 🇧🇩] নিশ্চিত হারাম উপাদান:\n• পর্ক, বেকন, হ্যাম, লার্ড (আমদানিকৃত খাদ্যে)\n• অ-হালাল প্রাণিজ জেলাটিন\n• অ্যালকোহল, রাম এসেন্স\n• ক্যারমাইন / কোচিনিল (E120)",
            "Chinese": "🚫 [孟加拉 🇧🇩] 严禁成分 (Haram):\n• 进口零食中的猪肉、猪油成分\n• 非清真明胶 (Gelatin)\n• 胭脂红 (E120)\n• 酒精、朗姆酒香精"
        },
        "syubhah": {
            "English": "⚠️ [Bangladesh 🇧🇩] Syubhah (Doubtful):\n• Emulsifiers (E471, E472)\n• Bakery Shortening & Margarine\n• Cheese Rennet & Whey powder",
            "Bengali": "⚠️ [বাংলাদেশ 🇧🇩] সন্দেহজনক উপাদান (Syubhah):\n• ইমালসিফায়ার (E471, E472)\n• শর্টনিং ও মার্জারিন\n• পনিরের রেনেট ও হুই পাউডার",
            "Chinese": "⚠️ [孟加拉 🇧🇩] 存疑成分 (Syubhah):\n• 乳化剂 (E471, E472)\n• 烘焙起酥油与人造奶油\n• 奶酪凝乳酶与乳清粉"
        },
        "tips": {
            "English": "🛒 [Bangladesh 🇧🇩] Shopping Tips:\n1. Check imported chocolates and jellies for Gelatin sources.\n2. Look for Islamic Foundation Halal logo.",
            "Bengali": "🛒 [বাংলাদেশ 🇧🇩] কেনাকাটার টিপস:\n১. আমদানিকৃত চকলেট ও জেলিতে জেলাটিনের উৎস দেখুন।\n২. ইসলামিক ফাউন্ডেশনের হালাল লোগো দেখে নিন।",
            "Chinese": "🛒 [孟加拉 🇧🇩] 购物小贴士:\n1. 进口巧克力和果冻需仔细核对明胶来源。\n2. 认准本地伊斯兰基金会清真认证。"
        },
        "info": {
            "English": "ℹ️ [Bangladesh 🇧🇩] Guide:\n• Take a picture of 'উপাদান' or 'Ingredients'.",
            "Bengali": "ℹ️ [বাংলাদেশ 🇧🇩] নির্দেশিকা:\n• মোড়কের 'উপাদান' বা 'Ingredients' অংশের সোজা ছবি তুলুন।",
            "Chinese": "ℹ️ [孟加拉 🇧🇩] 指南:\n• 请清晰拍摄包装上的‘উপাদান’或‘Ingredients’配料部分。"
        }
    }
}

COUNTRY_RULES = {
    "Indonesia": {
        "title": "ID HALAL FOOD CHECKER 🇮🇩",
        "haram_prompt": """
        TARGET REGION: INDONESIA (BPJPH & LPPOM MUI Standards).
        Header: Komposisi.
        - HARAM: Babi, Daging Babi (Pork), Lemak Babi (Lard), Porcine, Ham, Bacon, Gelatin Babi, Saren, Marus, Didih (Animal blood), Alkohol, Minuman Beralkohol, Angciu (Red cooking wine), Arak Masak, Rum, Mirin beralkohol, Non-Halal certified chicken/beef.
        - SYUBHAH: Pengemulsi (Emulsifier / E471/E472 - unless specified nabati), Mentega Putih (Shortening), Margarin, Gelatin (unless bovine halal/fish), Kolagen, Perisa (Flavors with alcohol solvent).
        - HALAL: Minyak Nabati, Minyak Kelapa Sawit, Kedelai, Tepung Terigu, Gula, Garam.
        """
    },
    "Japan": {
        "title": "JP HALAL FOOD CHECKER 🇯🇵",
        "haram_prompt": """
        TARGET REGION: JAPAN.
        Header: 原材料名.
        - HARAM: 豚肉 (Pork), 豚脂/ラード (Lard), 豚骨 (Pork bone), ポークエキス, 豚ゼラチン, ハム, ベーコン, 牛肉/牛脂/鶏肉 (unless Halal marked), 動物性油脂, 混合油脂, コンソメ, ブイヨン, アルコール (Alcohol), 洋酒, 酒精, 酒, 料理酒, 清酒, 味醂 (Mirin), 発酵調味料 (with alcohol).
        - SYUBHAH: ショートニング (Shortening), マーガリン (Margarine), ファットスプレッド, 乳化剤 (Emulsifier / E471/E472), 加工油脂, 食用油脂, コラーゲン, ゼラチン (Gelatin - unless fish-derived), アミノ酸等 (if animal origin unspecified), 酵素 (Enzymes), イーストフード, 骨炭.
        - HALAL: 植物油脂, 大豆油, 菜種油, 小麦粉, 砂糖, 食塩, 植物性タンパク, 野菜エキス, 海藻エキス, 魚介エキス.
        """
    },
    "China": {
        "title": "CN HALAL FOOD CHECKER 🇨🇳",
        "haram_prompt": """
        TARGET REGION: CHINA & CHINESE PACKAGED FOODS.
        Header: 配料 / 配料表.
        - HARAM: 猪肉, 猪油, 猪脂, 猪皮, 猪血, 培根, 火腿, 动物油脂, 鸡精, 浓汤宝, 料酒 (Chinese cooking wine), 黄酒, 白酒, 花雕酒, 米酒, 食用酒精, 啤酒, 明胶, 阿胶, 鸭血.
        - SYUBHAH: 起酥油, 人造奶油, 人造黄油, 乳化剂, 酶制剂, 食用香精.
        """
    },
    "Korea": {
        "title": "KR HALAL FOOD CHECKER 🇰🇷",
        "haram_prompt": """
        TARGET REGION: SOUTH KOREA.
        Header: 원재료명.
        - HARAM: 돼지고기, 돈지/라드, 햄, 베이컨, 젤라틴 (돼지), 쇠고기/닭고기 (unless Halal marked), 맛술 (Cooking wine), 청주, 주정 (Alcohol), 양조주, 동물성유지.
        - SYUBHAH: 쇼트ニング, 마가린, 유화제 (E471), 가공유지, 콜라ゲン, 효소제제.
        """
    },
    "USA": {
        "title": "US HALAL FOOD CHECKER 🇺🇸",
        "haram_prompt": """
        TARGET REGION: USA (FDA Standard).
        Header: Ingredients.
        - HARAM: Pork, Bacon, Ham, Lard, Pork Gelatin, Non-Zabiha Beef/Chicken extracts, Carmine/Cochineal extract (E120), Pure Vanilla Extract (with alcohol), Brewer's yeast, Alcohol, Wine, Rum flavoring.
        - SYUBHAH: Gelatin, Mono and diglycerides (E471), Polysorbate 60/80, Whey powder, Enzymes, Natural/Artificial Flavors.
        """
    },
    "Bangladesh": {
        "title": "BD HALAL FOOD CHECKER 🇧🇩",
        "haram_prompt": """
        TARGET REGION: BANGLADESH.
        Header: উপাদান, উপাদানসমূহ, Ingredients.
        - HARAM: শুয়োরের মাংস/চর্বি (Pork, Lard), অ-হালাল প্রাণিজ জেলাটিন, ক্যারমাইন/E120, অ্যালকোহল, রাম এসেন্স.
        - SYUBHAH: ইমালসিফায়ার (E471, E472), শর্টনিং, মার্জারিন, পনিরের রেনেট, হুই পাউডার.
        """
    }
}

# ============================================================================
# ৫. কুইক রিপ্লাই এবং Flex Message জেনারেটর
# ============================================================================
def get_country_selection_menu():
    return QuickReply(items=[
        QuickReplyItem(action=MessageAction(label="🇮🇩 Indonesia", text="Country: Indonesia")),
        QuickReplyItem(action=MessageAction(label="🇯🇵 Japan", text="Country: Japan")),
        QuickReplyItem(action=MessageAction(label="🇺🇸 USA", text="Country: USA")),
        QuickReplyItem(action=MessageAction(label="🇨🇳 China", text="Country: China")),
        QuickReplyItem(action=MessageAction(label="🇰🇷 Korea", text="Country: Korea")),
        QuickReplyItem(action=MessageAction(label="🇧🇩 Bangladesh", text="Country: Bangladesh"))
    ])

def get_language_selection_menu():
    return QuickReply(items=[
        QuickReplyItem(action=MessageAction(label="🇬🇧 English", text="Set: English")),
        QuickReplyItem(action=MessageAction(label="🇮🇩 Indonesia", text="Set: Indonesian")),
        QuickReplyItem(action=MessageAction(label="🇯🇵 日本語", text="Set: Japanese")),
        QuickReplyItem(action=MessageAction(label="🇨🇳 简体中文", text="Set: Chinese")),
        QuickReplyItem(action=MessageAction(label="🇧🇩 বাংলা", text="Set: Bengali")),
        QuickReplyItem(action=MessageAction(label="🇸🇦 العربية", text="Set: Arabic"))
    ])

def get_direct_camera_quick_reply(lang="English"):
    label = I18N.get(lang, I18N["English"])["cam_btn"]
    return QuickReply(items=[
        QuickReplyItem(action=CameraAction(label=label))
    ])

def get_post_scan_quick_reply(lang="English"):
    lang_data = I18N.get(lang, I18N["English"])
    return QuickReply(items=[
        QuickReplyItem(action=MessageAction(label=lang_data["btn_feedback_ok"], text="feedback_accurate")),
        QuickReplyItem(action=MessageAction(label=lang_data["btn_feedback_doubt"], text="feedback_doubt")),
        QuickReplyItem(action=MessageAction(label=lang_data["btn_share"], text="share_last_result")),
        QuickReplyItem(action=MessageAction(label=lang_data["btn_explain"], text="explain_last_scan")),
        QuickReplyItem(action=MessageAction(label=lang_data["btn_history"], text="show_history")),
        QuickReplyItem(action=CameraAction(label=lang_data["cam_btn"]))
    ])

def get_localized_country_text(country, category, lang="English"):
    country_data = COUNTRY_DETAILS.get(country, COUNTRY_DETAILS["Japan"])
    cat_dict = country_data.get(category, {})
    if isinstance(cat_dict, dict):
        return cat_dict.get(lang, cat_dict.get("English", cat_dict.get("Bengali", "")))
    return str(cat_dict)

def create_halal_flex_card(product_name, company_name, status, reason, items_text, alternatives_text, allergens_text, lang="English", country="Japan", item_no=None, total_count=None):
    lang_data = I18N.get(lang, I18N["English"])
    country_info = COUNTRY_RULES.get(country, COUNTRY_RULES["Japan"])
    country_header = country_info["title"]
    advice_text = get_localized_country_text(country, "advice_app", lang)

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

    body_contents = []

    # কাউন্টার তথ্য
    if item_no is not None and total_count is not None:
        counter_label = lang_data["counter_text"].format(total=total_count, item_no=item_no)
        body_contents.append({
            "type": "box",
            "layout": "vertical",
            "paddingBottom": "6px",
            "contents": [
                {
                    "type": "text",
                    "text": counter_label,
                    "weight": "bold",
                    "size": "xxs",
                    "color": "#757575"
                }
            ]
        })

    # প্রোডাক্ট ও কোম্পানি নাম
    if product_name or company_name:
        prod_display = product_name if product_name else "Food Item"
        comp_display = f" | {company_name}" if company_name else ""
        body_contents.append({
            "type": "box",
            "layout": "vertical",
            "paddingBottom": "10px",
            "contents": [
                {
                    "type": "text",
                    "text": f"📦 {prod_display}{comp_display}",
                    "weight": "bold",
                    "size": "sm",
                    "color": "#111111",
                    "wrap": True
                }
            ]
        })

    # স্ট্যাটাস ও কারণ
    body_contents.append({
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
    })

    # শনাক্ত উপাদান
    body_contents.append({
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
    })

    # অ্যালার্জি ওয়ার্নিং বক্স
    if allergens_text and allergens_text.strip():
        body_contents.append({
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#FFF8E1",
            "cornerRadius": "6px",
            "paddingAll": "10px",
            "margin": "md",
            "contents": [
                {
                    "type": "text",
                    "text": lang_data["label_allergens"],
                    "weight": "bold",
                    "size": "xxs",
                    "color": "#F57F17"
                },
                {
                    "type": "text",
                    "text": allergens_text,
                    "size": "xxs",
                    "color": "#E65100",
                    "wrap": True,
                    "margin": "xs"
                }
            ]
        })

    # হালাল বিকল্প সাজেশন
    if alternatives_text and alternatives_text.strip():
        body_contents.append({
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#E0F2F1",
            "cornerRadius": "6px",
            "paddingAll": "10px",
            "margin": "md",
            "contents": [
                {
                    "type": "text",
                    "text": lang_data["label_alternatives"],
                    "weight": "bold",
                    "size": "xxs",
                    "color": "#00695C"
                },
                {
                    "type": "text",
                    "text": alternatives_text,
                    "size": "xxs",
                    "color": "#004D40",
                    "wrap": True,
                    "margin": "xs"
                }
            ]
        })

    # হাদিস ও পরামর্শ
    body_contents.extend([
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
    ])

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
            "contents": body_contents
        }
    }
    return FlexContainer.from_json(json.dumps(flex_json))

# ============================================================================
# ৬. কোর ফ্লাস্ক মেসেজ হ্যান্ডলার
# ============================================================================
@app.route("/", methods=['GET'])
def index():
    return f"Global Halal Food Checker Engine Active. DB Index count: {len(LOCAL_DB)}"

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
    global user_languages, user_countries, user_last_scans
    user_id = event.source.user_id
    raw_text = event.message.text.strip()
    text = raw_text.lower()

    current_lang = user_languages.get(user_id, "English")
    current_country = user_countries.get(user_id, "Japan")

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # ১. ফিডব্যাক বাটন (সঠিক ও সংশয় হ্যান্ডলিং)
        if text in ["feedback_accurate", "নির্ভুল তথ্য", "accurate info", "🎯 নির্ভুল তথ্য", "🎯 accurate info"]:
            last_item = user_last_scans.get(user_id, {})
            log_user_feedback(user_id, last_item.get('product_name', 'Unknown'), 'ACCURATE')
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=I18N[current_lang]["feedback_ok_msg"])]
                )
            )
            return

        if text in ["feedback_doubt", "সংশয়", "report", "রিভিউ", "🚩 সংশয় / রিভিউ", "🚩 report / review"]:
            last_item = user_last_scans.get(user_id, {})
            log_user_feedback(user_id, last_item.get('product_name', 'Unknown'), 'DOUBTFUL_REPORT')
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=I18N[current_lang]["feedback_doubt_msg"])]
                )
            )
            return

        # ২. শেয়ার রেজাল্ট (এক ক্লিকে রেজাল্ট টেক্সট কপি/ফরোয়ার্ডের উপযোগী মেসেজ)
        if text in ["share_last_result", "share", "শেয়ার", "bagikan", "分享"]:
            last_item = user_last_scans.get(user_id)
            if last_item:
                prod = last_item.get('product_name', 'Food Product')
                comp = last_item.get('company_name', '')
                stat = last_item.get('status', 'CHECKED')
                rsn = last_item.get('reason', '')
                share_txt = f"📦 {prod} ({comp})\n🏷️ Status: {stat}\n📌 Observation: {rsn}\n\n✅ Checked via Global Halal Food Checker Bot."
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=share_txt)]
                    )
                )
            else:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=I18N[current_lang]["history_empty"])]
                    )
                )
            return

        # ৩. রেডিমেড হালাল ব্র্যান্ড গাইড
        if any(k in text for k in ["safe brand", "ব্র্যান্ড", "brand", "brand guide", "gudang brand", "品牌"]):
            guide_txt = SAFE_BRAND_GUIDES.get(current_country, SAFE_BRAND_GUIDES["Japan"])
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=guide_txt)]
                )
            )
            return

        # ৪. হিস্ট্রি তালিকা প্রদর্শন (SQLite ডাটাবেস থেকে)
        if text in ["show_history", "history", "হিস্ট্রি", "ইতিহাস", "履歴", "历史", "riwayat", "سجل"]:
            history_list = get_user_history_list(user_id, limit=10)
            if not history_list:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=I18N[current_lang]["history_empty"])]
                    )
                )
                return

            total_count = get_user_total_scans(user_id)
            response_msg = I18N[current_lang]["history_title"].format(count=total_count)
            for idx, item in enumerate(history_list, 1):
                prod = item.get("product_name", "Food Item")
                status = item.get("status", "VERIFY")
                response_msg += f"{idx}. 📦 {prod} [{status}]\n"

            response_msg += I18N[current_lang]["history_hint"]
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=response_msg)]
                )
            )
            return

        # ৫. নির্দিষ্ট নম্বরের আইটেম পুনরায় কার্ড আকারে দেখা (1, 2, 3...)
        if raw_text.isdigit():
            target_idx = int(raw_text)
            history_list = get_user_history_list(user_id, limit=10)
            if 1 <= target_idx <= len(history_list):
                saved_item = history_list[target_idx - 1]
                total_count = get_user_total_scans(user_id)
                flex_container = create_halal_flex_card(
                    saved_item.get("product_name", ""),
                    saved_item.get("company_name", ""),
                    saved_item.get("status", "SYUBHAH"),
                    saved_item.get("reason", ""),
                    saved_item.get("items", ""),
                    saved_item.get("alternatives", ""),
                    saved_item.get("allergens", ""),
                    current_lang,
                    saved_item.get("country", current_country),
                    item_no=target_idx,
                    total_count=total_count
                )
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[
                            FlexMessage(
                                alt_text=f"History #{target_idx}: {saved_item.get('status')}",
                                contents=flex_container,
                                quick_reply=get_post_scan_quick_reply(current_lang)
                            )
                        ]
                    )
                )
                return

        # ৬. শেষ স্ক্যানের উপাদানের ব্যাখ্যা
        if text in ["explain_last_scan", "explain", "বিস্তারিত", "ব্যাখ্যা", "解説", "详细", "jelaskan"]:
            last_scan = user_last_scans.get(user_id)
            if last_scan:
                prod = last_scan.get('product_name', 'Item')
                comp = last_scan.get('company_name', 'Brand')
                explanation = f"🔍 [{prod} ({comp})]:\n\n"
                explanation += f"📊 Status: {last_scan.get('status')}\n\n"
                explanation += f"📌 Reason: {last_scan.get('reason')}\n\n"
                explanation += f"🏷️ Ingredients: {last_scan.get('items')}\n\n"
                if last_scan.get('allergens'):
                    explanation += f"⚠️ Allergens: {last_scan.get('allergens')}\n\n"
                if last_scan.get('alternatives'):
                    explanation += f"💡 Alternatives: {last_scan.get('alternatives')}\n\n"
                line_bot_api.reply_message(
                    ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=explanation)])
                )
            else:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=I18N[current_lang]["history_empty"])]
                    )
                )
            return

        # ৭. দেশ নির্বাচন ও স্বয়ংক্রিয় ভাষা রূপান্তর (Indonesia সহ)
        if raw_text.startswith("Country:"):
            chosen = raw_text.replace("Country:", "").strip().lower()
            if "indonesia" in chosen:
                user_countries[user_id] = "Indonesia"
                user_languages[user_id] = "Indonesian"
            elif "china" in chosen:
                user_countries[user_id] = "China"
                user_languages[user_id] = "Chinese"
            elif "korea" in chosen or "한국" in chosen:
                user_countries[user_id] = "Korea"
                user_languages[user_id] = "English"
            elif "usa" in chosen or "america" in chosen:
                user_countries[user_id] = "USA"
                user_languages[user_id] = "English"
            elif "bangladesh" in chosen or "bd" in chosen:
                user_countries[user_id] = "Bangladesh"
                user_languages[user_id] = "Bengali"
            else:
                user_countries[user_id] = "Japan"
                user_languages[user_id] = "Japanese"

            current_country = user_countries[user_id]
            current_lang = user_languages[user_id]

            msg = I18N[current_lang]["country_selected"].format(country=current_country)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=msg, quick_reply=get_language_selection_menu())]
                )
            )
            return

        # ৮. ভাষা নির্বাচন ওভাররাইড
        if raw_text.startswith("Set:"):
            target = raw_text.replace("Set:", "").strip().lower()
            if "english" in target:
                user_languages[user_id] = "English"
            elif "chinese" in target or "中文" in target:
                user_languages[user_id] = "Chinese"
            elif "japan" in target or "日本語" in target:
                user_languages[user_id] = "Japanese"
            elif "indonesia" in target:
                user_languages[user_id] = "Indonesian"
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

        # রিচ মেনু বাটন C: হারাম উপাদান
        if any(k in text for k in ["haram", "হারাম", "ハラーム", "非清真"]):
            country_haram_text = get_localized_country_text(current_country, "haram", current_lang)
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=country_haram_text)])
            )
            return

        # রিচ মেনু বাটন D: সন্দেহজনক উপাদান
        if any(k in text for k in ["syubhah", "doubtful", "সন্দেহ", "シュブハ", "存疑"]):
            country_syubhah_text = get_localized_country_text(current_country, "syubhah", current_lang)
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=country_syubhah_text)])
            )
            return

        # রিচ মেনু বাটন E: শপিং টিপস
        if any(k in text for k in ["tip", "কেনাকাটা", "tips", "贴士"]):
            country_tips_text = get_localized_country_text(current_country, "tips", current_lang)
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=country_tips_text)])
            )
            return

        # রিচ মেনু বাটন F: গাইড ও তথ্য
        if any(k in text for k in ["info", "guide", "সাহায্য", "তথ্য", "指南"]):
            country_info_text = get_localized_country_text(current_country, "info", current_lang)
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=country_info_text)])
            )
            return

        # রিচ মেনু বাটন B: দেশ ও ভাষা নির্বাচন
        if any(k in text for k in ["language", "ভাষা", "bahasa", "言語", "语言", "country", "দেশ", "国家"]):
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
            return

        # রিচ মেনু বাটন A: ছবি তোলা
        if any(k in text for k in ["take a photo", "camera", "ক্যামেরা", "scan", "ছবি", "相机", "拍照"]):
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
            return

        # ডিফল্ট রিপ্লাই
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

# ============================================================================
# ৭. Gemini Flash Vision Inference Engine
# ============================================================================
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
            "maxOutputTokens": 850,
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

# ============================================================================
# ৮. ইমেজ প্রসেসিং ও ইন্সপেকশন পাইপলাইন
# ============================================================================
@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event):
    global user_languages, user_countries, user_last_scans
    user_id = event.source.user_id
    selected_lang = user_languages.get(user_id, "English")
    selected_country = user_countries.get(user_id, "Japan")

    try:
        with ApiClient(configuration) as api_client:
            blob_api = MessagingApiBlob(api_client)
            raw_bytes = blob_api.get_message_content(event.message.id)

        # ইমেজ সাইজ অপটিমাইজেশন (মেমরি ক্র্যাশ প্রতিরোধে)
        img = Image.open(io.BytesIO(raw_bytes))
        img.thumbnail((500, 500))
        out_buf = io.BytesIO()
        img.convert('RGB').save(out_buf, format="JPEG", quality=60, optimize=True)
        image_b64 = base64.b64encode(out_buf.getvalue()).decode("utf-8")

        del raw_bytes, img, out_buf
        gc.collect()

        country_context = COUNTRY_RULES.get(selected_country, COUNTRY_RULES["Japan"])["haram_prompt"]

        csv_db_summary = f"""
        Verified Dataset References loaded ({len(LOCAL_DB)} indices):
        - Haram sample keywords: {', '.join(CSV_HARAM_KEYWORDS[:40])}
        - High-Risk Syubhah/Verify additives & E-numbers sample: {', '.join(CSV_VERIFY_KEYWORDS[:40])}
        """

        prompt = f"""
        Act as an expert Global Halal Food Inspector specialized in packaged foods for: {selected_country}.
        
        Rules & Standards for {selected_country}:
        {country_context}

        {csv_db_summary}

        Inspection Procedure:
        1. Check image clarity: If the image is blurry, glaring, unreadable, or not a food packaging label, set 'is_blurry': true.
        2. Identify Product Name, Manufacturer / Brand name, and Barcode digits (if visible).
        3. Accurately detect and transcribe ingredients from packaging.
        4. Detect Common Allergens (Milk, Egg, Peanut, Tree Nuts, Wheat/Gluten, Soy, Fish, Crustaceans).
        5. Match ingredients with Dataset & local regulations:
           - Check Haram items (pork derivatives, non-halal meat extracts, cooking alcohol/sake/mirin/liaojiu/cheongju/angciu, carmine/E120, animal blood/saren, animal fats).
           - Check Syubhah/Doubtful components (shortening, emulsifiers E471/E472, unspecified animal gelatin, collagen, enzymes, yeast food).
        6. Verdict Hierarchy: If ANY Haram found -> 'HARAM'. Else if ANY Syubhah found -> 'SYUBHAH'. Otherwise -> 'HALAL'.
        7. Smart Halal Alternative: If status is 'HARAM' or 'SYUBHAH', suggest 1-2 widely available Halal alternative brands/items in {selected_country}. If HALAL, leave 'alternatives' empty.

        CRITICAL LOCALIZATION RULE:
        All explanation, reason, items description, allergens, and alternatives MUST BE STRICTLY WRITTEN IN: {selected_lang}.

        You MUST respond ONLY with a valid JSON matching this schema:
        {{
            "is_blurry": false,
            "barcode": "Detected barcode digits or empty string",
            "product_name": "Product name written in {selected_lang}",
            "company_name": "Manufacturer/Brand name",
            "status": "HALAL" or "HARAM" or "SYUBHAH",
            "reason": "Analysis strictly written in {selected_lang}",
            "items": "Detected specific key ingredients strictly written in {selected_lang}",
            "allergens": "Detected allergens strictly written in {selected_lang} (or empty string if none)",
            "alternatives": "Suggested halal alternatives strictly written in {selected_lang}"
        }}
        """

        result_raw = call_gemini_vision(prompt, image_b64)
        result_json = json.loads(result_raw)

        # ঝাপসা ছবি চেক
        if result_json.get("is_blurry", False):
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(
                            text=I18N[selected_lang]["blurry_error"],
                            quick_reply=get_direct_camera_quick_reply(selected_lang)
                        )]
                    )
                )
            return

        barcode = result_json.get("barcode", "")
        
        # বারকোড লোকাল ক্যাশ চেক (ইনস্ট্যান্ট রেসপন্স)
        cached_result = get_cached_barcode(barcode)
        if cached_result:
            product_name = cached_result.get("product_name")
            company_name = cached_result.get("company_name")
            status = cached_result.get("status")
            reason = cached_result.get("reason")
            items = cached_result.get("items")
            allergens = cached_result.get("allergens")
            alternatives = cached_result.get("alternatives")
        else:
            product_name = result_json.get("product_name", "")
            company_name = result_json.get("company_name", "")
            status = result_json.get("status", "SYUBHAH")
            reason = result_json.get("reason", "")
            items = result_json.get("items", "")
            allergens = result_json.get("allergens", "")
            alternatives = result_json.get("alternatives", "")

            # নতুন বারকোড ক্যাশ সংরক্ষণ
            if barcode:
                save_barcode_cache(barcode, result_json, selected_country)

        # ডাটাবেসে স্ক্যান হিস্ট্রি সংরক্ষণ
        scan_record = {
            "product_name": product_name,
            "company_name": company_name,
            "status": status,
            "reason": reason,
            "items": items,
            "allergens": allergens,
            "alternatives": alternatives
        }
        save_scan_history(user_id, scan_record, selected_country, barcode)

        user_last_scans[user_id] = scan_record
        total_scans = get_user_total_scans(user_id)

        flex_container = create_halal_flex_card(
            product_name, company_name, status, reason, items, alternatives, allergens,
            selected_lang, selected_country, item_no=total_scans, total_count=total_scans
        )
        reply_payload = [
            FlexMessage(
                alt_text=f"Check Result: {status}",
                contents=flex_container,
                quick_reply=get_post_scan_quick_reply(selected_lang)
            )
        ]

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
