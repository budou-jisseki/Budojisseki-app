import json
import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import google.auth
import os
import configparser
from datetime import datetime, timedelta
import socket
import qrcode
from io import BytesIO
import jpholiday

# ==========================================
# 設定とファイルパス
# ==========================================
INIT_FILE = 'config.ini'

JSON_KEY_FILE = 'secret.json'
SPREADSHEET_KEY = '1JQe44mjZAUo2oAyVANerXpgXjeM5z_XvJZIjB_TrN5U'
MASTER_SHEET_NAME = '利用者マスタ'

COLUMNS_ADULT = [
    '記載日', '名前', '受給者証番号', '出欠状況',
    '開始時間', '終了時間', '算定時間数',
    '送迎往路', '送迎復路', '食事提供', '食事量',
    '体調', '作業の取り組み', '精神や情緒', '特別な支援', '特記事項',
    '遅刻・早退', '計画', '都合', '計画開始時刻', '計画終了時刻',
    '中抜け開始時刻', '中抜け終了時刻'
]

COLUMNS_CHILD = [
    '記載日', '名前', '受給者証番号', '出欠状況',
    '開始時間', '終了時間', '算定時間数',
    '送迎往路', '送迎復路', '食事提供', '食事量',
    '体調', '活動の様子', '機嫌・情緒', '特別な支援', '特記事項',
    '遅刻・早退', '計画', '都合', '計画開始時刻', '計画終了時刻',
    '中抜け開始時刻', '中抜け終了時刻'
]

CONDITION_OPTS = ['良好', '普通', '不良', '服薬忘れあり', 'その他']
ENGAGEMENT_OPTS = ['集中して取り組めた', '声かけにより取り組めた', '休みがちだった', '参加できなかった', 'その他']
MENTAL_OPTS = ['安定している', '少し不安定', '気分の落ち込みあり', 'イライラしていた', 'その他']
SUPPORT_OPTS = ['通常支援のみ', '個別面談を実施した', '体調不良による静養対応', '他機関との連絡調整', 'その他']

CONDITION_OPTS_CHILD = ['良好', '普通', '不良', 'その他']
ACTIVITY_OPTS = ['意欲的に参加できた', '声かけにより参加できた', '落ち着きがなかった', '参加できなかった', 'その他']
MOOD_OPTS = ['安定している', '少し不安定', '興奮気味だった', '機嫌が悪かった', 'その他']
SUPPORT_OPTS_CHILD = ['通常支援のみ', '個別対応を実施した', 'クールダウンを行った', '保護者と連携した', 'その他']

ABSENT_REASON_OPTS = ['体調不良', '通院', '家庭の事情', '無断欠席', 'その他']

SPINNER_HTML = """
<style>
@keyframes custom-spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
}
.custom-spinner {
    border: 4px solid rgba(33, 150, 243, 0.2);
    width: 24px; height: 24px;
    border-radius: 50%;
    border-left-color: #2196F3;
    animation: custom-spin 1s linear infinite;
    margin-right: 15px;
}
.custom-spinner-box {
    padding: 15px; background-color: #e8f4f8; 
    border-left: 5px solid #2196F3; border-radius: 5px; 
    display: flex; align-items: center; margin-bottom: 15px;
}
</style>
<div class="custom-spinner-box">
    <div class="custom-spinner"></div>
    <strong style="color: #0c5460;">データをスプレッドシートに保存しています、このまま数秒お待ちください...</strong>
</div>
"""

st.set_page_config(page_title="実績入力システム", page_icon="📝", layout="centered")

# ==========================================
# 状態管理の初期化
# ==========================================
if "logged_in" not in st.session_state: st.session_state.logged_in = False
if "role" not in st.session_state: st.session_state.role = ""
if "success_msg" not in st.session_state: st.session_state.success_msg = None
if 'remarks_new' not in st.session_state: st.session_state.remarks_new = ""
if 'remarks_batch' not in st.session_state: st.session_state.remarks_batch = ""
if "service_type" not in st.session_state: st.session_state.service_type = "就労継続支援B型"
if "show_all_services" not in st.session_state: st.session_state.show_all_services = False # 🚨 ステルス機能用フラグ

# ==========================================
# テーマカラーの動的設定
# ==========================================
if st.session_state.service_type == "就労継続支援B型":
    bg_color = "#f0f8ff"
    accent_color = "#1976d2"
elif st.session_state.service_type == "生活介護":
    bg_color = "#fff5f0"
    accent_color = "#e65100"
elif st.session_state.service_type == "児童発達支援":
    bg_color = "#f1f8e9"
    accent_color = "#33691e"
elif st.session_state.service_type == "放課後等デイサービス":
    bg_color = "#fce4ec"
    accent_color = "#c2185b"

# ==========================================
# サービス共通の項目変数セットアップ
# ==========================================
is_child_service = st.session_state.service_type in ["児童発達支援", "放課後等デイサービス"]
current_columns = COLUMNS_CHILD if is_child_service else COLUMNS_ADULT

if is_child_service:
    cond_opts = CONDITION_OPTS_CHILD
    eng_label = "活動の様子"
    eng_opts = ACTIVITY_OPTS
    men_label = "機嫌・情緒"
    men_opts = MOOD_OPTS
    sup_opts = SUPPORT_OPTS_CHILD
else:
    cond_opts = CONDITION_OPTS
    eng_label = "作業の取り組み"
    eng_opts = ENGAGEMENT_OPTS
    men_label = "精神や情緒"
    men_opts = MENTAL_OPTS
    sup_opts = SUPPORT_OPTS

# ==========================================
# デザイン・UIカスタマイズ
# ==========================================
st.markdown(f"""
<style>
    header {{visibility: hidden !important;}}
    footer {{visibility: hidden !important;}}

    .stApp {{
        overflow-x: hidden !important;
        background-color: {bg_color} !important;
    }}
    .block-container {{ 
        padding-top: 2.5rem !important; 
        padding-bottom: 1.5rem !important; 
        padding-left: 2rem !important; 
        padding-right: 2rem !important; 
        max-width: 800px !important; 
        margin: 0 auto !important;
        box-sizing: border-box !important;
        border-left: 8px solid {accent_color} !important;
        background-color: rgba(255, 255, 255, 0.85) !important;
        border-radius: 8px !important; 
        box-shadow: 0 4px 12px rgba(0,0,0,0.05) !important; 
    }}
    .main-title {{ font-size: 1.5rem !important; font-weight: bold; margin-bottom: 0.5rem; color: {accent_color} !important; }}
    .stButton > button, .stFormSubmitButton > button {{
        border-radius: 8px !important; font-weight: bold !important;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1) !important; transition: all 0.2s ease !important; border: none !important;
    }}
    button[kind="primary"] {{ background-color: {accent_color} !important; color: white !important; }}
    
    input, select, textarea {{ 
        font-size: 16px !important; 
        width: 100% !important;
        max-width: 100% !important;
        box-sizing: border-box !important;
    }}
    div[data-baseweb="input"], div[data-baseweb="select"] {{
        max-width: 100% !important;
    }}
    
    div[data-baseweb="select"] > div {{
        font-size: 1.15rem !important;
        font-weight: bold !important;
        color: {accent_color} !important;
    }}

    div[role="radiogroup"] {{
        flex-wrap: wrap;
        gap: 10px;
    }}

    @media (max-width: 768px) {{
        .block-container {{
            max-width: 100vw !important; 
            border-radius: 0 !important; 
            box-shadow: none !important;
            padding-left: 1rem !important;
            padding-right: 1rem !important;
        }}
        .main-title {{ font-size: 1.3rem !important; }}
        div[data-testid="stDataFrame"] {{ overflow-x: auto !important; width: 100% !important; }}
    }}
</style>
""", unsafe_allow_html=True)

# ==========================================
# 補助関数群
# ==========================================
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def generate_qr(url):
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#2c3e50", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def load_client_master(client):
    client_dict = {'就労継続支援B型': {}, '生活介護': {}, '児童発達支援': {}, '放課後等デイサービス': {}}
    if client is None:
        return client_dict
    try:
        sheet = client.open_by_key(SPREADSHEET_KEY).worksheet(MASTER_SHEET_NAME)
        records = sheet.get_all_records()
        
        if records:
            headers = list(records[0].keys())
            if '就労／生活' not in headers and '就労/生活' not in headers:
                st.warning(f"スプレッドシートの1行目に「就労／生活」という列が見当たりません、現在の列名: {', '.join(headers)}")
                
        for row in records:
            name = str(row.get('利用者名', '')).strip()
            num = str(row.get('受給者証番号', '')).strip()
            category = str(row.get('就労／生活', row.get('就労/生活', ''))).strip()
            
            if name:
                if category == '46':
                    client_dict['就労継続支援B型'][name] = num
                elif category == '22':
                    client_dict['生活介護'][name] = num
                elif category == '11':
                    client_dict['児童発達支援'][name] = num
                elif category == '12':
                    client_dict['放課後等デイサービス'][name] = num
    except Exception as e:
        if 'WorksheetNotFound' in str(type(e)):
            try:
                spreadsheet = client.open_by_key(SPREADSHEET_KEY)
                new_sheet = spreadsheet.add_worksheet(title=MASTER_SHEET_NAME, rows="100", cols="3")
                new_sheet.append_row(['利用者名', '受給者証番号', '就労／生活'])
                st.warning(f"スプレッドシートに「{MASTER_SHEET_NAME}」シートを新しく作成しました")
            except Exception:
                pass
    return client_dict

def load_init_settings():
    settings = {
        'start_time': '10:00', 'end_time': '15:00', 
        'am_end_time': '12:00', 'pm_start_time': '13:00', 
        'rest_time_min': '60',
        'SAT_start_time': '10:00',
        'SAT_end_time': '12:00',
        'enable_daily_record': 'True',
        'show_absent_action': 'True',
        'staff_password': '1111',
        'admin_password': '9999',
        'exclude_label_1': '土曜日を除外する',
        'exclude_label_2': '日曜日・祝祭日を除外する'
    }
    config = configparser.ConfigParser()
    if os.path.exists(INIT_FILE):
        config.read(INIT_FILE, encoding='utf-8')
        if 'Settings' in config:
            for key in settings.keys():
                settings[key] = config['Settings'].get(key, settings[key])
    else:
        try:
            config['Settings'] = settings
            with open(INIT_FILE, 'w', encoding='utf-8') as f:
                config.write(f)
        except Exception:
            pass
    return settings

def calc_working_hours(start_str, end_str, n_start_str="", n_end_str=""):
    if not start_str or not end_str:
        return ""
    try:
        start_dt = datetime.strptime(start_str, "%H:%M")
        end_dt = datetime.strptime(end_str, "%H:%M")
        
        diff_min = (end_dt - start_dt).total_seconds() / 60
        
        nakanuke_min = 0
        if n_start_str and n_end_str:
            try:
                n_st_dt = datetime.strptime(n_start_str, "%H:%M")
                n_et_dt = datetime.strptime(n_end_str, "%H:%M")
                nakanuke_min = (n_et_dt - n_st_dt).total_seconds() / 60
                if nakanuke_min < 0:
                    nakanuke_min = 0
            except Exception:
                pass
                
        actual_min = max(0, diff_min - nakanuke_min)
        
        h = int(actual_min // 60)
        m = int(actual_min % 60)
        return f"{h:02d}:{m:02d}"
    except Exception:
        return ""

def is_day_excluded(date_obj, label):
    if not label or label == "なし" or label == "":
        return False
    
    is_mon = date_obj.weekday() == 0
    is_tue = date_obj.weekday() == 1
    is_wed = date_obj.weekday() == 2
    is_thu = date_obj.weekday() == 3
    is_fri = date_obj.weekday() == 4
    is_sat = date_obj.weekday() == 5
    is_sun = date_obj.weekday() == 6
    is_hol = jpholiday.is_holiday(date_obj)

    if "月曜" in label and is_mon: return True
    if "火曜" in label and is_