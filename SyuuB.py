import json
import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import google.auth
import os
import configparser
from datetime import datetime, timedelta, timezone
import socket
import qrcode
from io import BytesIO
import jpholiday
from st_aggrid import AgGrid, GridOptionsBuilder, DataReturnMode, GridUpdateMode, JsCode

# 日本時間（JST）の定義
JST = timezone(timedelta(hours=+9), 'JST')

# ==========================================
# 設定とファイルパス
# ==========================================
INIT_FILE = 'config.ini'
LOGIN_FILE = 'Login.ini'

JSON_KEY_FILE = 'secret.json'
SPREADSHEET_KEY = '1JQe44mjZAUo2oAyVANerXpgXjeM5z_XvJZIjB_TrN5U'
MASTER_SHEET_NAME = '利用者マスタ'
LOG_SHEET_NAME = 'システムログ'

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
    '送迎往路', '送迎復路', '食事提供', '食事量', 'おやつ提供', 'おやつ量',
    '検温', '体調', '排泄', '活動の様子', '機嫌・情緒', '特別な支援', '特記事項',
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
if "user_id" not in st.session_state: st.session_state.user_id = ""
if "success_msg" not in st.session_state: st.session_state.success_msg = None
if 'remarks_new' not in st.session_state: st.session_state.remarks_new = ""
if 'remarks_batch' not in st.session_state: st.session_state.remarks_batch = ""
if "service_type" not in st.session_state: st.session_state.service_type = "就労継続支援B型"
if "show_all_services" not in st.session_state: st.session_state.show_all_services = False
if "last_action_time" not in st.session_state: st.session_state.last_action_time = None
if "last_access_display" not in st.session_state: st.session_state.last_access_display = None

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
    to_opts = ["学校", "自宅", "なし"]
    tr_opts = ["自宅", "なし"]
    exc_opts = ["自立", "声かけ", "一部介助", "全介助", "失敗", "その他"]
else:
    cond_opts = CONDITION_OPTS
    eng_label = "作業の取り組み"
    eng_opts = ENGAGEMENT_OPTS
    men_label = "精神や情緒"
    men_opts = MENTAL_OPTS
    sup_opts = SUPPORT_OPTS
    to_opts = ["〇", "×"]
    tr_opts = ["〇", "×"]
    exc_opts = []

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

def get_client_ip():
    try:
        if hasattr(st, 'context') and hasattr(st.context, 'headers'):
            if "X-Forwarded-For" in st.context.headers:
                return st.context.headers["X-Forwarded-For"].split(",")[0].strip()
            
        from streamlit.web.server.websocket_headers import _get_websocket_headers
        headers = _get_websocket_headers()
        if headers and "X-Forwarded-For" in headers:
            return headers.get("X-Forwarded-For").split(",")[0].strip()
    except Exception:
        pass
    return "取得不可"

def generate_qr(url):
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#2c3e50", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def load_login_settings():
    logins = {
        'Developer': ['0000'],
        'Admin': ['9999'],
        'GeneralStaff': ['1111']
    }
    config = configparser.ConfigParser()
    if os.path.exists(LOGIN_FILE):
        try:
            config.read(LOGIN_FILE, encoding='utf-8')
            if config.has_section('Developer'):
                logins['Developer'] = config.options('Developer')
            if config.has_section('Admin'):
                logins['Admin'] = config.options('Admin')
            if config.has_section('GeneralStaff'):
                logins['GeneralStaff'] = config.options('GeneralStaff')
        except Exception:
            pass
    else:
        try:
            config['Developer'] = {'0000': '開発者'}
            config['Admin'] = {'9999': '管理者デフォルト'}
            config['GeneralStaff'] = {'1111': '一般デフォルト'}
            with open(LOGIN_FILE, 'w', encoding='utf-8') as f:
                config.write(f)
        except Exception:
            pass
    return logins

def get_last_access_info(client):
    if client is None:
        return None
    try:
        sheet = client.open_by_key(SPREADSHEET_KEY).worksheet(LOG_SHEET_NAME)
        records = sheet.get_all_values()
        
        for row in reversed(records):
            if len(row) >= 3 and row[1] != "開発管理者" and row[1] != "権限":
                return f"{row[0]} ({row[1]}による{row[2]})"
    except Exception:
        pass
    return "記録なし"

def write_system_log(client, category, target, count):
    try:
        now = datetime.now(JST)
        elapsed = 0
        if st.session_state.last_action_time:
            if st.session_state.last_action_time.tzinfo is None:
                st.session_state.last_action_time = st.session_state.last_action_time.replace(tzinfo=JST)
            elapsed = int((now - st.session_state.last_action_time).total_seconds())
        st.session_state.last_action_time = now
        
        client_ip = get_client_ip()
        user_id = st.session_state.get('user_id', '不明')
        
        try:
            sheet = client.open_by_key(SPREADSHEET_KEY).worksheet(LOG_SHEET_NAME)
        except Exception:
            spreadsheet = client.open_by_key(SPREADSHEET_KEY)
            sheet = spreadsheet.add_worksheet(title=LOG_SHEET_NAME, rows="100", cols="9")
            sheet.append_row(['タイムスタンプ', '権限', '操作カテゴリ', '処理対象', '処理件数', '操作間隔(秒)', '対象サービス', 'IPアドレス', '操作者ID'])
        
        log_row = [
            now.strftime('%Y-%m-%d %H:%M:%S'),
            st.session_state.get('role', '不明'),
            category,
            str(target),
            count,
            elapsed,
            st.session_state.get('service_type', ''),
            client_ip,
            user_id
        ]
        sheet.append_row(log_row)
    except Exception:
        pass

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
    if "火曜" in label and is_tue: return True
    if "水曜" in label and is_wed: return True
    if "木曜" in label and is_thu: return True
    if "金曜" in label and is_fri: return True
    if "土曜" in label and is_sat: return True
    if "日曜" in label and is_sun: return True
    if ("祝祭日" in label or "祝日" in label) and is_hol: return True

    return False

@st.cache_resource
def get_gspread_client():
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = json.loads(st.secrets["gcp_service_account"])
            credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            return gspread.authorize(credentials)
    except Exception:
        pass
        
    if os.path.exists(JSON_KEY_FILE):
        try:
            credentials = Credentials.from_service_account_file(JSON_KEY_FILE, scopes=scopes)
            return gspread.authorize(credentials)
        except Exception:
            pass
            
    try:
        credentials, _ = google.auth.default(scopes=scopes)
        return gspread.authorize(credentials)
    except Exception:
        return None

def get_exception_cells(row_idx, attendance):
    cells = []
    if attendance == "午前欠席":
        cells.append(f"E{row_idx}")
        cells.append(f"J{row_idx}")
    elif attendance == "午後欠席":
        cells.append(f"F{row_idx}")
    return cells

def apply_marking_to_sheet(sheet, exceptions, start_row, end_row):
    try:
        formats = [
            {"range": f"E{start_row}:F{end_row}", "format": {"backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}}},
            {"range": f"J{start_row}:J{end_row}", "format": {"backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}}}
        ]
        
        if exceptions:
            color = {"backgroundColor": {"red": 1.0, "green": 0.9, "blue": 0.6}}
            formats.extend([{"range": cell, "format": color} for cell in exceptions])
            
        sheet.batch_format(formats)
    except Exception as e:
        st.warning(f"スプレッドシートの網掛け処理でエラーが発生しました: {e}")

def get_sheet_data(client, sheet_name, columns):
    try:
        sheet = client.open_by_key(SPREADSHEET_KEY).worksheet(sheet_name)
        records = sheet.get_all_records()
        if not records:
            return pd.DataFrame(columns=columns)
        df = pd.DataFrame(records)
        for col in columns:
            if col not in df.columns:
                df[col] = ''
        df = df.astype(str)
        
        if '出欠状況' in df.columns:
            df['出欠状況'] = df['出欠状況'].replace('全日欠席', '欠席')
            
        df = df[df['記載日'].str.strip() != '']
        
        return df[columns]
    except Exception as e:
        st.error(f"スプレッドシートからのデータ読み込みに失敗しました ({e})")
        return None

def update_entire_sheet(client, sheet_name, df, init_settings):
    try:
        sheet = client.open_by_key(SPREADSHEET_KEY).worksheet(sheet_name)
        
        update_data = [df.columns.values.tolist()] + df.values.tolist()
        
        empty_row = [""] * len(df.columns)
        update_data.extend([empty_row] * 100)
        
        try:
            sheet.update('A1', update_data)
        except TypeError:
            sheet.update(update_data)

        all_exceptions = []
        end_row = len(df) + 1
        for i, row in df.iterrows():
            row_idx = i + 2
            att = str(row.get('出欠状況', ''))
            exc = get_exception_cells(row_idx, att)
            all_exceptions.extend(exc)
            
        if end_row >= 2:
            apply_marking_to_sheet(sheet, all_exceptions, 2, end_row)
            
        return True
    except Exception as e:
        if 'WorksheetNotFound' in str(type(e)):
            st.error(f"「{sheet_name}」シートが見つかりません、スプレッドシートに作成してください")
        else:
            st.error(f"データの書き込みに失敗しました: {e}")
        return False

def clear_text(key):
    if key in st.session_state:
        st.session_state[key] = ""

def check_absence_addition_count(client, sheet_name, client_name, target_date, columns):
    df = get_sheet_data(client, sheet_name, columns)
    if df is None or df.empty:
        return 0
    
    target_month = target_date.strftime('%Y-%m')
    
    count = df[
        (df['名前'] == client_name) & 
        (df['記載日'].str.startswith(target_month)) & 
        (df['特記事項'].str.contains('【利用計画あり】', na=False))
    ].shape[0]
    
    return count

init_settings = load_init_settings()

def on_date_new_change():
    if not st.session_state.get('full_ab_new', False):
        selected_date = st.session_state.date_new
        if selected_date.weekday() == 5:
            st.session_state.st_new = init_settings.get('SAT_start_time', '10:00')
            st.session_state.et_new = init_settings.get('SAT_end_time', '12:00')
        else:
            st.session_state.st_new = init_settings.get('start_time', '10:00')
            st.session_state.et_new = init_settings.get('end_time', '15:00')

def on_full_attendance_change():
    if st.session_state.full_ab_new:
        st.session_state.st_new = ""
        st.session_state.et_new = ""
        st.session_state.meal_new = "×"
        if "snack_new" in st.session_state: st.session_state.snack_new = "×"
        st.session_state.tardy_new = False
        st.session_state.nakanuke_new = False
    else:
        selected_date = st.session_state.get('date_new', datetime.now(JST).date())
        if selected_date.weekday() == 5:
            st.session_state.st_new = init_settings.get('SAT_start_time', '10:00')
            st.session_state.et_new = init_settings.get('SAT_end_time', '12:00')
        else:
            st.session_state.st_new = init_settings.get('start_time', '10:00')
            st.session_state.et_new = init_settings.get('end_time', '15:00')
        st.session_state.meal_new = "〇"
        if "snack_new" in st.session_state: st.session_state.snack_new = "〇"

def on_b_full_attendance_change():
    if st.session_state.b_full_ab:
        st.session_state.b_st = ""
        st.session_state.b_et = ""
        st.session_state.b_meal = "×"
        if "b_snack" in st.session_state: st.session_state.b_snack = "×"
        st.session_state.b_tardy = False
        st.session_state.b_nakanuke = False
    else:
        st.session_state.b_st = init_settings.get('start_time', '10:00')
        st.session_state.b_et = init_settings.get('end_time', '15:00')
        st.session_state.b_meal = "〇"
        if "b_snack" in st.session_state: st.session_state.b_snack = "〇"

app_title = f"{st.session_state.service_type} 実績入力" if st.session_state.logged_in else "実績入力システム"
st.markdown(f'<h1 class="main-title">{app_title}</h1>', unsafe_allow_html=True)

g_client = get_gspread_client()
if g_client is None and st.session_state.logged_in:
    st.error("認証情報が取得できません、設定を確認してください")
    st.stop()

all_client_dict = load_client_master(g_client)

if not st.session_state.logged_in:
    st.write("### ログイン")
    login_settings = load_login_settings()
    password = st.text_input("パスワード（職員コード）を入力してください", type="password", autocomplete="new-password")
    
    if st.button("ログイン", type="primary", use_container_width=True):
        pass_lower = password.lower()
        role = None
        
        if pass_lower in [p.lower() for p in login_settings.get('Developer', [])]:
            role = "開発管理者"
        elif pass_lower in [p.lower() for p in login_settings.get('Admin', [])]:
            role = "管理者"
        elif pass_lower in [p.lower() for p in login_settings.get('GeneralStaff', [])]:
            role = "一般職員"
            
        if role:
            last_access = get_last_access_info(g_client)
            st.session_state.logged_in = True
            st.session_state.role = role
            st.session_state.user_id = password
            st.session_state.show_all_services = (role == "開発管理者")
            st.session_state.last_action_time = datetime.now(JST)
            st.session_state.last_access_display = last_access
            write_system_log(g_client, "ログイン", "-", 0)
            st.rerun()
        else:
            st.error("パスワード（職員コード）が間違っています")

    st.markdown("<br><hr>", unsafe_allow_html=True)
    st.write("スマホからアクセスする場合")
    app_url = os.environ.get('APP_URL')
    network_url = app_url if app_url else f"http://{get_local_ip()}:8501"
    st.markdown(f"<div style='font-size:0.9rem; color:#666;'>{network_url}</div>", unsafe_allow_html=True)
    st.image(generate_qr(network_url), width=180)

else:
    if st.session_state.success_msg:
        st.success(st.session_state.success_msg)
        st.session_state.success_msg = None

    col1, col2, col3 = st.columns([1.5, 1, 1])
    with col1:
        st.write(f"権限: {st.session_state.role}")
        if st.session_state.get('last_access_display'):
            st.markdown(f"<div style='font-size: 0.8rem; color: #666; margin-top: -10px;'>最終アクセス: {st.session_state.last_access_display}</div>", unsafe_allow_html=True)
    with col2:
        if st.button('更新', use_container_width=True):
            st.rerun()
    with col3:
        if st.button("退出", use_container_width=True):
            write_system_log(g_client, "退出", "-", 0)
            st.session_state.clear()
            st.rerun()

    st.markdown("<div style='font-size: 0.9rem; font-weight: bold; color: #666; margin-top: 15px; margin-bottom: 5px;'>対象サービス切り替え</div>", unsafe_allow_html=True)
    
    service_options = ["就労継続支援B型", "生活介護"]
    if st.session_state.get("show_all_services", False):
        service_options.extend(["児童発達支援", "放課後等デイサービス"])
        
    st.selectbox(
        "対象サービス", 
        service_options, 
        key="service_type",
        label_visibility="collapsed"
    )
    
    current_sheet_name = ''
    if st.session_state.service_type == '就労継続支援B型':
        current_sheet_name = '就労B2'
    elif st.session_state.service_type == '生活介護':
        current_sheet_name = '生活介護'
    elif st.session_state.service_type == '児童発達支援':
        current_sheet_name = '児発'
    elif st.session_state.service_type == '放課後等デイサービス':
        current_sheet_name = '放デイ'
        
    current_client_dict = all_client_dict.get(st.session_state.service_type, {})
    client_names = list(current_client_dict.keys()) if current_client_dict else ['未設定']
    enable_record = init_settings.get('enable_daily_record', 'True').lower() == 'true'
    show_absent_action = init_settings.get('show_absent_action', 'True').lower() == 'true'

    if st.session_state.role in ["管理者", "開発管理者"]:
        menu_tabs = ["新規入力", "個人・複数日入力", "全員一括入力", "過去の記録を編集"]
    else:
        menu_tabs = ["新規入力"]

    st.markdown("<div style='margin-top: 20px;'></div>", unsafe_allow_html=True)
    selected_tab = st.radio(
        "メニュー",
        menu_tabs,
        horizontal=True,
        label_visibility="collapsed",
        key="selected_tab_menu"
    )
    st.markdown("<hr style='margin-top: 0px; margin-bottom: 20px;'>", unsafe_allow_html=True)

    if selected_tab == "新規入力":
        today_date = datetime.now(JST).date()
        is_sat_today = (today_date.weekday() == 5)

        if 'st_new' not in st.session_state: st.session_state.st_new = init_settings.get('SAT_start_time', '10:00') if is_sat_today else init_settings.get('start_time', '10:00')
        if 'et_new' not in st.session_state: st.session_state.et_new = init_settings.get('SAT_end_time', '12:00') if is_sat_today else init_settings.get('end_time', '15:00')
        if 'meal_new' not in st.session_state: st.session_state.meal_new = "〇"
        if 'snack_new' not in st.session_state: st.session_state.snack_new = "〇"

        st.write("### 基本情報")
        record_date = st.date_input("記載日", today_date, key="date_new", on_change=on_date_new_change)
        
        st.markdown(f"<h3 style='color: {accent_color}; border-bottom: 2px solid {accent_color}; padding-bottom: 5px; margin-top: 20px; margin-bottom: 10px;'>対象の利用者</h3>", unsafe_allow_html=True)
        client_name = st.selectbox("名前（利用者）", client_names, key="name_new", label_visibility="collapsed")
        
        st.write("### 出欠状況")
        full_absent = st.checkbox("欠席", key="full_ab_new", on_change=on_full_attendance_change)
        is_all_absent = full_absent
        
        absent_reason = ""
        planned_absence = False
        absent_action = ""
        
        if is_all_absent:
            absent_reason = st.selectbox("欠席理由", ABSENT_REASON_OPTS, key="ab_reason_new")
            planned_absence = st.checkbox("本来の利用計画あり（欠席時対応加算等）", key="plan_ab_new")
            
            if planned_absence:
                count = check_absence_addition_count(g_client, current_sheet_name, client_name, record_date, current_columns)
                if count >= 4:
                    st.error(f"⚠️ 【警告】{client_name}さんの{record_date.month}月の「欠席時対応加算」は既に {count} 回記録されています。月4回の上限を超過します。")
                else:
                    st.info(f"💡 {client_name}さんの{record_date.month}月の「欠席時対応加算」は、現在 {count} 回算定済みです。（残り {4 - count} 回）")

            if show_absent_action:
                if planned_absence:
                    absent_action = st.text_input("欠席対応", placeholder="欠席利用計画有 (対応についての情報を入力してください)", key="ab_action_new")
                else:
                    absent_action = st.text_input("欠席対応", placeholder="対応内容があれば入力", key="ab_action_new")

        st.write("### 遅刻・早退")
        is_tardy_early = st.checkbox("遅刻・早退", key="tardy_new", disabled=is_all_absent)
        tardy_planned = ""
        tardy_reason = ""
        plan_start = ""
        plan_end = ""
        if is_tardy_early:
            if st.session_state.service_type == "生活介護" or is_child_service:
                st.warning("⚠️ 遅刻・早退の時刻を「特記事項」欄に記入してください")
                col_t1, col_t2 = st.columns(2)
                with col_t1:
                    tardy_planned = st.radio("計画の有無", ["計画あり", "計画なし"], horizontal=True, key="t_plan_new")
                with col_t2:
                    tardy_reason = st.radio("都合", ["利用者都合", "事業所都合"], horizontal=True, key="t_rsn_new")
                
                if tardy_planned == "計画あり":
                    col_ps, col_pe = st.columns(2)
                    with col_ps:
                        plan_start = st.text_input("計画開始時刻 (HH:MM)", key="p_st_new")
                    with col_pe:
                        plan_end = st.text_input("計画終了時刻 (HH:MM)", key="p_et_new")
            else:
                st.info("※遅刻・早退の理由や詳細は、必要に応じて「特記事項」欄へ記入してください")

        st.write("### 中抜け")
        is_nakanuke = st.checkbox("中抜け", key="nakanuke_new", disabled=is_all_absent)
        nakanuke_start = ""
        nakanuke_end = ""
        if is_nakanuke:
            col_ns, col_ne = st.columns(2)
            with col_ns:
                nakanuke_start = st.text_input("中抜け開始時刻 (HH:MM)", key="n_st_new")
            with col_ne:
                nakanuke_end = st.text_input("中抜け終了時刻 (HH:MM)", key="n_et_new")
            
            st.info("※中抜けの理由や詳細は、必要に応じて「特記事項」欄へ記入してください")

        st.write("### サービス提供状況")
        if is_tardy_early or is_nakanuke:
            st.warning("⚠️ 実績に合わせて時刻を編集してください")
        col_start, col_end = st.columns(2)
        with col_start:
            input_start = st.text_input("開始時間 (HH:MM)", disabled=is_all_absent, key="st_new")
        with col_end:
            input_end = st.text_input("終了時間 (HH:MM)", disabled=is_all_absent, key="et_new")

        col_t1, col_t2 = st.columns(2)
        with col_t1:
            transport_out = st.radio("送迎往路", to_opts, horizontal=True, key="to_new", disabled=is_all_absent)
        with col_t2:
            transport_ret = st.radio("送迎復路", tr_opts, horizontal=True, key="tr_new", disabled=is_all_absent)

        meal_provided = st.radio("食事提供", ["〇", "×"], horizontal=True, key="meal_new", disabled=is_all_absent)
        meal_amount_val = ""
        if not is_all_absent and meal_provided == "〇":
            meal_amount_val = st.number_input("食事量", min_value=0, max_value=10, value=10, step=1, key="meal_amt_new")

        if is_child_service:
            snack_provided = st.radio("おやつ提供", ["〇", "×"], horizontal=True, key="snack_new", disabled=is_all_absent)
            snack_amount = ""
            if not is_all_absent and snack_provided == "〇":
                snack_amount = st.selectbox("おやつ量", ["完食", "半分", "一口", "食べず"], key="snack_amt_new")

        temp_val = 36.5
        excretion_val = ""
        
        if enable_record:
            st.write("### 1日の記録")
            if is_child_service:
                col_r1, col_r2 = st.columns(2)
                with col_r1:
                    temp_val = st.number_input("検温 (℃)", min_value=34.0, max_value=43.0, value=36.5, step=0.1, format="%.1f", key="temp_new", disabled=is_all_absent)
                with col_r2:
                    condition = st.selectbox("体調", cond_opts, key="cond_new", disabled=is_all_absent)
                col_r3, col_r4 = st.columns(2)
                with col_r3:
                    excretion_val = st.selectbox("排泄", exc_opts, key="exc_new", disabled=is_all_absent)
                with col_r4:
                    engagement = st.selectbox(eng_label, eng_opts, key="eng_new", disabled=is_all_absent)
                mental = st.selectbox(men_label, men_opts, key="men_new", disabled=is_all_absent)
                support = st.selectbox("特別な支援", sup_opts, key="sup_new", disabled=is_all_absent)
            else:
                condition = st.selectbox("体調", cond_opts, key="cond_new", disabled=is_all_absent)
                engagement = st.selectbox(eng_label, eng_opts, key="eng_new", disabled=is_all_absent)
                mental = st.selectbox(men_label, men_opts, key="men_new", disabled=is_all_absent)
                support = st.selectbox("特別な支援", sup_opts, key="sup_new", disabled=is_all_absent)
        else:
            condition = ""
            engagement = ""
            mental = ""
            support = ""

        col_rem1, col_rem2 = st.columns([10, 1])
        with col_rem1:
            remarks = st.text_input("特記事項", placeholder="不良等の場合やトラブル時に手入力", key='remarks_new', disabled=is_all_absent)
        with col_rem2:
            st.markdown("<div style='margin-top: 27px;'></div>", unsafe_allow_html=True)
            st.button("x", key="clear_rem_new", on_click=clear_text, args=('remarks_new',), disabled=is_all_absent)

        status_placeholder_new = st.empty()
        submit_btn = st.button(label='記録を保存する', use_container_width=True, type='primary', key="submit_new")

        if submit_btn:
            allow_save = True
            
            if is_all_absent and planned_absence:
                current_count = check_absence_addition_count(g_client, current_sheet_name, client_name, record_date, current_columns)
                if current_count >= 4:
                    st.error(f"⚠️ 【保存エラー】{client_name}さんの{record_date.month}月の「欠席時対応加算」は既に{current_count}回算定済みです。月4回の上限を超えるため保存できません。")
                    allow_save = False
            
            if allow_save:
                status_placeholder_new.markdown(SPINNER_HTML, unsafe_allow_html=True)
                
                record_df = get_sheet_data(g_client, current_sheet_name, current_columns)
                
                if record_df is None:
                    status_placeholder_new.empty()
                    st.error("スプレッドシートのデータ取得に失敗したため、保存を中止しました。時間をおいて再度お試しください。")
                else:
                    if is_all_absent:
                        attendance_status = "欠席"
                    elif is_nakanuke:
                        attendance_status = "中抜け"
                    elif is_tardy_early:
                        attendance_status = "遅刻・早退"
                    else:
                        attendance_status = "出席"
        
                    calc_time = "" if is_all_absent else calc_working_hours(input_start, input_end, nakanuke_start, nakanuke_end)
                    recipient_num = current_client_dict.get(client_name, "")
                    
                    final_remarks = remarks
                    if is_all_absent:
                        final_remarks = f"【欠席理由: {absent_reason}】"
                        if planned_absence:
                            final_remarks += "【利用計画あり】"
                        if show_absent_action and absent_action:
                            final_remarks += f"対応: {absent_action}"
                        if remarks:
                            final_remarks += f" / {remarks}"

                    row_dict = {
                        '記載日': record_date.strftime('%Y-%m-%d'), 
                        '名前': client_name, 
                        '受給者証番号': recipient_num, 
                        '出欠状況': attendance_status,
                        '開始時間': "" if is_all_absent else input_start, 
                        '終了時間': "" if is_all_absent else input_end, 
                        '算定時間数': calc_time,
                        '送迎往路': "" if is_all_absent else transport_out, 
                        '送迎復路': "" if is_all_absent else transport_ret, 
                        '食事提供': "" if is_all_absent else meal_provided,
                        '食事量': "" if (is_all_absent or meal_provided == "×") else str(meal_amount_val),
                        '体調': "" if is_all_absent else condition,
                        eng_label: "" if is_all_absent else engagement,
                        men_label: "" if is_all_absent else mental,
                        '特別な支援': "" if is_all_absent else support,
                        '特記事項': final_remarks,
                        '遅刻・早退': "" if is_all_absent else ("〇" if is_tardy_early else ""),
                        '計画': "" if is_all_absent else (tardy_planned if is_tardy_early else ""),
                        '都合': "" if is_all_absent else (tardy_reason if is_tardy_early else ""),
                        '計画開始時刻': "" if is_all_absent else (plan_start if (is_tardy_early and tardy_planned == "計画あり") else ""),
                        '計画終了時刻': "" if is_all_absent else (plan_end if (is_tardy_early and tardy_planned == "計画あり") else ""),
                        '中抜け開始時刻': "" if is_all_absent else nakanuke_start,
                        '中抜け終了時刻': "" if is_all_absent else nakanuke_end
                    }
                    if is_child_service:
                        row_dict['おやつ提供'] = "" if is_all_absent else snack_provided
                        row_dict['おやつ量'] = "" if (is_all_absent or snack_provided == "×") else snack_amount
                        row_dict['検温'] = "" if is_all_absent else f"{temp_val:.1f}"
                        row_dict['排泄'] = "" if is_all_absent else excretion_val
                    
                    new_df = pd.DataFrame([row_dict], columns=current_columns)
                    updated_df = pd.concat([record_df, new_df], ignore_index=True)
                    updated_df = updated_df.drop_duplicates(subset=['記載日', '名前'], keep='last').reset_index(drop=True)
                    
                    if update_entire_sheet(g_client, current_sheet_name, updated_df, init_settings):
                        write_system_log(g_client, "新規入力", client_name, 1)
                        st.session_state.success_msg = f'{client_name} さんの実績を記録しました'
                        reset_keys = ['st_new', 'et_new', 'meal_new', 'meal_amt_new', 'snack_new', 'snack_amt_new', 'temp_new', 'exc_new', 'full_ab_new', 'plan_ab_new', 'to_new', 'tr_new', 'cond_new', 'eng_new', 'men_new', 'sup_new', 'remarks_new', 'ab_reason_new', 'ab_action_new', 'tardy_new', 'nakanuke_new', 't_plan_new', 't_rsn_new', 'p_st_new', 'p_et_new', 'n_st_new', 'n_et_new']
                        for k in reset_keys:
                            if k in st.session_state:
                                del st.session_state[k]
                        st.rerun()

    if st.session_state.role in ["管理者", "開発管理者"]:
        
        if selected_tab == "個人・複数日入力":
            if 'b_st' not in st.session_state: st.session_state.b_st = init_settings.get('start_time', '10:00')
            if 'b_et' not in st.session_state: st.session_state.b_et = init_settings.get('end_time', '15:00')
            if 'b_meal' not in st.session_state: st.session_state.b_meal = "〇"
            if 'b_snack' not in st.session_state: st.session_state.b_snack = "〇"

            st.write("### 一括登録する内容を設定してください")
            batch_dates = st.date_input('対象期間', value=(datetime.now(JST).date(), datetime.now(JST).date()), key="date_batch")
            
            col_ex1, col_ex2 = st.columns(2)
            exc_1_checked = False
            exc_2_checked = False
            with col_ex1:
                label1 = init_settings.get('exclude_label_1', '')
                if label1 and label1 != "なし":
                    exc_1_checked = st.checkbox(label1, value=True, key="exc_1")
            with col_ex2:
                label2 = init_settings.get('exclude_label_2', '')
                if label2 and label2 != "なし":
                    exc_2_checked = st.checkbox(label2, value=True, key="exc_2")
            
            st.markdown(f"<h3 style='color: {accent_color}; border-bottom: 2px solid {accent_color}; padding-bottom: 5px; margin-top: 20px; margin-bottom: 10px;'>対象の利用者</h3>", unsafe_allow_html=True)
            b_client_name = st.selectbox('名前（利用者）', client_names, key='name_batch', label_visibility="collapsed")
            
            st.write("### 出欠状況")
            b_full_absent = st.checkbox("欠席", key="b_full_ab", on_change=on_b_full_attendance_change)
            is_b_all_absent = b_full_absent
            
            b_absent_reason = ""
            b_planned_absence = False
            b_absent_action = ""
            if is_b_all_absent:
                b_absent_reason = st.selectbox("欠席理由", ABSENT_REASON_OPTS, key="b_ab_reason")
                b_planned_absence = st.checkbox("本来の利用計画あり（欠席時対応加算等）", key="b_plan_ab")
                
                if b_planned_absence:
                    target_date = batch_dates[0] if isinstance(batch_dates, tuple) and len(batch_dates) > 0 else batch_dates
                    b_count = check_absence_addition_count(g_client, current_sheet_name, b_client_name, target_date, current_columns)
                    if b_count >= 4:
                        st.error(f"⚠️ 【警告】{b_client_name}さんの{target_date.month}月の「欠席時対応加算」は既に {b_count} 回記録されています。月4回の上限を超過します。")
                    else:
                        st.info(f"💡 {b_client_name}さんの{target_date.month}月の「欠席時対応加算」は、現在 {b_count} 回算定済みです。（残り {4 - b_count} 回）")

                if show_absent_action:
                    if b_planned_absence:
                        b_absent_action = st.text_input("欠席対応", placeholder="欠席利用計画有 (対応についての情報を入力してください)", key="b_ab_action")
                    else:
                        b_absent_action = st.text_input("欠席対応", placeholder="対応内容があれば入力", key="b_ab_action")

            st.write("### 遅刻・早退")
            b_is_tardy_early = st.checkbox("遅刻・早退", key="b_tardy", disabled=is_b_all_absent)
            b_tardy_planned = ""
            b_tardy_reason = ""
            b_plan_start = ""
            b_plan_end = ""
            if b_is_tardy_early:
                if st.session_state.service_type == "生活介護" or is_child_service:
                    st.warning("⚠️ 遅刻・早退の時刻を「特記事項」欄に記入してください")
                    col_btardy1, col_btardy2 = st.columns(2)
                    with col_btardy1:
                        b_tardy_planned = st.radio("計画の有無", ["計画あり", "計画なし"], horizontal=True, key="b_t_plan")
                    with col_btardy2:
                        b_tardy_reason = st.radio("都合", ["利用者都合", "事業所都合"], horizontal=True, key="b_t_rsn")
                    
                    if b_tardy_planned == "計画あり":
                        col_bps, col_bpe = st.columns(2)
                        with col_bps:
                            b_plan_start = st.text_input("計画開始時刻 (HH:MM)", key="b_p_st")
                        with col_bpe:
                            b_plan_end = st.text_input("計画終了時刻 (HH:MM)", key="b_p_et")
                else:
                    st.info("※遅刻・早退の理由や詳細は、必要に応じて「特記事項」欄へ記入してください")
            
            st.write("### 中抜け")
            b_is_nakanuke = st.checkbox("中抜け", key="b_nakanuke", disabled=is_b_all_absent)
            b_nakanuke_start = ""
            b_nakanuke_end = ""
            if b_is_nakanuke:
                col_bns, col_bne = st.columns(2)
                with col_bns:
                    b_nakanuke_start = st.text_input("中抜け開始時刻 (HH:MM)", key="b_n_st")
                with col_bne:
                    b_nakanuke_end = st.text_input("中抜け終了時刻 (HH:MM)", key="b_n_et")
                st.info("※中抜けの理由や詳細は、必要に応じて「特記事項」欄へ記入してください")
            
            st.write("### サービス提供状況")
            if b_is_tardy_early or b_is_nakanuke:
                st.warning("⚠️ 実績に合わせて時刻を編集してください")
            col_bs, col_be = st.columns(2)
            with col_bs:
                b_start = st.text_input("開始時間 (HH:MM)", disabled=is_b_all_absent, key="b_st")
            with col_be:
                b_end = st.text_input("終了時間 (HH:MM)", disabled=is_b_all_absent, key="b_et")

            col_bt1, col_bt2 = st.columns(2)
            with col_bt1:
                b_transport_out = st.radio("送迎往路", to_opts, horizontal=True, key='b_to', disabled=is_b_all_absent)
            with col_bt2:
                b_transport_ret = st.radio("送迎復路", tr_opts, horizontal=True, key='b_tr', disabled=is_b_all_absent)

            b_meal_provided = st.radio("食事提供", ["〇", "×"], horizontal=True, key='b_meal', disabled=is_b_all_absent)
            b_meal_amount_val = ""
            if not is_b_all_absent and b_meal_provided == "〇":
                b_meal_amount_val = st.number_input("食事量", min_value=0, max_value=10, value=10, step=1, key="b_meal_amt")

            if is_child_service:
                b_snack_provided = st.radio("おやつ提供", ["〇", "×"], horizontal=True, key='b_snack', disabled=is_b_all_absent)
                b_snack_amount = ""
                if not is_b_all_absent and b_snack_provided == "〇":
                    b_snack_amount = st.selectbox("おやつ量", ["完食", "半分", "一口", "食べず"], key="b_snack_amt")

            b_temp_val = 36.5
            b_excretion_val = ""

            if enable_record:
                st.write("### 1日の記録")
                if is_child_service:
                    col_br1, col_br2 = st.columns(2)
                    with col_br1:
                        b_temp_val = st.number_input("検温 (℃)", min_value=34.0, max_value=43.0, value=36.5, step=0.1, format="%.1f", key="b_temp", disabled=is_b_all_absent)
                    with col_br2:
                        b_condition = st.selectbox("体調", cond_opts, key='b_cond', disabled=is_b_all_absent)
                    col_br3, col_br4 = st.columns(2)
                    with col_br3:
                        b_excretion_val = st.selectbox("排泄", exc_opts, key="b_exc", disabled=is_b_all_absent)
                    with col_br4:
                        b_engagement = st.selectbox(eng_label, eng_opts, key='b_eng', disabled=is_b_all_absent)
                    b_mental = st.selectbox(men_label, men_opts, key='b_men', disabled=is_b_all_absent)
                    b_support = st.selectbox("特別な支援", sup_opts, key='b_sup', disabled=is_b_all_absent)
                else:
                    b_condition = st.selectbox("体調", cond_opts, key='b_cond', disabled=is_b_all_absent)
                    b_engagement = st.selectbox(eng_label, eng_opts, key='b_eng', disabled=is_b_all_absent)
                    b_mental = st.selectbox(men_label, men_opts, key='b_men', disabled=is_b_all_absent)
                    b_support = st.selectbox("特別な支援", sup_opts, key='b_sup', disabled=is_b_all_absent)
            else:
                b_condition = ""
                b_engagement = ""
                b_mental = ""
                b_support = ""
            
            col_brem1, col_brem2 = st.columns([10, 1])
            with col_brem1:
                b_remarks = st.text_input("特記事項", placeholder="自由記述", key='remarks_batch', disabled=is_b_all_absent)
            with col_brem2:
                st.markdown("<div style='margin-top: 27px;'></div>", unsafe_allow_html=True)
                st.button("x", key="clear_rem_batch", on_click=clear_text, args=('remarks_batch',), disabled=is_b_all_absent)
            
            status_placeholder_batch = st.empty()
            submit_batch = st.button(label='一括登録する', use_container_width=True, type='primary', key='submit_batch')
            
            if submit_batch:
                if len(batch_dates) != 2:
                    st.warning('開始日と終了日の両方を選択してください')
                else:
                    start_date, end_date = batch_dates
                    if start_date.year != end_date.year or start_date.month != end_date.month:
                        st.error('月を跨ぐ一括登録はできません、同じ月内で期間を指定してください')
                    else:
                        allow_save = True
                        adding_days = 0
                        
                        if is_b_all_absent and b_planned_absence:
                            for i in range((end_date - start_date).days + 1):
                                current_date = start_date + timedelta(days=i)
                                
                                exclude_it = False
                                if exc_1_checked and is_day_excluded(current_date, label1):
                                    exclude_it = True
                                if exc_2_checked and is_day_excluded(current_date, label2):
                                    exclude_it = True

                                if not exclude_it:
                                    adding_days += 1
                                    
                            if adding_days > 0:
                                current_count = check_absence_addition_count(g_client, current_sheet_name, b_client_name, start_date, current_columns)
                                if current_count + adding_days > 4:
                                    st.error(f"⚠️ 【保存エラー】{b_client_name}さんの{start_date.month}月の「欠席時対応加算」は現在{current_count}回算定済みです。今回{adding_days}日分を追加すると上限(月4回)を超えるため保存できません。")
                                    allow_save = False
                        
                        if allow_save:
                            status_placeholder_batch.markdown(SPINNER_HTML, unsafe_allow_html=True)
                            
                            record_df = get_sheet_data(g_client, current_sheet_name, current_columns)
                            if record_df is None:
                                status_placeholder_batch.empty()
                                st.error("スプレッドシートのデータ取得に失敗したため、保存処理を中止しました。時間をおいて再度お試しください。")
                            else:
                                if is_b_all_absent:
                                    b_attendance = "欠席"
                                elif b_is_nakanuke:
                                    b_attendance = "中抜け"
                                elif b_is_tardy_early:
                                    b_attendance = "遅刻・早退"
                                else:
                                    b_attendance = "出席"
        
                                new_rows_df = []
                                b_recipient_num = current_client_dict.get(b_client_name, "")
                                b_calc_time = "" if is_b_all_absent else calc_working_hours(b_start, b_end, b_nakanuke_start, b_nakanuke_end)
                                
                                b_final_remarks = b_remarks
                                if is_b_all_absent:
                                    b_final_remarks = f"【欠席理由: {b_absent_reason}】"
                                    if b_planned_absence:
                                        b_final_remarks += "【利用計画あり】"
                                    if show_absent_action and b_absent_action:
                                        b_final_remarks += f"対応: {b_absent_action}"
                                    if b_remarks:
                                        b_final_remarks += f" / {b_remarks}"
                                
                                for i in range((end_date - start_date).days + 1):
                                    current_date = start_date + timedelta(days=i)
                                    
                                    exclude_it = False
                                    if exc_1_checked and is_day_excluded(current_date, label1):
                                        exclude_it = True
                                    if exc_2_checked and is_day_excluded(current_date, label2):
                                        exclude_it = True
        
                                    if exclude_it:
                                        continue
                                        
                                    is_saturday = (current_date.weekday() == 5)
                                    if is_saturday:
                                        current_start = init_settings.get('SAT_start_time', '10:00')
                                        current_end = init_settings.get('SAT_end_time', '12:00')
                                        current_calc_time = "" if is_b_all_absent else calc_working_hours(current_start, current_end, b_nakanuke_start, b_nakanuke_end)
                                    else:
                                        current_start = b_start
                                        current_end = b_end
                                        current_calc_time = b_calc_time
                                    
                                    current_row_dict = {
                                        '記載日': current_date.strftime('%Y-%m-%d'),
                                        '名前': b_client_name,
                                        '受給者証番号': b_recipient_num,
                                        '出欠状況': b_attendance,
                                        '开始時間': "" if is_b_all_absent else current_start,
                                        '終了時間': "" if is_b_all_absent else current_end,
                                        '算定時間数': current_calc_time,
                                        '送迎往路': "" if is_b_all_absent else b_transport_out,
                                        '送迎復路': "" if is_b_all_absent else b_transport_ret,
                                        '食事提供': "" if is_b_all_absent else b_meal_provided,
                                        '食事量': "" if (is_b_all_absent or b_meal_provided == "×") else str(b_meal_amount_val),
                                        '体調': "" if is_b_all_absent else b_condition,
                                        eng_label: "" if is_b_all_absent else b_engagement,
                                        men_label: "" if is_b_all_absent else b_mental,
                                        '特別な支援': "" if is_b_all_absent else b_support,
                                        '特記事項': b_final_remarks,
                                        '遅刻・早退': "" if is_b_all_absent else ("〇" if b_is_tardy_early else ""),
                                        '計画': "" if is_b_all_absent else (b_tardy_planned if b_is_tardy_early else ""),
                                        '都合': "" if is_b_all_absent else (b_tardy_reason if b_is_tardy_early else ""),
                                        '計画開始時刻': "" if is_b_all_absent else (b_plan_start if (b_is_tardy_early and b_tardy_planned == "計画あり") else ""),
                                        '計画終了時刻': "" if is_b_all_absent else (b_plan_end if (b_is_tardy_early and b_tardy_planned == "計画あり") else ""),
                                        '中抜け開始時刻': "" if is_b_all_absent else b_nakanuke_start,
                                        '中抜け終了時刻': "" if is_b_all_absent else b_nakanuke_end
                                    }
                                    if is_child_service:
                                        current_row_dict['おやつ提供'] = "" if is_b_all_absent else b_snack_provided
                                        current_row_dict['おやつ量'] = "" if (is_b_all_absent or b_snack_provided == "×") else b_snack_amount
                                        current_row_dict['検温'] = "" if is_b_all_absent else f"{b_temp_val:.1f}"
                                        current_row_dict['排泄'] = "" if is_b_all_absent else b_excretion_val

                                    new_rows_df.append(current_row_dict)
                                
                                if not new_rows_df:
                                    st.warning('登録対象となる日がありません')
                                else:
                                    new_df = pd.DataFrame(new_rows_df, columns=current_columns)
                                    updated_df = pd.concat([record_df, new_df], ignore_index=True)
                                    updated_df = updated_df.drop_duplicates(subset=['記載日', '名前'], keep='last').reset_index(drop=True)
                                    
                                    if update_entire_sheet(g_client, current_sheet_name, updated_df, init_settings):
                                        write_system_log(g_client, "個人・複数日入力", b_client_name, len(new_rows_df))
                                        st.session_state.success_msg = f'{b_client_name} さんの実績を {len(new_rows_df)}件 一括登録しました'
                                        reset_keys = ['b_st', 'b_et', 'b_meal', 'b_meal_amt', 'b_snack', 'b_snack_amt', 'b_temp', 'b_exc', 'b_full_ab', 'b_plan_ab', 'b_to', 'b_tr', 'b_cond', 'b_eng', 'b_men', 'b_sup', 'remarks_batch', 'b_ab_reason', 'b_ab_action', 'b_tardy', 'b_nakanuke', 'b_t_plan', 'b_t_rsn', 'b_p_st', 'b_p_et', 'b_n_st', 'b_n_et']
                                        for k in reset_keys:
                                            if k in st.session_state:
                                                del st.session_state[k]
                                        st.rerun()

        if selected_tab == "全員一括入力":
            st.write("### 全員一括登録する内容を設定してください")
            batch_dates_all = st.date_input('対象期間', value=(datetime.now(JST).date(), datetime.now(JST).date()), key="date_all")
            
            col_ex1_all, col_ex2_all = st.columns(2)
            exc_1_all_checked = False
            exc_2_all_checked = False
            with col_ex1_all:
                label1 = init_settings.get('exclude_label_1', '')
                if label1 and label1 != "なし":
                    exc_1_all_checked = st.checkbox(label1, value=True, key="exc_1_all")
            with col_ex2_all:
                label2 = init_settings.get('exclude_label_2', '')
                if label2 and label2 != "なし":
                    exc_2_all_checked = st.checkbox(label2, value=True, key="exc_2_all")
            
            valid_clients = [name for name in client_names if name != '未設定']
            st.info(f"現在選択されているサービスの登録者全員に対して、以下の同じ内容で一括登録します")
            
            if 'all_st' not in st.session_state: st.session_state.all_st = init_settings.get('start_time', '10:00')
            if 'all_et' not in st.session_state: st.session_state.all_et = init_settings.get('end_time', '15:00')
            if 'all_meal' not in st.session_state: st.session_state.all_meal = "〇"
            if 'all_snack' not in st.session_state: st.session_state.all_snack = "〇"

            st.write("### サービス提供状況 (デフォルト設定)")
            col_alls, col_alle = st.columns(2)
            with col_alls:
                all_start = st.text_input("開始時間 (HH:MM)", key="all_st")
            with col_alle:
                all_end = st.text_input("終了時間 (HH:MM)", key="all_et")

            col_allt1, col_allt2 = st.columns(2)
            with col_allt1:
                all_transport_out = st.radio("送迎往路", to_opts, horizontal=True, key='all_to')
            with col_allt2:
                all_transport_ret = st.radio("送迎復路", tr_opts, horizontal=True, key='all_tr')

            all_meal_provided = st.radio("食事提供", ["〇", "×"], horizontal=True, key='all_meal')
            all_meal_amount_val = ""
            if all_meal_provided == "〇":
                all_meal_amount_val = st.number_input("食事量 (デフォルト)", min_value=0, max_value=10, value=10, step=1, key="all_meal_amt")

            if is_child_service:
                all_snack_provided = st.radio("おやつ提供", ["〇", "×"], horizontal=True, key='all_snack')
                all_snack_amount = ""
                if all_snack_provided == "〇":
                    all_snack_amount = st.selectbox("おやつ量 (デフォルト)", ["完食", "半分", "一口", "食べず"], key="all_snack_amt")

            all_temp_val = 36.5
            all_excretion_val = ""

            if enable_record:
                st.write("### 1日の記録 (デフォルト設定)")
                if is_child_service:
                    col_allr1, col_allr2 = st.columns(2)
                    with col_allr1:
                        all_temp_val = st.number_input("検温 (℃)デフォルト", min_value=34.0, max_value=43.0, value=36.5, step=0.1, format="%.1f", key="all_temp")
                    with col_allr2:
                        all_condition = st.selectbox("体調", cond_opts, key='all_cond')
                    col_allr3, col_allr4 = st.columns(2)
                    with col_allr3:
                        all_excretion_val = st.selectbox("排泄 (デフォルト)", exc_opts, key="all_exc")
                    with col_allr4:
                        all_engagement = st.selectbox(eng_label, eng_opts, key='all_eng')
                    all_mental = st.selectbox(men_label, men_opts, key='all_men')
                    all_support = st.selectbox("特別な支援", sup_opts, key='all_sup')
                else:
                    all_condition = st.selectbox("体調", cond_opts, key='all_cond')
                    all_engagement = st.selectbox(eng_label, eng_opts, key='all_eng')
                    all_mental = st.selectbox(men_label, men_opts, key='all_men')
                    all_support = st.selectbox("特別な支援", sup_opts, key='all_sup')
            else:
                all_condition = ""
                all_engagement = ""
                all_mental = ""
                all_support = ""
            
            status_placeholder_all = st.empty()
            submit_all = st.button(label='全員分を一括登録する', use_container_width=True, type='primary', key='submit_all')
            
            if submit_all:
                if not valid_clients:
                    st.warning('登録対象となる利用者がいません')
                elif len(batch_dates_all) != 2:
                    st.warning('開始日と終了日の両方を選択してください')
                else:
                    start_date, end_date = batch_dates_all
                    if start_date.year != end_date.year or start_date.month != end_date.month:
                        st.error('月を跨ぐ一括登録はできません、同じ月内で期間を指定してください')
                    else:
                        status_placeholder_all.markdown(SPINNER_HTML, unsafe_allow_html=True)
                        
                        record_df = get_sheet_data(g_client, current_sheet_name, current_columns)
                        if record_df is None:
                            status_placeholder_all.empty()
                            st.error("スプレッドシートのデータ取得に失敗したため、保存処理を中止しました。時間をおいて再度お試しください。")
                        else:
                            new_rows_df = []
                            all_calc_time = calc_working_hours(all_start, all_end)
                            
                            for i in range((end_date - start_date).days + 1):
                                current_date = start_date + timedelta(days=i)
                                
                                exclude_it = False
                                if exc_1_all_checked and is_day_excluded(current_date, label1):
                                    exclude_it = True
                                if exc_2_all_checked and is_day_excluded(current_date, label2):
                                    exclude_it = True
    
                                if exclude_it:
                                    continue
                                    
                                is_saturday = (current_date.weekday() == 5)
                                if is_saturday:
                                    current_start = init_settings.get('SAT_start_time', '10:00')
                                    current_end = init_settings.get('SAT_end_time', '12:00')
                                    current_calc_time = calc_working_hours(current_start, current_end)
                                else:
                                    current_start = all_start
                                    current_end = all_end
                                    current_calc_time = all_calc_time
                                
                                for c_name in valid_clients:
                                    c_recipient_num = current_client_dict.get(c_name, "")
                                    
                                    current_row_dict = {
                                        '記載日': current_date.strftime('%Y-%m-%d'),
                                        '名前': c_name,
                                        '受給者証番号': c_recipient_num,
                                        '出欠状況': "出席",
                                        '開始時間': current_start,
                                        '終了時間': current_end,
                                        '算定時間数': current_calc_time,
                                        '送迎往路': all_transport_out,
                                        '送迎復路': all_transport_ret,
                                        '食事提供': all_meal_provided,
                                        '食事量': str(all_meal_amount_val) if all_meal_provided == "〇" else "",
                                        '体調': all_condition,
                                        eng_label: all_engagement,
                                        men_label: all_mental,
                                        '特別な支援': all_support,
                                        '特記事項': "",
                                        '遅刻・早退': "",
                                        '計画': "",
                                        '都合': "",
                                        '計画開始時刻': "",
                                        '計画終了時刻': "",
                                        '中抜け開始時刻': "",
                                        '中抜け終了時刻': ""
                                    }
                                    if is_child_service:
                                        current_row_dict['おやつ提供'] = all_snack_provided
                                        current_row_dict['おやつ量'] = all_snack_amount if all_snack_provided == "〇" else ""
                                        current_row_dict['検温'] = f"{all_temp_val:.1f}"
                                        current_row_dict['排泄'] = all_excretion_val

                                    new_rows_df.append(current_row_dict)
                            
                            if not new_rows_df:
                                st.warning('登録対象となる日がありません')
                            else:
                                new_df = pd.DataFrame(new_rows_df, columns=current_columns)
                                updated_df = pd.concat([record_df, new_df], ignore_index=True)
                                updated_df = updated_df.drop_duplicates(subset=['記載日', '名前'], keep='last').reset_index(drop=True)
                                
                                if update_entire_sheet(g_client, current_sheet_name, updated_df, init_settings):
                                    write_system_log(g_client, "全員一括入力", f"対象{len(valid_clients)}名", len(new_rows_df))
                                    st.session_state.success_msg = f'合計 {len(new_rows_df)}件の実績を一括登録しました、「過去の記録を編集」タブから個別修正を行ってください'
                                    reset_keys = ['all_st', 'all_et', 'all_meal', 'all_meal_amt', 'all_snack', 'all_snack_amt', 'all_temp', 'all_exc', 'all_to', 'all_tr', 'all_cond', 'all_eng', 'all_men', 'all_sup']
                                    for k in reset_keys:
                                        if k in st.session_state:
                                            del st.session_state[k]
                                    st.rerun()

        if selected_tab == "過去の記録を編集":
            today = datetime.now(JST).date()
            edit_dates = st.date_input('カレンダーから編集する期間', value=(today, today), key='edit_dates')
            
            if len(edit_dates) == 2:
                start_date, end_date = edit_dates
                
                if ('edit_last_start' not in st.session_state or 
                    st.session_state.edit_last_start != start_date or 
                    st.session_state.get('edit_last_end') != end_date or
                    st.session_state.get('edit_need_reload', False)):
                    
                    record_df = get_sheet_data(g_client, current_sheet_name, current_columns)
                    
                    if record_df is None:
                        st.error("スプレッドシートのデータ取得に失敗しました。時間をおいて再度お試しください。")
                        st.session_state.edit_cache = None
                        st.session_state.edit_original = None
                    elif not record_df.empty:
                        start_ts = pd.to_datetime(start_date)
                        end_ts = pd.to_datetime(end_date)
                        record_df['比較用日付'] = pd.to_datetime(record_df['記載日'], errors='coerce')
                        mask = (record_df['比較用日付'] >= start_ts) & (record_df['比較用日付'] <= end_ts)
                        
                        target_records = record_df[mask].copy()
                        
                        st.session_state.edit_cache = target_records[current_columns].copy()
                        st.session_state.edit_original = target_records[current_columns].copy()
                        st.session_state.full_record_df = record_df.copy()
                    else:
                        st.session_state.edit_cache = pd.DataFrame(columns=current_columns)
                        st.session_state.edit_original = pd.DataFrame(columns=current_columns)
                        st.session_state.full_record_df = record_df
                        
                    st.session_state.edit_last_start = start_date
                    st.session_state.edit_last_end = end_date
                    st.session_state.edit_need_reload = False

                if st.session_state.get('edit_cache') is not None:
                    if st.session_state.edit_cache.empty:
                        st.warning('指定された期間に記録がありません')
                    else:
                        # -------------------------------------------------------------
                        # streamlit-aggrid を用いた表の設定
                        # -------------------------------------------------------------
                        gb = GridOptionsBuilder.from_dataframe(st.session_state.edit_cache)
                        
                        gb.configure_default_column(editable=True)
                        
                        # ② 列の固定（左側）
                        gb.configure_column("記載日", pinned='left', width=110)
                        gb.configure_column("名前", pinned='left', width=110)
                        
                        # ③ ゼブラ柄、④ 日付の区切り線（JavaScriptを使用してスタイル制御）
                        jscode = JsCode("""
                        function(params) {
                            var style = {};
                            // ③ ゼブラ柄（偶数行を薄い緑色に）
                            if (params.node.rowIndex % 2 === 0) {
                                style['backgroundColor'] = '#d4edda';
                            } else {
                                style['backgroundColor'] = '#ffffff';
                            }
                            
                            // ④ 日付が変わった行の上に青い罫線を入れる
                            if (params.node.rowIndex > 0) {
                                var prevNode = params.api.getDisplayedRowAtIndex(params.node.rowIndex - 1);
                                if (prevNode && prevNode.data) {
                                    var prevDate = prevNode.data['記載日'];
                                    var currDate = params.node.data['記載日'];
                                    if (currDate !== prevDate) {
                                        style['borderTop'] = '2px solid #2196F3';
                                    }
                                }
                            }
                            return style;
                        }
                        """)
                        gb.configure_grid_options(getRowStyle=jscode)
                        
                        # プルダウン（セレクトボックス）の設定
                        gb.configure_column("出欠状況", cellEditor='agSelectCellEditor', cellEditorParams={'values': ["出席", "遅刻・早退", "中抜け", "欠席"]})
                        gb.configure_column("送迎往路", cellEditor='agSelectCellEditor', cellEditorParams={'values': ["〇", "×", "学校", "自宅", "なし"]})
                        gb.configure_column("送迎復路", cellEditor='agSelectCellEditor', cellEditorParams={'values': ["〇", "×", "自宅", "なし"]})
                        gb.configure_column("食事提供", cellEditor='agSelectCellEditor', cellEditorParams={'values': ["〇", "×"]})
                        gb.configure_column("体調", cellEditor='agSelectCellEditor', cellEditorParams={'values': cond_opts})
                        gb.configure_column(eng_label, cellEditor='agSelectCellEditor', cellEditorParams={'values': eng_opts})
                        gb.configure_column(men_label, cellEditor='agSelectCellEditor', cellEditorParams={'values': men_opts})
                        gb.configure_column("特別な支援", cellEditor='agSelectCellEditor', cellEditorParams={'values': sup_opts})
                        gb.configure_column("遅刻・早退", cellEditor='agSelectCellEditor', cellEditorParams={'values': ["〇", ""]})
                        
                        if st.session_state.service_type == "生活介護" or is_child_service:
                            gb.configure_column("計画", cellEditor='agSelectCellEditor', cellEditorParams={'values': ["計画あり", "計画なし", ""]})
                            gb.configure_column("都合", cellEditor='agSelectCellEditor', cellEditorParams={'values': ["利用者都合", "事業所都合", ""]})
                            
                        if is_child_service:
                            gb.configure_column("おやつ提供", cellEditor='agSelectCellEditor', cellEditorParams={'values': ["〇", "×"]})
                            gb.configure_column("おやつ量", cellEditor='agSelectCellEditor', cellEditorParams={'values': ["完食", "半分", "一口", "食べず"]})
                            gb.configure_column("排泄", cellEditor='agSelectCellEditor', cellEditorParams={'values': exc_opts})

                        gridOptions = gb.build()
                        
                        # ① 編集時にスクロールが飛ばないようAgGridの内部状態を利用
                        response = AgGrid(
                            st.session_state.edit_cache,
                            gridOptions=gridOptions,
                            update_mode=GridUpdateMode.MODEL_CHANGED,
                            data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
                            fit_columns_on_grid_load=False,
                            theme='balham', # よりExcelに近い高密度のテーマ
                            allow_unsafe_jscode=True # カスタムデザイン（ゼブラ柄等）を適用するために必須
                        )
                        
                        # 編集後のデータフレームを取得
                        edited_df = pd.DataFrame(response['data'])
                        
                        status_placeholder_edit = st.empty()
                        save_btn = st.button('変更を保存する', type='primary')
                        
                        if save_btn:
                            status_placeholder_edit.markdown(SPINNER_HTML, unsafe_allow_html=True)
                            
                            original_df = st.session_state.edit_original
                            
                            for idx in edited_df.index:
                                current_status = edited_df.at[idx, '出欠状況']
                                cached_status = original_df.at[idx, '出欠状況'] if idx in original_df.index else ""
                                
                                cols_to_clear = ['開始時間', '終了時間', '算定時間数', '送迎往路', '送迎復路', '食事提供', '食事量', '体調', eng_label, men_label, '特別な支援', '遅刻・早退', '計画', '都合', '計画開始時刻', '計画終了時刻', '中抜け開始時刻', '中抜け終了時刻']
                                if is_child_service:
                                    cols_to_clear.extend(['おやつ提供', 'おやつ量', '検温', '排泄'])

                                if current_status == '欠席':
                                    for col in cols_to_clear:
                                        if col in edited_df.columns and pd.notna(edited_df.at[idx, col]) and str(edited_df.at[idx, col]).strip() != '':
                                            edited_df.at[idx, col] = ''
                                
                                elif cached_status == '欠席' and current_status != '欠席':
                                    for col in cols_to_clear:
                                        if idx in original_df.index:
                                            orig_val = original_df.at[idx, col]
                                            if pd.notna(orig_val) and col in edited_df.columns:
                                                edited_df.at[idx, col] = orig_val
                                
                                if current_status != '欠席':
                                    cur_st = str(edited_df.at[idx, '開始時間']).strip() if '開始時間' in edited_df.columns else ""
                                    cur_et = str(edited_df.at[idx, '終了時間']).strip() if '終了時間' in edited_df.columns else ""
                                    cur_nst = str(edited_df.at[idx, '中抜け開始時刻']).strip() if '中抜け開始時刻' in edited_df.columns else ""
                                    cur_net = str(edited_df.at[idx, '中抜け終了時刻']).strip() if '中抜け終了時刻' in edited_df.columns else ""
                                    
                                    new_calc = calc_working_hours(cur_st, cur_et, cur_nst, cur_net)
                                    edited_df.at[idx, '算定時間数'] = new_calc
                            
                            record_df = st.session_state.full_record_df.copy()
                            
                            start_ts = pd.to_datetime(start_date)
                            end_ts = pd.to_datetime(end_date)
                            record_df['比較用日付'] = pd.to_datetime(record_df['記載日'], errors='coerce')
                            mask = (record_df['比較用日付'] >= start_ts) & (record_df['比較用日付'] <= end_ts)
                            record_df = record_df[~mask].copy()
                            
                            for idx in edited_df.index:
                                name = str(edited_df.at[idx, '名前'])
                                edited_df.at[idx, '受給者証番号'] = current_client_dict.get(name, "")
                                
                            record_df = pd.concat([record_df, edited_df[current_columns]], ignore_index=True)
                            record_df.drop(columns=['比較用日付'], inplace=True, errors='ignore')
                            
                            record_df = record_df.drop_duplicates(subset=['記載日', '名前'], keep='last').reset_index(drop=True)
                            record_df = record_df.sort_values(by=['記載日', '名前']).reset_index(drop=True)
                            
                            if update_entire_sheet(g_client, current_sheet_name, record_df, init_settings):
                                write_system_log(g_client, "データ編集保存", "-", len(edited_df))
                                st.session_state.success_msg = '記録をスプレッドシートに更新しました'
                                st.session_state.edit_need_reload = True
                                st.rerun()

            elif len(edit_dates) == 1:
                st.warning('終了日もカレンダーから選択してください')