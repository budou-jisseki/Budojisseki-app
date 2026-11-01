import json
import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import google.auth
import os
from datetime import datetime, timedelta, timezone
import socket
import qrcode
from io import BytesIO
import jpholiday
from st_aggrid import AgGrid, GridOptionsBuilder, DataReturnMode, GridUpdateMode, JsCode
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# 日本時間（JST）の定義
JST = timezone(timedelta(hours=+9), 'JST')

# ==========================================
# 設定とファイルパス
# ==========================================
JSON_KEY_FILE = 'secret.json'
# ここに「統括マスタ（テナント一覧）」のスプレッドシートIDを設定してください
MASTER_ROUTING_SHEET_KEY = '1rMyULhLjnXDllJFbVM1NcDsdv6_zwEMK56IeyOVM-oY'

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

COLUMNS_GH = [
    '記載日', '名前', '受給者証番号', '出欠状況',
    '朝食提供', '朝食量', '昼食提供', '昼食量', '夕食提供', '夕食量',
    '検温', '血圧_上', '血圧_下', '脈拍', 'SpO2', '体調',
    '服薬_朝', '服薬_昼', '服薬_夕', '服薬_就寝前', '頓服',
    '入浴', '排泄',
    '就寝時刻', '起床時刻', '睡眠状態',
    '通院同行', '日中活動先連携', '特別な支援', '特記事項'
]

CONDITION_OPTS = ['良好', '普通', '不良', '服薬忘れあり', 'その他']
ENGAGEMENT_OPTS = ['集中して取り組めた', '声かけにより取り組めた', '休みがちだった', '参加できなかった', 'その他']
MENTAL_OPTS = ['安定している', '少し不安定', '気分の落ち込みあり', 'イライラしていた', 'その他']
SUPPORT_OPTS = ['通常支援のみ', '個別面談を実施した', '体調不良による静養対応', '他機関との連絡調整', 'その他']

CONDITION_OPTS_CHILD = ['良好', '普通', '不良', 'その他']
ACTIVITY_OPTS = ['意欲的に参加できた', '声かけにより参加できた', '落ち着きがなかった', '参加できなかった', 'その他']
MOOD_OPTS = ['安定している', '少し不安定', '興奮気味だった', '機嫌が悪かった', 'その他']
SUPPORT_OPTS_CHILD = ['通常支援のみ', '個別対応を実施した', 'クールダウンを行った', '保護者と連携した', 'その他']

# GHの出欠状況から「日中滞在」を外し、「体験利用」を追加
GH_ATTENDANCE_OPTS = ['宿泊', '体験利用', '外泊', '入院', '欠席']
GH_MED_OPTS = ['済', '未', '無', '本人管理']
GH_BATH_OPTS = ['済', '未', 'シャワー', '清拭', '拒否', 'その他']
GH_EXC_OPTS = ['普通', '便秘', '下痢', '頻尿', '失禁', 'その他']
GH_SLEEP_OPTS = ['良眠', '中途覚醒', '不眠', 'その他']

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
if "grid_key" not in st.session_state: st.session_state.grid_key = "edit_grid_init"
if "init_settings" not in st.session_state: st.session_state.init_settings = {}

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
elif st.session_state.service_type == "共同生活援助":
    bg_color = "#f3e5f5"
    accent_color = "#8e24aa"
else:
    bg_color = "#ffffff"
    accent_color = "#333333"

is_child_service = st.session_state.service_type in ["児童発達支援", "放課後等デイサービス"]
is_gh_service = st.session_state.service_type == "共同生活援助"

if is_gh_service:
    current_columns = COLUMNS_GH
    cond_opts = CONDITION_OPTS
    sup_opts = SUPPORT_OPTS
elif is_child_service:
    current_columns = COLUMNS_CHILD
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
    current_columns = COLUMNS_ADULT
    cond_opts = CONDITION_OPTS
    eng_label = "作業の取り組み"
    eng_opts = ENGAGEMENT_OPTS
    men_label = "精神や情緒"
    men_opts = MENTAL_OPTS
    sup_opts = SUPPORT_OPTS
    to_opts = ["〇", "×"]
    tr_opts = ["〇", "×"]
    exc_opts = []

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
def send_closing_email(tenant_name, target_month, service_type, to_email):
    smtp_server = "smtp.gmail.com"
    smtp_port = 587
    from_email = "hidamarioffice3@gmail.com"
    app_password = "fptu eqxi tdwh nixx"
    
    if not to_email:
        to_email = "hidamarioffice3@gmail.com"
        
    subject = f"【実績入力システム】{target_month}分 {service_type} の入力完了（締め処理）通知"
    body = f"担当各位\n\n実績入力Webアプリ（SyuuB）より自動通知です。\n\n以下の事業所・サービスの月次データ入力が完了（締め処理）されました。\n\n事業所名: {tenant_name}\n対象年月: {target_month}\n対象サービス: {service_type}\n\n当該月のデータはロックされ、新規入力および変更が制限されています。\nご確認のほどよろしくお願いいたします。\n\n（このメールはシステムによって自動生成されています）"
    
    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    
    recipients = [email.strip() for email in to_email.split(',') if email.strip()]
    
    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(from_email, app_password)
        server.sendmail(from_email, recipients, msg.as_string())
        server.quit()
        return True
    except Exception:
        return False

def check_closing_alert(closing_day_str):
    now = datetime.now(JST).date()
    closing_date = None
    if closing_day_str == '末日':
        if now.month == 12:
            next_month = now.replace(year=now.year+1, month=1, day=1)
        else:
            next_month = now.replace(month=now.month+1, day=1)
        closing_date = next_month - timedelta(days=1)
    else:
        try:
            closing_date = now.replace(day=int(closing_day_str))
        except Exception:
            return None
    days_left = (closing_date - now).days
    if 0 <= days_left <= 2:
        return f"【お知らせ】{closing_date.day}日がデータの締日です。対象月のデータ入力完了をお願いします。"
    return None

def update_system_setting(client, sheet_id, key, value):
    try:
        sheet = client.open_by_key(sheet_id).worksheet('システム設定')
        records = sheet.get_all_values()
        for i, row in enumerate(records):
            if len(row) > 0 and row[0] == key:
                sheet.update_cell(i + 1, 2, value)
                return
        sheet.append_row([key, value])
    except Exception:
        pass

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

def get_tenant_info(client, tenant_key):
    try:
        sheet = client.open_by_key(MASTER_ROUTING_SHEET_KEY).worksheet('テナント一覧')
        records = sheet.get_all_records()
        for row in records:
            if str(row.get('暗号キー', '')) == tenant_key:
                return {
                    'name': row.get('事業所名', '不明な事業所'),
                    'sheet_id': row.get('スプレッドシートID', ''),
                    'status': str(row.get('状態', '有効')).strip()
                }
    except Exception:
        pass
    return None

def auto_setup_tenant_sheet(client, sheet_id):
    try:
        spreadsheet = client.open_by_key(sheet_id)
        existing_sheets = [ws.title for ws in spreadsheet.worksheets()]
        
        if 'システム設定' not in existing_sheets:
            ws_settings = spreadsheet.add_worksheet(title='システム設定', rows="50", cols="2")
            default_settings = [
                ['設定項目', '設定値'],
                ['closing_day', '末日'],
                ['notify_email', 'hidamarioffice3@gmail.com'],
                ['start_time', '10:00'], ['end_time', '15:00'],
                ['am_end_time', '12:00'], ['pm_start_time', '13:00'],
                ['rest_time_min', '60'], ['SAT_start_time', '10:00'],
                ['SAT_end_time', '12:00'], ['enable_daily_record', 'True'],
                ['show_absent_action', 'True'], ['exclude_label_1', '土曜日を除外する'],
                ['exclude_label_2', '日曜日・祝祭日を除外する'],
                ['enable_gh_meal_detail', 'True'], ['enable_gh_vital_detail', 'True'],
                ['enable_gh_medication', 'True'], ['enable_gh_life_record', 'True'],
                ['enable_gh_sleep_record', 'True'],
                ['GH_lunch_ui_mode', '日中滞在時のみ'],
                ['GH_default_temp', '36.5'],
                ['GH_default_breakfast', 'True'],
                ['GH_default_dinner', 'True'],
                ['GH_個別設定有効', 'False']
            ]
            ws_settings.update('A1', default_settings)

        if '職員マスタ' not in existing_sheets:
            ws_staff = spreadsheet.add_worksheet(title='職員マスタ', rows="50", cols="3")
            ws_staff.update('A1', [['職員名', 'パスワード', '権限'], ['開発管理者', '0000', '開発管理者'], ['初期管理者', '9999', '管理者'], ['一般職員', '1111', '一般職員']])

        # ★利用者マスタを12列に拡張
        if '利用者マスタ' not in existing_sheets:
            ws_client = spreadsheet.add_worksheet(title='利用者マスタ', rows="100", cols="12")
            ws_client.update('A1', [['利用者名', '受給者証番号', '就労／生活', '平熱', '朝食基本', '夕食基本', '就寝基本', '起床基本', '血圧上', '血圧下', '脈拍', 'SPO2']])

        service_sheets = {
            '就労B2': COLUMNS_ADULT,
            '生活介護': COLUMNS_ADULT,
            '児発': COLUMNS_CHILD,
            '放デイ': COLUMNS_CHILD,
            'グループホーム': COLUMNS_GH
        }
        for s_name, cols in service_sheets.items():
            if s_name not in existing_sheets:
                ws_service = spreadsheet.add_worksheet(title=s_name, rows="100", cols=str(len(cols)))
                ws_service.update('A1', [cols])
                
        if 'シート1' in existing_sheets and len(existing_sheets) > 1:
            spreadsheet.del_worksheet(spreadsheet.worksheet('シート1'))

    except Exception:
        pass

# 既存シートへの不足設定項目の自動追記
def check_and_add_missing_settings(client, sheet_id):
    try:
        sheet = client.open_by_key(sheet_id).worksheet('システム設定')
        records = sheet.get_all_values()
        existing_keys = [row[0] for row in records if len(row) > 0]
        
        default_gh_settings = {
            'GH_lunch_ui_mode': '日中滞在時のみ',
            'GH_default_temp': '36.5',
            'GH_default_breakfast': 'True',
            'GH_default_dinner': 'True',
            'GH_個別設定有効': 'False'
        }
        
        updates = []
        for key, val in default_gh_settings.items():
            if key not in existing_keys:
                updates.append([key, str(val)])
                
        if updates:
            for row in updates:
                sheet.append_row(row)
    except Exception:
        pass


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

def load_login_settings(client, sheet_id):
    logins = {'Developer': [], 'Admin': [], 'GeneralStaff': []}
    try:
        sheet = client.open_by_key(sheet_id).worksheet('職員マスタ')
        records = sheet.get_all_records()
        for row in records:
            pwd_raw = row.get('パスワード', '')
            if pwd_raw == '':
                continue
            
            pwd = str(pwd_raw).strip()
            if pwd.isdigit() and len(pwd) < 4:
                pwd = pwd.zfill(4)
                
            role = str(row.get('権限', '')).strip()
            if not pwd:
                continue
            
            if role in ['開発管理者', 'Developer']:
                logins['Developer'].append(pwd)
            elif role in ['管理者', 'Admin']:
                logins['Admin'].append(pwd)
            else:
                logins['GeneralStaff'].append(pwd)
    except Exception:
        pass
    return logins

def get_last_access_info(client, sheet_id):
    if client is None: return None
    try:
        sheet = client.open_by_key(sheet_id).worksheet(LOG_SHEET_NAME)
        records = sheet.get_all_values()
        for row in reversed(records):
            if len(row) >= 3 and row[1] != "開発管理者" and row[1] != "権限":
                return f"{row[0]} ({row[1]}による{row[2]})"
    except Exception:
        pass
    return "記録なし"

def write_system_log(client, sheet_id, category, target, count):
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
            sheet = client.open_by_key(sheet_id).worksheet(LOG_SHEET_NAME)
        except Exception:
            spreadsheet = client.open_by_key(sheet_id)
            sheet = spreadsheet.add_worksheet(title=LOG_SHEET_NAME, rows="100", cols="9")
            sheet.append_row(['タイムスタンプ', '権限', '操作カテゴリ', '処理対象', '処理件数', '操作間隔(秒)', '対象サービス', 'IPアドレス', '操作者ID'])
        
        log_row = [
            now.strftime('%Y-%m-%d %H:%M:%S'),
            st.session_state.get('role', '不明'),
            category, str(target), count, elapsed,
            st.session_state.get('service_type', ''), client_ip, user_id
        ]
        sheet.append_row(log_row)
    except Exception:
        pass

# ★ 利用者マスタから個別設定を含めて読み込むように拡張
def load_client_master(client, sheet_id):
    client_dict = {'就労継続支援B型': {}, '生活介護': {}, '児童発達支援': {}, '放課後等デイサービス': {}, '共同生活援助': {}}
    if client is None: return client_dict
    try:
        sheet = client.open_by_key(sheet_id).worksheet(MASTER_SHEET_NAME)
        records = sheet.get_all_records()
        for row in records:
            name = str(row.get('利用者名', '')).strip()
            num = str(row.get('受給者証番号', '')).strip()
            category = str(row.get('就労／生活', row.get('就労/生活', ''))).strip()
            
            # 個別設定の取得（列がない場合は空文字）
            temp = str(row.get('平熱', '')).strip()
            bf = str(row.get('朝食基本', '')).strip()
            dn = str(row.get('夕食基本', '')).strip()
            bed = str(row.get('就寝基本', '')).strip()
            wake = str(row.get('起床基本', '')).strip()
            bp_h = str(row.get('血圧上', '')).strip()
            bp_l = str(row.get('血圧下', '')).strip()
            pulse = str(row.get('脈拍', '')).strip()
            spo2 = str(row.get('SPO2', '')).strip()

            val_dict = {
                'num': num,
                'temp': temp,
                'bf': bf,
                'dn': dn,
                'bed': bed,
                'wake': wake,
                'bp_h': bp_h,
                'bp_l': bp_l,
                'pulse': pulse,
                'spo2': spo2
            }

            if name:
                if category == '46': client_dict['就労継続支援B型'][name] = val_dict
                elif category == '22': client_dict['生活介護'][name] = val_dict
                elif category == '11': client_dict['児童発達支援'][name] = val_dict
                elif category == '12': client_dict['放課後等デイサービス'][name] = val_dict
                elif category == '33': client_dict['共同生活援助'][name] = val_dict
    except Exception:
        pass
    return client_dict

def load_init_settings(client, sheet_id):
    settings = {
        'closing_day': '末日', 'notify_email': 'hidamarioffice3@gmail.com',
        'start_time': '10:00', 'end_time': '15:00', 
        'am_end_time': '12:00', 'pm_start_time': '13:00', 
        'rest_time_min': '60', 'SAT_start_time': '10:00',
        'SAT_end_time': '12:00', 'enable_daily_record': 'True',
        'show_absent_action': 'True', 'exclude_label_1': '土曜日を除外する',
        'exclude_label_2': '日曜日・祝祭日を除外する',
        'enable_gh_meal_detail': 'True', 'enable_gh_vital_detail': 'True',
        'enable_gh_medication': 'True', 'enable_gh_life_record': 'True',
        'enable_gh_sleep_record': 'True',
        'GH_lunch_ui_mode': '日中滞在時のみ',
        'GH_default_temp': '36.5',
        'GH_default_breakfast': 'True',
        'GH_default_dinner': 'True',
        'GH_個別設定有効': 'False'
    }
    try:
        sheet = client.open_by_key(sheet_id).worksheet('システム設定')
        records = sheet.get_all_records()
        for row in records:
            key = str(row.get('設定項目', '')).strip()
            val = str(row.get('設定値', '')).strip()
            if key and val:
                settings[key] = val
    except Exception:
        pass
    return settings

def calc_working_hours(start_str, end_str, n_start_str="", n_end_str=""):
    if not start_str or not end_str: return ""
    try:
        start_dt = datetime.strptime(start_str, "%H:%M")
        end_dt = datetime.strptime(end_str, "%H:%M")
        diff_min = (end_dt - start_dt).total_seconds() / 60
        nakanuke_min = 0
        if n_start_str and n_end_str:
            try:
                n_st_dt = datetime.strptime(n_start_str, "%H:%M")
                n_et_dt = datetime.strptime(n_end_str, "%H:%M")
                nakanuke_min = max(0, (n_et_dt - n_st_dt).total_seconds() / 60)
            except Exception:
                pass
        actual_min = max(0, diff_min - nakanuke_min)
        h = int(actual_min // 60)
        m = int(actual_min % 60)
        return f"{h:02d}:{m:02d}"
    except Exception:
        return ""

def is_day_excluded(date_obj, label):
    if not label or label == "なし" or label == "": return False
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

def get_exception_cells(row_idx, attendance):
    cells = []
    if attendance in ["午前欠席", "欠席", "外泊", "入院"]:
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
    except Exception:
        pass

def get_sheet_data(client, sheet_id, sheet_name, columns):
    try:
        sheet = client.open_by_key(sheet_id).worksheet(sheet_name)
        records = sheet.get_all_records()
        if not records:
            return pd.DataFrame(columns=columns)
        df = pd.DataFrame(records)
        for col in columns:
            if col not in df.columns: df[col] = ''
        df = df.astype(str)
        if '出欠状況' in df.columns:
            df['出欠状況'] = df['出欠状況'].replace('全日欠席', '欠席')
        df = df[df['記載日'].str.strip() != '']
        return df[columns]
    except Exception:
        return None

def update_entire_sheet(client, sheet_id, sheet_name, df):
    try:
        sheet = client.open_by_key(sheet_id).worksheet(sheet_name)
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
        return False

def clear_text(key):
    if key in st.session_state:
        st.session_state[key] = ""

def check_absence_addition_count(client, sheet_id, sheet_name, client_name, target_date, columns):
    df = get_sheet_data(client, sheet_id, sheet_name, columns)
    if df is None or df.empty: return 0
    target_month = target_date.strftime('%Y-%m')
    count = df[
        (df['名前'] == client_name) & 
        (df['記載日'].str.startswith(target_month)) & 
        (df['特記事項'].str.contains('【利用計画あり】', na=False))
    ].shape[0]
    return count

def on_date_new_change():
    if not st.session_state.get('full_ab_new', False):
        selected_date = st.session_state.date_new
        if selected_date.weekday() == 5:
            st.session_state.st_new = st.session_state.init_settings.get('SAT_start_time', '10:00')
            st.session_state.et_new = st.session_state.init_settings.get('SAT_end_time', '12:00')
        else:
            st.session_state.st_new = st.session_state.init_settings.get('start_time', '10:00')
            st.session_state.et_new = st.session_state.init_settings.get('end_time', '15:00')

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
            st.session_state.st_new = st.session_state.init_settings.get('SAT_start_time', '10:00')
            st.session_state.et_new = st.session_state.init_settings.get('SAT_end_time', '12:00')
        else:
            st.session_state.st_new = st.session_state.init_settings.get('start_time', '10:00')
            st.session_state.et_new = st.session_state.init_settings.get('end_time', '15:00')
        st.session_state.meal_new = "〇"
        if "snack_new" in st.session_state: st.session_state.snack_new = "〇"

def on_b_full_attendance_change():
    if st.session_state.b_full_ab:
        st.session_state.b_st = ""
        st.session_state.b_et = ""
        st.session_state.b_meal = "×"
        if "b_snack" in st.session_state: st.session_state.b_snack = "×"
    else:
        st.session_state.b_st = st.session_state.init_settings.get('start_time', '10:00')
        st.session_state.b_et = st.session_state.init_settings.get('end_time', '15:00')
        st.session_state.b_meal = "〇"
        if "b_snack" in st.session_state: st.session_state.b_snack = "〇"


# ==========================================
# ルーティングおよび初期化処理
# ==========================================
tenant_key = st.query_params.get("key")
if not tenant_key:
    st.error("URLが無効です。専用のアクセスURL（暗号キー付き）を使用してください。")
    st.stop()

g_client = get_gspread_client()
if g_client is None:
    st.error("認証情報が取得できません。")
    st.stop()

if "tenant_info" not in st.session_state or st.session_state.get("tenant_key") != tenant_key:
    tenant_info = get_tenant_info(g_client, tenant_key)
    if not tenant_info or not tenant_info['sheet_id']:
        st.error("無効な事業所キーです。")
        st.stop()
        
    if tenant_info['status'] == '無効':
        st.error("この事業所のアドレスは現在利用停止されています。")
        st.stop()
    
    st.session_state.tenant_info = tenant_info
    st.session_state.tenant_key = tenant_key
    st.session_state.current_sheet_id = tenant_info['sheet_id']
    st.session_state.tenant_name = tenant_info['name']
    
    auto_setup_tenant_sheet(g_client, st.session_state.current_sheet_id)
    check_and_add_missing_settings(g_client, st.session_state.current_sheet_id)
    st.session_state.init_settings = load_init_settings(g_client, st.session_state.current_sheet_id)
    st.session_state.all_client_dict = load_client_master(g_client, st.session_state.current_sheet_id)


# ==========================================
# メイン画面
# ==========================================
app_title = f"{st.session_state.tenant_name} 実績入力" if st.session_state.logged_in else f"{st.session_state.tenant_name} ログイン"
st.markdown(f'<h1 class="main-title">{app_title}</h1>', unsafe_allow_html=True)

all_client_dict = st.session_state.all_client_dict
init_settings = st.session_state.init_settings

if not st.session_state.logged_in:
    st.write("### パスワード入力")
    login_settings = load_login_settings(g_client, st.session_state.current_sheet_id)
    password = st.text_input("パスワード（職員コード）を入力してください", type="password")
    
    if st.button("ログイン", type="primary", use_container_width=True):
        pass_lower = password.lower()
        role = None
        if pass_lower in [p.lower() for p in login_settings.get('Developer', [])]: role = "開発管理者"
        elif pass_lower in [p.lower() for p in login_settings.get('Admin', [])]: role = "管理者"
        elif pass_lower in [p.lower() for p in login_settings.get('GeneralStaff', [])]: role = "一般職員"
            
        if role:
            last_access = get_last_access_info(g_client, st.session_state.current_sheet_id)
            st.session_state.logged_in = True
            st.session_state.role = role
            st.session_state.user_id = password
            st.session_state.show_all_services = (role == "開発管理者")
            st.session_state.last_action_time = datetime.now(JST)
            st.session_state.last_access_display = last_access
            write_system_log(g_client, st.session_state.current_sheet_id, "ログイン", "-", 0)
            st.rerun()
        else:
            st.error("パスワード（職員コード）が間違っています")

    st.markdown("<br><hr>", unsafe_allow_html=True)
    st.write("スマホからアクセスする場合")
    
    # Cloud Runの公開URLを直接指定する
    base_url = "https://hidamari-jisseki-1025709562828.asia-northeast1.run.app"
    network_url = f"{base_url}/?key={tenant_key}"
    
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
        if st.button('更新', use_container_width=True): st.rerun()
    with col3:
        if st.button("退出", use_container_width=True):
            write_system_log(g_client, st.session_state.current_sheet_id, "退出", "-", 0)
            st.session_state.logged_in = False
            st.rerun()

    st.markdown("<div style='font-size: 0.9rem; font-weight: bold; color: #666; margin-top: 15px; margin-bottom: 5px;'>対象サービス切り替え</div>", unsafe_allow_html=True)
    
    if st.session_state.get("show_all_services", False):
        service_options = ["就労継続支援B型", "生活介護", "共同生活援助", "児童発達支援", "放課後等デイサービス"]
    else:
        service_options = ["就労継続支援B型", "共同生活援助"]
        
    st.selectbox("対象サービス", service_options, key="service_type", label_visibility="collapsed")
    
    current_sheet_name = ''
    if st.session_state.service_type == '就労継続支援B型': current_sheet_name = '就労B2'
    elif st.session_state.service_type == '生活介護': current_sheet_name = '生活介護'
    elif st.session_state.service_type == '児童発達支援': current_sheet_name = '児発'
    elif st.session_state.service_type == '放課後等デイサービス': current_sheet_name = '放デイ'
    elif st.session_state.service_type == '共同生活援助': current_sheet_name = 'グループホーム'
        
    current_client_dict = all_client_dict.get(st.session_state.service_type, {})
    client_names = list(current_client_dict.keys()) if current_client_dict else ['未設定']
    enable_record = init_settings.get('enable_daily_record', 'True').lower() == 'true'
    
    closing_day_setting = init_settings.get('closing_day', '末日')
    alert_msg = check_closing_alert(closing_day_setting)
    if alert_msg:
        st.warning(alert_msg)

    if st.session_state.role in ["管理者", "開発管理者"]:
        menu_tabs = ["新規入力", "個人・複数日入力", "全員一括入力", "過去の記録を編集"]
    else:
        menu_tabs = ["新規入力"]

    selected_tab = st.radio("メニュー", menu_tabs, horizontal=True, label_visibility="collapsed", key="selected_tab_menu")
    st.markdown("<hr style='margin-top: 0px; margin-bottom: 20px;'>", unsafe_allow_html=True)

    # ==========================================
    # 1. 新規入力タブ
    # ==========================================
    if selected_tab == "新規入力":
        today_date = datetime.now(JST).date()
        st.write("### 基本情報")
        record_date = st.date_input("記載日", today_date, key="date_new", on_change=on_date_new_change)
        
        target_month = record_date.strftime('%Y-%m')
        setting_key = f"closed_{target_month}_{st.session_state.service_type}"
        is_month_closed = init_settings.get(setting_key, 'False') == 'True'
        if is_month_closed:
            st.error(f"{target_month}月のデータは締め処理が完了しているため、入力・変更はできません。")
        
        st.markdown(f"<h3 style='color: {accent_color}; border-bottom: 2px solid {accent_color}; padding-bottom: 5px; margin-top: 20px; margin-bottom: 10px;'>対象の利用者</h3>", unsafe_allow_html=True)
        client_name = st.selectbox("名前（利用者）", client_names, key="name_new", label_visibility="collapsed")
        
        if is_gh_service:
            # === GH 設定値と個別フォールバックの計算 ===
            gh_lunch_ui_mode = init_settings.get('GH_lunch_ui_mode', '日中滞在時のみ')
            gh_use_indiv = init_settings.get('GH_個別設定有効', 'False').lower() == 'true'
            user_detail = current_client_dict.get(client_name, {})

            # 体温のデフォルト判定
            gh_default_temp = 36.5
            try: gh_default_temp = float(init_settings.get('GH_default_temp', 36.5))
            except ValueError: pass
            
            final_def_temp = gh_default_temp
            if gh_use_indiv and user_detail.get('temp'):
                try: final_def_temp = float(user_detail.get('temp'))
                except ValueError: pass

            # 朝食のデフォルト判定
            gh_default_bf = init_settings.get('GH_default_breakfast', 'True').lower() == 'true'
            final_def_bf = gh_default_bf
            if gh_use_indiv and user_detail.get('bf'):
                bf_val = user_detail.get('bf')
                if bf_val in ['〇', 'TRUE', 'True', 'true']: final_def_bf = True
                elif bf_val in ['×', 'FALSE', 'False', 'false']: final_def_bf = False

            # 夕食のデフォルト判定
            gh_default_dn = init_settings.get('GH_default_dinner', 'True').lower() == 'true'
            final_def_dn = gh_default_dn
            if gh_use_indiv and user_detail.get('dn'):
                dn_val = user_detail.get('dn')
                if dn_val in ['〇', 'TRUE', 'True', 'true']: final_def_dn = True
                elif dn_val in ['×', 'FALSE', 'False', 'false']: final_def_dn = False

            # 睡眠・起床のデフォルト判定
            final_def_bed = user_detail.get('bed', "") if gh_use_indiv else ""
            final_def_wake = user_detail.get('wake', "") if gh_use_indiv else ""
            
            # ★追加：バイタルのデフォルト判定
            final_def_bp_h = user_detail.get('bp_h', "") if gh_use_indiv else ""
            final_def_bp_l = user_detail.get('bp_l', "") if gh_use_indiv else ""
            final_def_pulse = user_detail.get('pulse', "") if gh_use_indiv else ""
            final_def_spo2 = user_detail.get('spo2', "") if gh_use_indiv else ""

            st.write("### 滞在状況と加算事由")
            # 滞在状況
            status_options = ["(通常宿泊)", "体験利用", "外泊", "入院", "欠席"]
            stay_status_disp = st.selectbox("本日の滞在区分（※例外時のみ変更）", status_options, index=0, key="gh_stay_status")
            
            gh_att = "宿泊" if stay_status_disp == "(通常宿泊)" else stay_status_disp
            is_gh_absent = stay_status_disp in ["外泊", "入院", "欠席"]

            # 加算算定トリガー
            col_t1, col_t2 = st.columns(2)
            with col_t1:
                is_daytime_stay = st.checkbox("日中滞在あり（体調不良・休日等）", key="gh_daytime")
                gh_hos = st.checkbox("通院同行あり", key="gh_hosp_acc")
            with col_t2:
                is_away_support = st.checkbox("外泊時・入院時の支援あり", key="gh_away_supp")
                gh_link = st.checkbox("他機関（日中活動先等）との連携あり", key="gh_coord")

            st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)

            gh_m_m = gh_m_n = gh_m_e = ""
            gh_amt_m = gh_amt_n = gh_amt_e = ""
            gh_temp = final_def_temp
            gh_cond = gh_bp_h = gh_bp_l = gh_pulse = gh_spo2 = ""
            gh_med_m = gh_med_n = gh_med_e = gh_med_s = gh_med_t = ""
            gh_bath = gh_exc = gh_bed = gh_wake = gh_sleep = ""

            if is_gh_absent:
                st.info(f"滞在区分が「{stay_status_disp}」のため、食事・バイタル・生活記録の入力項目は非表示になっています。必要な支援や申し送りは「特記事項」に入力してください。")
            else:
                st.write("### 食事提供")
                if init_settings.get('enable_gh_meal_detail', 'True').lower() == 'true':
                    meal_col1, meal_col2, meal_col3 = st.columns(3)
                    with meal_col1:
                        has_bf = st.checkbox("朝食あり", value=final_def_bf, key="gh_has_bf")
                        gh_m_m = "〇" if has_bf else "×"
                        if has_bf: gh_amt_m = str(st.number_input("朝食量", 0, 10, 10, key="gh_amtm_new"))
                    with meal_col2:
                        show_lunch = False
                        if gh_lunch_ui_mode == "常時表示": show_lunch = True
                        elif gh_lunch_ui_mode == "日中滞在時のみ" and is_daytime_stay: show_lunch = True
                        
                        if show_lunch:
                            has_lu = st.checkbox("昼食あり", value=True, key="gh_has_lu")
                            gh_m_n = "〇" if has_lu else "×"
                            if has_lu: gh_amt_n = str(st.number_input("昼食量", 0, 10, 10, key="gh_amtn_new"))
                        else:
                            gh_m_n = "×" # 非表示の時は食べない扱い
                    with meal_col3:
                        has_dn = st.checkbox("夕食あり", value=final_def_dn, key="gh_has_dn")
                        gh_m_e = "〇" if has_dn else "×"
                        if has_dn: gh_amt_e = str(st.number_input("夕食量", 0, 10, 10, key="gh_amte_new"))
                else:
                    gh_meal_simple = st.radio("食事提供(朝・夕)", ["〇", "×"], horizontal=True, key="gh_ms_new")
                    if gh_meal_simple == "〇": gh_amt_m = gh_amt_e = str(st.number_input("食事量", 0, 10, 10, key="gh_amts_new"))
                    gh_m_m = gh_m_e = gh_meal_simple
                    gh_m_n = "×"

                st.write("### 健康・バイタル")
                col_gv1, col_gv2 = st.columns(2)
                with col_gv1: gh_temp = st.number_input("検温 (℃)", 34.0, 43.0, final_def_temp, 0.1, format="%.1f")
                with col_gv2: gh_cond = st.selectbox("体調", cond_opts, index=0)
                
                if init_settings.get('enable_gh_vital_detail', 'True').lower() == 'true':
                    col_gv3, col_gv4, col_gv5, col_gv6 = st.columns(4)
                    with col_gv3: gh_bp_h = st.text_input("血圧(上)", value=final_def_bp_h)
                    with col_gv4: gh_bp_l = st.text_input("血圧(下)", value=final_def_bp_l)
                    with col_gv5: gh_pulse = st.text_input("脈拍", value=final_def_pulse)
                    with col_gv6: gh_spo2 = st.text_input("SpO2", value=final_def_spo2)

                if init_settings.get('enable_gh_medication', 'True').lower() == 'true':
                    st.write("### 服薬管理")
                    col_gmd1, col_gmd2, col_gmd3, col_gmd4 = st.columns(4)
                    with col_gmd1: gh_med_m = st.selectbox("朝", GH_MED_OPTS, index=0)
                    with col_gmd2: gh_med_n = st.selectbox("昼", GH_MED_OPTS, index=2) # デフォ無
                    with col_gmd3: gh_med_e = st.selectbox("夕", GH_MED_OPTS, index=0)
                    with col_gmd4: gh_med_s = st.selectbox("就寝前", GH_MED_OPTS, index=2) # デフォ無
                    gh_med_t = st.text_input("頓服・その他特記")

                if init_settings.get('enable_gh_life_record', 'True').lower() == 'true':
                    st.write("### 生活記録")
                    col_gl1, col_gl2 = st.columns(2)
                    with col_gl1: gh_bath = st.selectbox("入浴", GH_BATH_OPTS, index=0)
                    with col_gl2: gh_exc = st.selectbox("排泄", GH_EXC_OPTS, index=0)

                if init_settings.get('enable_gh_sleep_record', 'True').lower() == 'true':
                    st.write("### 睡眠状況")
                    col_gbs1, col_gbs2, col_gbs3 = st.columns(3)
                    with col_gbs1: gh_bed = st.text_input("就寝時刻 (HH:MM)", value=final_def_bed)
                    with col_gbs2: gh_wake = st.text_input("起床時刻 (HH:MM)", value=final_def_wake)
                    with col_gbs3: gh_sleep = st.selectbox("睡眠状態", GH_SLEEP_OPTS, index=0)

            st.write("### 支援詳細・特記事項")
            gh_sup = st.selectbox("特別な支援", sup_opts, index=0)
            
            col_rem1, col_rem2 = st.columns([10, 1])
            with col_rem1: remarks = st.text_input("特記事項", key='remarks_new')
            with col_rem2:
                st.markdown("<div style='margin-top: 27px;'></div>", unsafe_allow_html=True)
                st.button("x", key="clear_rem_new", on_click=clear_text, args=('remarks_new',))

            status_placeholder_new = st.empty()
            if st.button('記録を保存する', use_container_width=True, type='primary', key="submit_gh", disabled=is_month_closed):
                status_placeholder_new.markdown(SPINNER_HTML, unsafe_allow_html=True)
                
                try:
                    record_df = get_sheet_data(g_client, st.session_state.current_sheet_id, current_sheet_name, current_columns)
                    
                    append_tags = []
                    if is_daytime_stay: append_tags.append("【日中滞在支援】")
                    if is_away_support: append_tags.append("【外泊/入院時支援】")
                    final_remarks = "".join(append_tags) + remarks

                    if record_df is not None:
                        row_dict = {
                            '記載日': record_date.strftime('%Y-%m-%d'), '名前': client_name, '受給者証番号': current_client_dict.get(client_name, {}).get('num', ""), 
                            '出欠状況': gh_att,
                            '朝食提供': "" if is_gh_absent else gh_m_m, '朝食量': "" if is_gh_absent or gh_m_m == "×" else gh_amt_m,
                            '昼食提供': "" if is_gh_absent else gh_m_n, '昼食量': "" if is_gh_absent or gh_m_n == "×" else gh_amt_n,
                            '夕食提供': "" if is_gh_absent else gh_m_e, '夕食量': "" if is_gh_absent or gh_m_e == "×" else gh_amt_e,
                            '検温': "" if is_gh_absent else f"{gh_temp:.1f}", '血圧_上': "" if is_gh_absent else gh_bp_h, '血圧_下': "" if is_gh_absent else gh_bp_l, 
                            '脈拍': "" if is_gh_absent else gh_pulse, 'SpO2': "" if is_gh_absent else gh_spo2, '体調': "" if is_gh_absent else gh_cond,
                            '服薬_朝': "" if is_gh_absent else gh_med_m, '服薬_昼': "" if is_gh_absent else gh_med_n, '服薬_夕': "" if is_gh_absent else gh_med_e, '服薬_就寝前': "" if is_gh_absent else gh_med_s, '頓服': "" if is_gh_absent else gh_med_t,
                            '入浴': "" if is_gh_absent else gh_bath, '排泄': "" if is_gh_absent else gh_exc,
                            '就寝時刻': "" if is_gh_absent else gh_bed, '起床時刻': "" if is_gh_absent else gh_wake, '睡眠状態': "" if is_gh_absent else gh_sleep,
                            '通院同行': ("〇" if gh_hos else ""), '日中活動先連携': ("〇" if gh_link else ""),
                            '特別な支援': gh_sup, '特記事項': final_remarks
                        }
                        new_df = pd.DataFrame([row_dict], columns=current_columns)
                        updated_df = pd.concat([record_df, new_df], ignore_index=True).drop_duplicates(subset=['記載日', '名前'], keep='last').reset_index(drop=True)
                        if update_entire_sheet(g_client, st.session_state.current_sheet_id, current_sheet_name, updated_df):
                            write_system_log(g_client, st.session_state.current_sheet_id, "新規入力", client_name, 1)
                            st.session_state.edit_need_reload = True
                            st.session_state.success_msg = f'{client_name} さんの記録を保存しました'
                            st.rerun()
                        else:
                            st.error("データの更新に失敗しました。シートの列数やアクセス権限をご確認ください。")
                except Exception as e:
                    st.error(f"保存処理中に予期せぬエラーが発生しました: {str(e)}")

        else:
            if 'st_new' not in st.session_state: st.session_state.st_new = init_settings.get('start_time', '10:00')
            if 'et_new' not in st.session_state: st.session_state.et_new = init_settings.get('end_time', '15:00')
            if 'meal_new' not in st.session_state: st.session_state.meal_new = "〇"

            st.write("### 出欠状況")
            full_absent = st.checkbox("欠席", key="full_ab_new", on_change=on_full_attendance_change)
            is_all_absent = full_absent
            
            absent_reason = absent_action = plan_start = plan_end = nakanuke_start = nakanuke_end = tardy_planned = tardy_reason = ""
            planned_absence = is_tardy_early = is_nakanuke = False
            
            if is_all_absent:
                absent_reason = st.selectbox("欠席理由", ABSENT_REASON_OPTS, key="ab_reason_new")
                planned_absence = st.checkbox("本来の利用計画あり（欠席時対応加算等）", key="plan_ab_new")
                if planned_absence:
                    count = check_absence_addition_count(g_client, st.session_state.current_sheet_id, current_sheet_name, client_name, record_date, current_columns)
                    if count >= 4: st.error(f"⚠️ {client_name}さんの「欠席時対応加算」は既に {count} 回算定済みです")
                absent_action = st.text_input("欠席対応", key="ab_action_new")

            st.write("### サービス提供状況")
            col_start, col_end = st.columns(2)
            with col_start: input_start = st.text_input("開始時間 (HH:MM)", disabled=is_all_absent, key="st_new")
            with col_end: input_end = st.text_input("終了時間 (HH:MM)", disabled=is_all_absent, key="et_new")

            col_t1, col_t2 = st.columns(2)
            with col_t1: transport_out = st.radio("送迎往路", to_opts, horizontal=True, key="to_new", disabled=is_all_absent)
            with col_t2: transport_ret = st.radio("送迎復路", tr_opts, horizontal=True, key="tr_new", disabled=is_all_absent)

            meal_provided = st.radio("食事提供", ["〇", "×"], horizontal=True, key="meal_new", disabled=is_all_absent)
            meal_amount_val = st.number_input("食事量", min_value=0, max_value=10, value=10, key="meal_amt_new") if meal_provided == "〇" else ""

            temp_val = 36.5
            excretion_val = condition = engagement = mental = support = ""
            
            if enable_record:
                st.write("### 1日の記録")
                condition = st.selectbox("体調", cond_opts, key="cond_new", disabled=is_all_absent)
                engagement = st.selectbox(eng_label, eng_opts, key="eng_new", disabled=is_all_absent)
                mental = st.selectbox(men_label, men_opts, key="men_new", disabled=is_all_absent)
                support = st.selectbox("特別な支援", sup_opts, key="sup_new", disabled=is_all_absent)

            remarks = st.text_input("特記事項", key='remarks_new', disabled=is_all_absent)
            
            if st.button('記録を保存する', use_container_width=True, type='primary', disabled=is_month_closed):
                st.markdown(SPINNER_HTML, unsafe_allow_html=True)
                try:
                    record_df = get_sheet_data(g_client, st.session_state.current_sheet_id, current_sheet_name, current_columns)
                    if record_df is not None:
                        calc_time = "" if is_all_absent else calc_working_hours(input_start, input_end, nakanuke_start, nakanuke_end)
                        final_remarks = remarks
                        if is_all_absent:
                            final_remarks = f"【欠席理由: {absent_reason}】" + ("【利用計画あり】" if planned_absence else "") + (f"対応: {absent_action}" if absent_action else "") + f" {remarks}"

                        row_dict = {
                            '記載日': record_date.strftime('%Y-%m-%d'), '名前': client_name, '受給者証番号': current_client_dict.get(client_name, {}).get('num', ""), 
                            '出欠状況': "欠席" if is_all_absent else "出席",
                            '開始時間': "" if is_all_absent else input_start, '終了時間': "" if is_all_absent else input_end, '算定時間数': calc_time,
                            '送迎往路': "" if is_all_absent else transport_out, '送迎復路': "" if is_all_absent else transport_ret, 
                            '食事提供': "" if is_all_absent else meal_provided, '食事量': str(meal_amount_val) if meal_provided == "〇" else "",
                            '体調': "" if is_all_absent else condition, eng_label: "" if is_all_absent else engagement, men_label: "" if is_all_absent else mental,
                            '特別な支援': "" if is_all_absent else support, '特記事項': final_remarks,
                            '遅刻・早退': "", '計画': "", '都合': "", '計画開始時刻': "", '計画終了時刻': "", '中抜け開始時刻': "", '中抜け終了時刻': ""
                        }
                        new_df = pd.DataFrame([row_dict], columns=current_columns)
                        updated_df = pd.concat([record_df, new_df], ignore_index=True).drop_duplicates(subset=['記載日', '名前'], keep='last').reset_index(drop=True)
                        if update_entire_sheet(g_client, st.session_state.current_sheet_id, current_sheet_name, updated_df):
                            write_system_log(g_client, st.session_state.current_sheet_id, "新規入力", client_name, 1)
                            st.session_state.edit_need_reload = True
                            st.session_state.success_msg = f'{client_name} さんの実績を記録しました'
                            st.rerun()
                        else:
                            st.error("データの更新に失敗しました。")
                except Exception as e:
                    st.error(f"保存処理中にエラーが発生しました: {str(e)}")

        if st.session_state.role in ["管理者", "開発管理者"]:
            st.markdown("<br><hr><br>", unsafe_allow_html=True)
            if is_month_closed:
                if st.button(f"{target_month}分の締めを解除する", use_container_width=True, key="unclose_edit"):
                    update_system_setting(g_client, st.session_state.current_sheet_id, setting_key, 'False')
                    st.session_state.init_settings[setting_key] = 'False'
                    st.session_state.success_msg = f"{target_month}月の締めを解除しました"
                    st.rerun()
            else:
                if st.button(f"{target_month}分のデータ入力を完了（締め）する", use_container_width=True, type='secondary', key="close_edit"):
                    update_system_setting(g_client, st.session_state.current_sheet_id, setting_key, 'True')
                    st.session_state.init_settings[setting_key] = 'True'
                    notify_email = init_settings.get('notify_email', '')
                    send_closing_email(st.session_state.tenant_name, target_month, st.session_state.service_type, notify_email)
                    st.session_state.success_msg = f"{target_month}月の締め処理を完了し、ロックしました"
                    st.rerun()

    # ==========================================
    # 個人・複数日入力タブ
    # ==========================================
    elif selected_tab == "個人・複数日入力" and st.session_state.role in ["管理者", "開発管理者"]:
        st.write("### 一括登録する内容を設定してください")
        today_date = datetime.now(JST).date()
        batch_dates = st.date_input('対象期間', value=(today_date, today_date), key="date_batch")
        
        target_month = batch_dates[0].strftime('%Y-%m') if len(batch_dates) > 0 else today_date.strftime('%Y-%m')
        setting_key = f"closed_{target_month}_{st.session_state.service_type}"
        is_month_closed = init_settings.get(setting_key, 'False') == 'True'
        if is_month_closed:
            st.error(f"{target_month}月のデータは締め処理が完了しているため、入力・変更はできません。")
            
        col_ex1, col_ex2 = st.columns(2)
        with col_ex1:
            label1 = init_settings.get('exclude_label_1', '')
            exc_1_checked = st.checkbox(label1, value=True, key="exc_1") if label1 and label1 != "なし" else False
        with col_ex2:
            label2 = init_settings.get('exclude_label_2', '')
            exc_2_checked = st.checkbox(label2, value=True, key="exc_2") if label2 and label2 != "なし" else False
        
        st.markdown(f"<h3 style='color: {accent_color}; border-bottom: 2px solid {accent_color}; padding-bottom: 5px; margin-top: 20px; margin-bottom: 10px;'>対象の利用者</h3>", unsafe_allow_html=True)
        b_client_name = st.selectbox('名前（利用者）', client_names, key='name_batch', label_visibility="collapsed")
        
        if is_gh_service:
            # === GH 設定値と個別フォールバックの計算 (一括) ===
            gh_lunch_ui_mode = init_settings.get('GH_lunch_ui_mode', '日中滞在時のみ')
            gh_use_indiv = init_settings.get('GH_個別設定有効', 'False').lower() == 'true'
            b_user_detail = current_client_dict.get(b_client_name, {})

            gh_default_temp = 36.5
            try: gh_default_temp = float(init_settings.get('GH_default_temp', 36.5))
            except ValueError: pass
            
            final_def_temp = gh_default_temp
            if gh_use_indiv and b_user_detail.get('temp'):
                try: final_def_temp = float(b_user_detail.get('temp'))
                except ValueError: pass

            gh_default_bf = init_settings.get('GH_default_breakfast', 'True').lower() == 'true'
            final_def_bf = gh_default_bf
            if gh_use_indiv and b_user_detail.get('bf'):
                bf_val = b_user_detail.get('bf')
                if bf_val in ['〇', 'TRUE', 'True', 'true']: final_def_bf = True
                elif bf_val in ['×', 'FALSE', 'False', 'false']: final_def_bf = False

            gh_default_dn = init_settings.get('GH_default_dinner', 'True').lower() == 'true'
            final_def_dn = gh_default_dn
            if gh_use_indiv and b_user_detail.get('dn'):
                dn_val = b_user_detail.get('dn')
                if dn_val in ['〇', 'TRUE', 'True', 'true']: final_def_dn = True
                elif dn_val in ['×', 'FALSE', 'False', 'false']: final_def_dn = False

            final_def_bed = b_user_detail.get('bed', "") if gh_use_indiv else ""
            final_def_wake = b_user_detail.get('wake', "") if gh_use_indiv else ""
            
            # ★追加：バイタルのデフォルト判定
            final_def_bp_h = b_user_detail.get('bp_h', "") if gh_use_indiv else ""
            final_def_bp_l = b_user_detail.get('bp_l', "") if gh_use_indiv else ""
            final_def_pulse = b_user_detail.get('pulse', "") if gh_use_indiv else ""
            final_def_spo2 = b_user_detail.get('spo2', "") if gh_use_indiv else ""

            st.write("### 滞在状況と加算事由")
            status_options = ["(通常宿泊)", "体験利用", "外泊", "入院", "欠席"]
            gh_b_stay_status = st.selectbox("一括登録する滞在区分（※例外時のみ変更）", status_options, index=0, key="gh_b_stay")
            
            gh_b_att = "宿泊" if gh_b_stay_status == "(通常宿泊)" else gh_b_stay_status
            is_gh_b_absent = gh_b_stay_status in ["外泊", "入院", "欠席"]

            col_gb_t1, col_gb_t2 = st.columns(2)
            with col_gb_t1:
                is_b_daytime_stay = st.checkbox("日中滞在あり（体調不良・休日等）", key="gh_b_daytime")
                gh_b_hos = st.checkbox("通院同行あり", key="gh_b_hos")
            with col_gb_t2:
                is_b_away_support = st.checkbox("外泊時・入院時の支援あり", key="gh_b_away_supp")
                gh_b_link = st.checkbox("他機関（日中活動先等）との連携", key="gh_b_link")

            st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)

            gh_b_m_m = gh_b_m_n = gh_b_m_e = ""
            gh_b_amt_m = gh_b_amt_n = gh_b_amt_e = ""
            gh_b_temp = final_def_temp
            gh_b_cond = gh_b_bp_h = gh_b_bp_l = gh_b_pulse = gh_b_spo2 = ""
            gh_b_med_m = gh_b_med_n = gh_b_med_e = gh_b_med_s = gh_b_med_t = ""
            gh_b_bath = gh_b_exc = gh_b_bed = gh_b_wake = gh_b_sleep = ""

            if is_gh_b_absent:
                st.info(f"滞在区分が「{gh_b_stay_status}」のため、食事・バイタル・生活記録の入力項目は非表示になっています。")
            else:
                st.write("### 食事提供")
                if init_settings.get('enable_gh_meal_detail', 'True').lower() == 'true':
                    col_gbm1, col_gbm2, col_gbm3 = st.columns(3)
                    with col_gbm1:
                        has_b_bf = st.checkbox("朝食あり", value=final_def_bf, key="gh_b_bf")
                        gh_b_m_m = "〇" if has_b_bf else "×"
                        if has_b_bf: gh_b_amt_m = str(st.number_input("朝食量", 0, 10, 10, key="gh_b_amtm"))
                    with col_gbm2:
                        show_b_lunch = False
                        if gh_lunch_ui_mode == "常時表示": show_b_lunch = True
                        elif gh_lunch_ui_mode == "日中滞在時のみ" and is_b_daytime_stay: show_b_lunch = True
                        
                        if show_b_lunch:
                            has_b_lu = st.checkbox("昼食あり", value=True, key="gh_b_lu")
                            gh_b_m_n = "〇" if has_b_lu else "×"
                            if has_b_lu: gh_b_amt_n = str(st.number_input("昼食量", 0, 10, 10, key="gh_b_amtn"))
                        else:
                            gh_b_m_n = "×"
                    with col_gbm3:
                        has_b_dn = st.checkbox("夕食あり", value=final_def_dn, key="gh_b_dn")
                        gh_b_m_e = "〇" if has_b_dn else "×"
                        if has_b_dn: gh_b_amt_e = str(st.number_input("夕食量", 0, 10, 10, key="gh_b_amte"))
                else:
                    gh_b_meal_simple = st.radio("食事提供(朝・夕)", ["〇", "×"], horizontal=True, key="gh_b_ms")
                    if gh_b_meal_simple == "〇": gh_b_amt_m = gh_b_amt_e = str(st.number_input("食事量", 0, 10, 10, key="gh_b_amts"))
                    gh_b_m_m = gh_b_m_e = gh_b_meal_simple
                    gh_b_m_n = "×"

                st.write("### 健康・バイタル")
                col_gbv1, col_gbv2 = st.columns(2)
                with col_gbv1: gh_b_temp = st.number_input("検温 (℃)", 34.0, 43.0, final_def_temp, 0.1, format="%.1f", key="gh_b_temp")
                with col_gbv2: gh_b_cond = st.selectbox("体調", cond_opts, key="gh_b_cond", index=0)
                
                if init_settings.get('enable_gh_vital_detail', 'True').lower() == 'true':
                    col_gbv3, col_gbv4, col_gbv5, col_gbv6 = st.columns(4)
                    with col_gbv3: gh_b_bp_h = st.text_input("血圧(上)", key="gh_b_bph", value=final_def_bp_h)
                    with col_gbv4: gh_b_bp_l = st.text_input("血圧(下)", key="gh_b_bpl", value=final_def_bp_l)
                    with col_gbv5: gh_b_pulse = st.text_input("脈拍", key="gh_b_pulse", value=final_def_pulse)
                    with col_gbv6: gh_b_spo2 = st.text_input("SpO2", key="gh_b_spo2", value=final_def_spo2)

                if init_settings.get('enable_gh_medication', 'True').lower() == 'true':
                    st.write("### 服薬管理")
                    col_gbmd1, col_gbmd2, col_gbmd3, col_gbmd4 = st.columns(4)
                    with col_gbmd1: gh_b_med_m = st.selectbox("朝", GH_MED_OPTS, key="gh_b_medm", index=0)
                    with col_gbmd2: gh_b_med_n = st.selectbox("昼", GH_MED_OPTS, key="gh_b_medn", index=2) # 無
                    with col_gbmd3: gh_b_med_e = st.selectbox("夕", GH_MED_OPTS, key="gh_b_mede", index=0)
                    with col_gbmd4: gh_b_med_s = st.selectbox("就寝前", GH_MED_OPTS, key="gh_b_meds", index=2) # 無
                    gh_b_med_t = st.text_input("頓服・その他特記", key="gh_b_medt")

                if init_settings.get('enable_gh_life_record', 'True').lower() == 'true':
                    st.write("### 生活記録")
                    col_gbl1, col_gbl2 = st.columns(2)
                    with col_gbl1: gh_b_bath = st.selectbox("入浴", GH_BATH_OPTS, key="gh_b_bath", index=0)
                    with col_gbl2: gh_b_exc = st.selectbox("排泄", GH_EXC_OPTS, key="gh_b_exc", index=0)

                if init_settings.get('enable_gh_sleep_record', 'True').lower() == 'true':
                    st.write("### 睡眠状況")
                    col_gbs1, col_gbs2, col_gbs3 = st.columns(3)
                    with col_gbs1: gh_b_bed = st.text_input("就寝時刻 (HH:MM)", key="gh_b_bed", value=final_def_bed)
                    with col_gbs2: gh_b_wake = st.text_input("起床時刻 (HH:MM)", key="gh_b_wake", value=final_def_wake)
                    with col_gbs3: gh_b_sleep = st.selectbox("睡眠状態", GH_SLEEP_OPTS, key="gh_b_sleep", index=0)

            st.write("### 支援詳細・特記事項")
            gh_b_sup = st.selectbox("特別な支援", sup_opts, key="gh_b_sup", index=0)
            
            col_brem1, col_brem2 = st.columns([10, 1])
            with col_brem1: b_remarks = st.text_input("特記事項", key='remarks_batch')
            with col_brem2:
                st.markdown("<div style='margin-top: 27px;'></div>", unsafe_allow_html=True)
                st.button("x", key="clear_rem_batch", on_click=clear_text, args=('remarks_batch',))

            status_placeholder_batch = st.empty()
            if st.button('一括登録する', use_container_width=True, type='primary', key='submit_batch_gh', disabled=is_month_closed):
                if len(batch_dates) != 2:
                    st.warning('開始日と終了日の両方を選択してください')
                else:
                    start_date, end_date = batch_dates
                    if start_date.year != end_date.year or start_date.month != end_date.month:
                        st.error('月を跨ぐ一括登録はできません、同じ月内で期間を指定してください')
                    else:
                        status_placeholder_batch.markdown(SPINNER_HTML, unsafe_allow_html=True)
                        try:
                            record_df = get_sheet_data(g_client, st.session_state.current_sheet_id, current_sheet_name, current_columns)
                            if record_df is not None:
                                new_rows_df = []
                                b_recipient_num = current_client_dict.get(b_client_name, {}).get('num', "")
                                
                                append_tags_b = []
                                if is_b_daytime_stay: append_tags_b.append("【日中滞在支援】")
                                if is_b_away_support: append_tags_b.append("【外泊/入院時支援】")
                                final_remarks_b = "".join(append_tags_b) + b_remarks

                                for i in range((end_date - start_date).days + 1):
                                    current_date = start_date + timedelta(days=i)
                                    exclude_it = False
                                    if exc_1_checked and is_day_excluded(current_date, label1): exclude_it = True
                                    if exc_2_checked and is_day_excluded(current_date, label2): exclude_it = True
                                    if exclude_it: continue

                                    current_row_dict = {
                                        '記載日': current_date.strftime('%Y-%m-%d'), '名前': b_client_name, '受給者証番号': b_recipient_num, 
                                        '出欠状況': gh_b_att,
                                        '朝食提供': "" if is_gh_b_absent else gh_b_m_m, '朝食量': "" if is_gh_b_absent or gh_b_m_m == "×" else gh_b_amt_m,
                                        '昼食提供': "" if is_gh_b_absent else gh_b_m_n, '昼食量': "" if is_gh_b_absent or gh_b_m_n == "×" else gh_b_amt_n,
                                        '夕食提供': "" if is_gh_b_absent else gh_b_m_e, '夕食量': "" if is_gh_b_absent or gh_b_m_e == "×" else gh_b_amt_e,
                                        '検温': "" if is_gh_b_absent else f"{gh_b_temp:.1f}", '血圧_上': "" if is_gh_b_absent else gh_b_bp_h, '血圧_下': "" if is_gh_b_absent else gh_b_bp_l, 
                                        '脈拍': "" if is_gh_b_absent else gh_b_pulse, 'SpO2': "" if is_gh_b_absent else gh_b_spo2, '体調': "" if is_gh_b_absent else gh_b_cond,
                                        '服薬_朝': "" if is_gh_b_absent else gh_b_med_m, '服薬_昼': "" if is_gh_b_absent else gh_b_med_n, '服薬_夕': "" if is_gh_b_absent else gh_b_med_e, '服薬_就寝前': "" if is_gh_b_absent else gh_b_med_s, '頓服': "" if is_gh_b_absent else gh_b_med_t,
                                        '入浴': "" if is_gh_b_absent else gh_b_bath, '排泄': "" if is_gh_b_absent else gh_b_exc,
                                        '就寝時刻': "" if is_gh_b_absent else gh_b_bed, '起床時刻': "" if is_gh_b_absent else gh_b_wake, '睡眠状態': "" if is_gh_b_absent else gh_b_sleep,
                                        '通院同行': ("〇" if gh_b_hos else ""), '日中活動先連携': ("〇" if gh_b_link else ""),
                                        '特別な支援': gh_b_sup, '特記事項': final_remarks_b
                                    }
                                    new_rows_df.append(current_row_dict)
                                
                                if not new_rows_df:
                                    st.warning('登録対象となる日がありません')
                                else:
                                    new_df = pd.DataFrame(new_rows_df, columns=current_columns)
                                    updated_df = pd.concat([record_df, new_df], ignore_index=True).drop_duplicates(subset=['記載日', '名前'], keep='last').reset_index(drop=True)
                                    if update_entire_sheet(g_client, st.session_state.current_sheet_id, current_sheet_name, updated_df):
                                        write_system_log(g_client, st.session_state.current_sheet_id, "個人・複数日入力", b_client_name, len(new_rows_df))
                                        st.session_state.edit_need_reload = True
                                        st.session_state.success_msg = f'{b_client_name} さんの実績を {len(new_rows_df)}件 一括登録しました'
                                        st.rerun()
                                    else:
                                        st.error("データの更新に失敗しました。")
                        except Exception as e:
                            st.error(f"一括登録中にエラーが発生しました: {str(e)}")

        else:
            if 'b_st' not in st.session_state: st.session_state.b_st = init_settings.get('start_time', '10:00')
            if 'b_et' not in st.session_state: st.session_state.b_et = init_settings.get('end_time', '15:00')

            st.write("### 出欠状況")
            b_full_absent = st.checkbox("欠席", key="b_full_ab", on_change=on_b_full_attendance_change)
            
            b_absent_reason = b_absent_action = ""
            b_planned_absence = False
            
            if b_full_absent:
                b_absent_reason = st.selectbox("欠席理由", ABSENT_REASON_OPTS, key="b_ab_reason")
                b_planned_absence = st.checkbox("本来の利用計画あり（欠席時対応加算等）", key="b_plan_ab")
                b_absent_action = st.text_input("欠席対応", key="b_ab_action")

            st.write("### サービス提供状況")
            col_bs, col_be = st.columns(2)
            with col_bs: b_start = st.text_input("開始時間 (HH:MM)", disabled=b_full_absent, key="b_st")
            with col_be: b_end = st.text_input("終了時間 (HH:MM)", disabled=b_full_absent, key="b_et")

            col_bt1, col_bt2 = st.columns(2)
            with col_bt1: b_transport_out = st.radio("送迎往路", to_opts, horizontal=True, key='b_to', disabled=b_full_absent)
            with col_bt2: b_transport_ret = st.radio("送迎復路", tr_opts, horizontal=True, key='b_tr', disabled=b_full_absent)

            b_meal_provided = st.radio("食事提供", ["〇", "×"], horizontal=True, key='b_meal', disabled=b_full_absent)
            b_meal_amount_val = ""
            if not b_full_absent and b_meal_provided == "〇":
                b_meal_amount_val = st.number_input("食事量", min_value=0, max_value=10, value=10, step=1, key="b_meal_amt")

            if enable_record:
                st.write("### 1日の記録")
                b_condition = st.selectbox("体調", cond_opts, key='b_cond', disabled=b_full_absent)
                b_engagement = st.selectbox(eng_label, eng_opts, key='b_eng', disabled=b_full_absent)
                b_mental = st.selectbox(men_label, men_opts, key='b_men', disabled=b_full_absent)
                b_support = st.selectbox("特別な支援", sup_opts, key='b_sup', disabled=b_full_absent)
            else:
                b_condition = b_engagement = b_mental = b_support = ""
            
            b_remarks = st.text_input("特記事項", key='remarks_batch', disabled=b_full_absent)
            
            status_placeholder_batch = st.empty()
            if st.button('一括登録する', use_container_width=True, type='primary', key='submit_batch', disabled=is_month_closed):
                if len(batch_dates) != 2:
                    st.warning('開始日と終了日の両方を選択してください')
                else:
                    start_date, end_date = batch_dates
                    if start_date.year != end_date.year or start_date.month != end_date.month:
                        st.error('月を跨ぐ一括登録はできません、同じ月内で期間を指定してください')
                    else:
                        status_placeholder_batch.markdown(SPINNER_HTML, unsafe_allow_html=True)
                        try:
                            record_df = get_sheet_data(g_client, st.session_state.current_sheet_id, current_sheet_name, current_columns)
                            if record_df is not None:
                                new_rows_df = []
                                b_recipient_num = current_client_dict.get(b_client_name, {}).get('num', "")
                                b_calc_time = "" if b_full_absent else calc_working_hours(b_start, b_end)
                                
                                b_final_remarks = b_remarks
                                if b_full_absent:
                                    b_final_remarks = f"【欠席理由: {b_absent_reason}】" + ("【利用計画あり】" if b_planned_absence else "") + (f"対応: {b_absent_action}" if b_absent_action else "") + f" {b_remarks}"
                                
                                for i in range((end_date - start_date).days + 1):
                                    current_date = start_date + timedelta(days=i)
                                    exclude_it = False
                                    if exc_1_checked and is_day_excluded(current_date, label1): exclude_it = True
                                    if exc_2_checked and is_day_excluded(current_date, label2): exclude_it = True
                                    if exclude_it: continue
                                        
                                    current_row_dict = {
                                        '記載日': current_date.strftime('%Y-%m-%d'), '名前': b_client_name, '受給者証番号': b_recipient_num,
                                        '出欠状況': "欠席" if b_full_absent else "出席",
                                        '開始時間': "" if b_full_absent else b_start, '終了時間': "" if b_full_absent else b_end, '算定時間数': b_calc_time,
                                        '送迎往路': "" if b_full_absent else b_transport_out, '送迎復路': "" if b_full_absent else b_transport_ret,
                                        '食事提供': "" if b_full_absent else b_meal_provided, '食事量': "" if (b_full_absent or b_meal_provided == "×") else str(b_meal_amount_val),
                                        '体調': "" if b_full_absent else b_condition, eng_label: "" if b_full_absent else b_engagement, men_label: "" if b_full_absent else b_mental,
                                        '特別な支援': "" if b_full_absent else b_support, '特記事項': b_final_remarks,
                                        '遅刻・早退': "", '計画': "", '都合': "", '計画開始時刻': "", '計画終了時刻': "", '中抜け開始時刻': "", '中抜け終了時刻': ""
                                    }
                                    new_rows_df.append(current_row_dict)
                                
                                if not new_rows_df:
                                    st.warning('登録対象となる日がありません')
                                else:
                                    new_df = pd.DataFrame(new_rows_df, columns=current_columns)
                                    updated_df = pd.concat([record_df, new_df], ignore_index=True).drop_duplicates(subset=['記載日', '名前'], keep='last').reset_index(drop=True)
                                    if update_entire_sheet(g_client, st.session_state.current_sheet_id, current_sheet_name, updated_df):
                                        write_system_log(g_client, st.session_state.current_sheet_id, "個人・複数日入力", b_client_name, len(new_rows_df))
                                        st.session_state.edit_need_reload = True
                                        st.session_state.success_msg = f'{b_client_name} さんの実績を {len(new_rows_df)}件 一括登録しました'
                                        st.rerun()
                                    else:
                                        st.error("データの更新に失敗しました。")
                        except Exception as e:
                            st.error(f"エラーが発生しました: {str(e)}")

        if st.session_state.role in ["管理者", "開発管理者"]:
            st.markdown("<br><hr><br>", unsafe_allow_html=True)
            if is_month_closed:
                if st.button(f"{target_month}分の締めを解除する", use_container_width=True, key="unclose_batch"):
                    update_system_setting(g_client, st.session_state.current_sheet_id, setting_key, 'False')
                    st.session_state.init_settings[setting_key] = 'False'
                    st.session_state.success_msg = f"{target_month}月の締めを解除しました"
                    st.rerun()
            else:
                if st.button(f"{target_month}分のデータ入力を完了（締め）する", use_container_width=True, type='secondary', key="close_batch"):
                    update_system_setting(g_client, st.session_state.current_sheet_id, setting_key, 'True')
                    st.session_state.init_settings[setting_key] = 'True'
                    notify_email = init_settings.get('notify_email', '')
                    send_closing_email(st.session_state.tenant_name, target_month, st.session_state.service_type, notify_email)
                    st.session_state.success_msg = f"{target_month}月の締め処理を完了し、ロックしました"
                    st.rerun()

    # ==========================================
    # 2. 全員一括入力タブ (管理者以上)
    # ==========================================
    elif selected_tab == "全員一括入力" and st.session_state.role in ["管理者", "開発管理者"]:
        st.write("### 全員一括登録")
        batch_dates_all = st.date_input('対象期間', value=(datetime.now(JST).date(), datetime.now(JST).date()), key="date_all")
        
        target_month = batch_dates_all[0].strftime('%Y-%m') if len(batch_dates_all) > 0 else datetime.now(JST).date().strftime('%Y-%m')
        setting_key = f"closed_{target_month}_{st.session_state.service_type}"
        is_month_closed = init_settings.get(setting_key, 'False') == 'True'
        if is_month_closed:
            st.error(f"{target_month}月のデータは締め処理が完了しているため、入力・変更はできません。")
            
        col_ex1_all, col_ex2_all = st.columns(2)
        with col_ex1_all: exc_1_all_checked = st.checkbox(init_settings.get('exclude_label_1', '土曜日を除外する'), value=True)
        with col_ex2_all: exc_2_all_checked = st.checkbox(init_settings.get('exclude_label_2', '日曜日を除外する'), value=True)
        
        valid_clients = [name for name in client_names if name != '未設定']
        
        if is_gh_service:
            st.info("※グループホームでは、以下の内容で全員分を一括保存します")
            gh_all_att_disp = st.selectbox("出欠状況(デフォルト)", ["(通常宿泊)", "体験利用", "外泊", "入院", "欠席"], index=0)
            gh_all_att = "宿泊" if gh_all_att_disp == "(通常宿泊)" else gh_all_att_disp
            
            if init_settings.get('enable_gh_meal_detail', 'True').lower() == 'true':
                col_gm1, col_gm2, col_gm3 = st.columns(3)
                with col_gm1: gh_all_m_m = st.radio("朝食(デフォ)", ["〇", "×"], horizontal=True, key="gh_all_m")
                with col_gm2: gh_all_m_n = st.radio("昼食(デフォ)", ["〇", "×"], horizontal=True, index=1, key="gh_all_n")
                with col_gm3: gh_all_m_e = st.radio("夕食(デフォ)", ["〇", "×"], horizontal=True, key="gh_all_e")
            else:
                gh_meal_simple = st.radio("食事提供(朝・夕 デフォ)", ["〇", "×"], horizontal=True)
                gh_all_m_m = gh_all_m_e = gh_meal_simple
                gh_all_m_n = "×"

            if init_settings.get('enable_gh_medication', 'True').lower() == 'true':
                gh_all_med = st.radio("服薬一括セット", ["全て済にする", "空欄にする"], horizontal=True)
                
            gh_all_bath = "済" if init_settings.get('enable_gh_life_record', 'True').lower() == 'true' else ""
            
            gh_use_indiv_all = init_settings.get('GH_個別設定有効', 'False').lower() == 'true'
            base_temp_str = str(init_settings.get('GH_default_temp', '36.5'))

            if st.button('全員分を一括登録する', use_container_width=True, type='primary', disabled=is_month_closed):
                st.markdown(SPINNER_HTML, unsafe_allow_html=True)
                try:
                    record_df = get_sheet_data(g_client, st.session_state.current_sheet_id, current_sheet_name, current_columns)
                    if record_df is not None:
                        new_rows_df = []
                        start_date, end_date = batch_dates_all
                        for i in range((end_date - start_date).days + 1):
                            current_date = start_date + timedelta(days=i)
                            if exc_1_all_checked and is_day_excluded(current_date, init_settings.get('exclude_label_1', '')): continue
                            if exc_2_all_checked and is_day_excluded(current_date, init_settings.get('exclude_label_2', '')): continue
                            
                            for c_name in valid_clients:
                                c_detail = current_client_dict.get(c_name, {})
                                
                                # 全員一括でも平熱・就寝・起床・バイタルは個別設定があれば適用する
                                c_temp = base_temp_str
                                if gh_use_indiv_all and c_detail.get('temp'):
                                    c_temp = c_detail.get('temp')
                                c_bed = c_detail.get('bed', "") if gh_use_indiv_all else ""
                                c_wake = c_detail.get('wake', "") if gh_use_indiv_all else ""
                                c_bp_h = c_detail.get('bp_h', "") if gh_use_indiv_all else ""
                                c_bp_l = c_detail.get('bp_l', "") if gh_use_indiv_all else ""
                                c_pulse = c_detail.get('pulse', "") if gh_use_indiv_all else ""
                                c_spo2 = c_detail.get('spo2', "") if gh_use_indiv_all else ""

                                row_dict = {
                                    '記載日': current_date.strftime('%Y-%m-%d'), '名前': c_name, '受給者証番号': c_detail.get('num', ""), 
                                    '出欠状況': gh_all_att,
                                    '朝食提供': gh_all_m_m, '朝食量': "10" if gh_all_m_m == "〇" else "",
                                    '昼食提供': gh_all_m_n, '昼食量': "10" if gh_all_m_n == "〇" else "",
                                    '夕食提供': gh_all_m_e, '夕食量': "10" if gh_all_m_e == "〇" else "",
                                    '検温': c_temp, '血圧_上': c_bp_h, '血圧_下': c_bp_l, '脈拍': c_pulse, 'SpO2': c_spo2, '体調': "良好",
                                    '服薬_朝': "済" if gh_all_med == "全て済にする" else "", 
                                    '服薬_昼': "無" if gh_all_med == "全て済にする" else "", 
                                    '服薬_夕': "済" if gh_all_med == "全て済にする" else "", 
                                    '服薬_就寝前': "無" if gh_all_med == "全て済にする" else "", 
                                    '頓服': "", '入浴': gh_all_bath, '排泄': "普通",
                                    '就寝時刻': c_bed, '起床時刻': c_wake, '睡眠状態': "良眠",
                                    '通院同行': "", '日中活動先連携': "", '特別な支援': "通常支援のみ", '特記事項': ""
                                }
                                new_rows_df.append(row_dict)
                        
                        if new_rows_df:
                            new_df = pd.DataFrame(new_rows_df, columns=current_columns)
                            updated_df = pd.concat([record_df, new_df], ignore_index=True).drop_duplicates(subset=['記載日', '名前'], keep='last').reset_index(drop=True)
                            if update_entire_sheet(g_client, st.session_state.current_sheet_id, current_sheet_name, updated_df):
                                st.session_state.edit_need_reload = True
                                st.session_state.success_msg = f'合計 {len(new_rows_df)}件の実績を一括登録しました'
                                st.rerun()
                            else:
                                st.error("保存に失敗しました。")
                except Exception as e:
                    st.error(f"一括登録中にエラーが発生しました: {str(e)}")

        else:
            col_alls, col_alle = st.columns(2)
            with col_alls: all_start = st.text_input("開始時間 (HH:MM)", key="all_st", value="10:00")
            with col_alle: all_end = st.text_input("終了時間 (HH:MM)", key="all_et", value="15:00")
            
            # 【追加修正箇所】エラー画面に合わせて、送迎・食事の設定項目を追加
            st.write("### サービス提供状況 (デフォルト設定)")
            col_all_t1, col_all_t2 = st.columns(2)
            with col_all_t1: all_transport_out = st.radio("送迎往路", to_opts, horizontal=True, key='all_to')
            with col_all_t2: all_transport_ret = st.radio("送迎復路", tr_opts, horizontal=True, key='all_tr')
            
            all_meal_provided = st.radio("食事提供", ["〇", "×"], horizontal=True, key='all_meal')

            if st.button('全員分を一括登録する', use_container_width=True, type='primary', disabled=is_month_closed):
                st.markdown(SPINNER_HTML, unsafe_allow_html=True)
                try:
                    record_df = get_sheet_data(g_client, st.session_state.current_sheet_id, current_sheet_name, current_columns)
                    if record_df is not None:
                        new_rows_df = []
                        start_date, end_date = batch_dates_all
                        for i in range((end_date - start_date).days + 1):
                            current_date = start_date + timedelta(days=i)
                            for c_name in valid_clients:
                                row_dict = {
                                    '記載日': current_date.strftime('%Y-%m-%d'), '名前': c_name, '受給者証番号': current_client_dict.get(c_name, {}).get('num', ""), 
                                    '出欠状況': "出席", '開始時間': all_start, '終了時間': all_end, '算定時間数': calc_working_hours(all_start, all_end),
                                    # 【修正箇所】固定値から入力値の変数に変更
                                    '送迎往路': all_transport_out, '送迎復路': all_transport_ret, '食事提供': all_meal_provided, '食事量': "10" if all_meal_provided == "〇" else "",
                                    '体調': "良好", eng_label: "集中して取り組めた", men_label: "安定している", '特別な支援': "通常支援のみ", '特記事項': "",
                                    '遅刻・早退': "", '計画': "", '都合': "", '計画開始時刻': "", '計画終了時刻': "", '中抜け開始時刻': "", '中抜け終了時刻': ""
                                }
                                new_rows_df.append(row_dict)
                        if new_rows_df:
                            new_df = pd.DataFrame(new_rows_df, columns=current_columns)
                            updated_df = pd.concat([record_df, new_df], ignore_index=True).drop_duplicates(subset=['記載日', '名前'], keep='last').reset_index(drop=True)
                            if update_entire_sheet(g_client, st.session_state.current_sheet_id, current_sheet_name, updated_df):
                                st.session_state.edit_need_reload = True
                                st.session_state.success_msg = f'合計 {len(new_rows_df)}件の実績を一括登録しました'
                                st.rerun()
                            else:
                                st.error("保存に失敗しました。")
                except Exception as e:
                    st.error(f"エラーが発生しました: {str(e)}")

        if st.session_state.role in ["管理者", "開発管理者"]:
            st.markdown("<br><hr><br>", unsafe_allow_html=True)
            if is_month_closed:
                if st.button(f"{target_month}分の締めを解除する", use_container_width=True, key="unclose_all"):
                    update_system_setting(g_client, st.session_state.current_sheet_id, setting_key, 'False')
                    st.session_state.init_settings[setting_key] = 'False'
                    st.session_state.success_msg = f"{target_month}月の締めを解除しました"
                    st.rerun()
            else:
                if st.button(f"{target_month}分のデータ入力を完了（締め）する", use_container_width=True, type='secondary', key="close_all"):
                    update_system_setting(g_client, st.session_state.current_sheet_id, setting_key, 'True')
                    st.session_state.init_settings[setting_key] = 'True'
                    notify_email = init_settings.get('notify_email', '')
                    send_closing_email(st.session_state.tenant_name, target_month, st.session_state.service_type, notify_email)
                    st.session_state.success_msg = f"{target_month}月の締め処理を完了し、ロックしました"
                    st.rerun()

    # ==========================================
    # 3. 過去の記録を編集 (データエディタ)
    # ==========================================
    elif selected_tab == "過去の記録を編集" and st.session_state.role in ["管理者", "開発管理者"]:
        today = datetime.now(JST).date()
        edit_dates = st.date_input('カレンダーから編集する期間', value=(today, today), key='edit_dates')
        
        if len(edit_dates) == 2:
            start_date, end_date = edit_dates
            
            target_month = start_date.strftime('%Y-%m')
            setting_key = f"closed_{target_month}_{st.session_state.service_type}"
            is_month_closed = init_settings.get(setting_key, 'False') == 'True'
            if is_month_closed:
                st.error(f"{target_month}月のデータは締め処理が完了しているため、入力・変更はできません。")
            
            if ('edit_last_start' not in st.session_state or 
                st.session_state.edit_last_start != start_date or 
                st.session_state.get('edit_last_end') != end_date or
                st.session_state.get('edit_need_reload', False)):
                
                record_df = get_sheet_data(g_client, st.session_state.current_sheet_id, current_sheet_name, current_columns)
                if record_df is None:
                    st.error("スプレッドシートのデータ取得に失敗しました。時間をおいて再度お試しください。")
                    st.session_state.edit_cache = None
                elif not record_df.empty:
                    start_ts = pd.to_datetime(start_date)
                    end_ts = pd.to_datetime(end_date)
                    record_df['比較用日付'] = pd.to_datetime(record_df['記載日'], errors='coerce')
                    mask = (record_df['比較用日付'] >= start_ts) & (record_df['比較用日付'] <= end_ts)
                    target_records = record_df[mask].copy()
                    st.session_state.edit_cache = target_records[current_columns].copy()
                    st.session_state.full_record_df = record_df.copy()
                else:
                    st.session_state.edit_cache = pd.DataFrame(columns=current_columns)
                    st.session_state.full_record_df = record_df
                    
                st.session_state.grid_key = f"edit_grid_{datetime.now().timestamp()}"
                st.session_state.edit_last_start = start_date
                st.session_state.edit_last_end = end_date
                st.session_state.edit_need_reload = False

            if st.session_state.get('edit_cache') is not None:
                if st.session_state.edit_cache.empty:
                    st.warning('指定された期間に記録がありません')
                else:
                    gb = GridOptionsBuilder.from_dataframe(st.session_state.edit_cache)
                    
                    gb.configure_default_column(
                        editable=True, 
                        resizable=True,
                        minWidth=100,
                        suppressSizeToFit=True
                    )
                    
                    gb.configure_column("記載日", pinned='left', width=120)
                    gb.configure_column("名前", pinned='left', width=120, cellEditor='agSelectCellEditor', cellEditorParams={'values': client_names})
                    gb.configure_column("受給者証番号", width=120)
                    
                    if is_gh_service:
                        gb.configure_column("出欠状況", cellEditor='agSelectCellEditor', cellEditorParams={'values': GH_ATTENDANCE_OPTS}, width=110)
                        for c in ["朝食提供", "昼食提供", "夕食提供"]: 
                            gb.configure_column(c, cellEditor='agSelectCellEditor', cellEditorParams={'values': ["〇", "×", ""]}, width=90)
                        for c in ["服薬_朝", "服薬_昼", "服薬_夕", "服薬_就寝前"]: 
                            gb.configure_column(c, cellEditor='agSelectCellEditor', cellEditorParams={'values': GH_MED_OPTS}, width=90)
                        gb.configure_column("体調", cellEditor='agSelectCellEditor', cellEditorParams={'values': cond_opts}, width=120)
                        gb.configure_column("入浴", cellEditor='agSelectCellEditor', cellEditorParams={'values': GH_BATH_OPTS}, width=100)
                        gb.configure_column("排泄", cellEditor='agSelectCellEditor', cellEditorParams={'values': GH_EXC_OPTS}, width=100)
                        gb.configure_column("睡眠状態", cellEditor='agSelectCellEditor', cellEditorParams={'values': GH_SLEEP_OPTS}, width=110)
                    else:
                        gb.configure_column("出欠状況", cellEditor='agSelectCellEditor', cellEditorParams={'values': ["出席", "遅刻・早退", "中抜け", "欠席"]}, width=110)
                        gb.configure_column("開始時間", width=100)
                        gb.configure_column("終了時間", width=100)
                        gb.configure_column("算定時間数", width=100)
                        gb.configure_column("送迎往路", cellEditor='agSelectCellEditor', cellEditorParams={'values': to_opts}, width=100)
                        gb.configure_column("送迎復路", cellEditor='agSelectCellEditor', cellEditorParams={'values': tr_opts}, width=100)
                        gb.configure_column("食事提供", cellEditor='agSelectCellEditor', cellEditorParams={'values': ["〇", "×"]}, width=100)
                        gb.configure_column("食事量", width=90)
                        gb.configure_column("体調", cellEditor='agSelectCellEditor', cellEditorParams={'values': cond_opts}, width=120)
                        gb.configure_column(eng_label, cellEditor='agSelectCellEditor', cellEditorParams={'values': eng_opts}, width=180)
                        gb.configure_column(men_label, cellEditor='agSelectCellEditor', cellEditorParams={'values': men_opts}, width=160)
                        gb.configure_column("特別な支援", cellEditor='agSelectCellEditor', cellEditorParams={'values': sup_opts}, width=180)
                        gb.configure_column("遅刻・早退", cellEditor='agSelectCellEditor', cellEditorParams={'values': ["〇", ""]}, width=110)
                        
                        if st.session_state.service_type == "生活介護" or is_child_service:
                            gb.configure_column("計画", cellEditor='agSelectCellEditor', cellEditorParams={'values': ["計画あり", "計画なし", ""]}, width=110)
                            gb.configure_column("都合", cellEditor='agSelectCellEditor', cellEditorParams={'values': ["利用者都合", "事業所都合", ""]}, width=130)
                            gb.configure_column("計画開始時刻", width=120)
                            gb.configure_column("計画終了時刻", width=120)
                            
                        gb.configure_column("中抜け開始時刻", width=140)
                        gb.configure_column("中抜け終了時刻", width=140)
                            
                        if is_child_service:
                            gb.configure_column("おやつ提供", cellEditor='agSelectCellEditor', cellEditorParams={'values': ["〇", "×"]}, width=110)
                            gb.configure_column("おやつ量", cellEditor='agSelectCellEditor', cellEditorParams={'values': ["完食", "半分", "一口", "食べず"]}, width=110)
                            gb.configure_column("検温", width=90)
                            gb.configure_column("排泄", cellEditor='agSelectCellEditor', cellEditorParams={'values': exc_opts}, width=110)

                    gb.configure_column("特記事項", width=350)

                    jscode = JsCode("""
                    function(params) {
                        var style = {};
                        if (params.node.rowIndex % 2 === 0) {
                            style['backgroundColor'] = '#d4edda';
                        } else {
                            style['backgroundColor'] = '#ffffff';
                        }
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
                    
                    gridOptions = gb.build()
                    
                    response = AgGrid(
                        st.session_state.edit_cache,
                        gridOptions=gridOptions,
                        update_mode=GridUpdateMode.MODEL_CHANGED,
                        data_return_mode=DataReturnMode.AS_INPUT,
                        fit_columns_on_grid_load=False,
                        theme='balham',
                        allow_unsafe_jscode=True,
                        reload_data=False,
                        key=st.session_state.get('grid_key', 'edit_grid')
                    )
                    
                    edited_df = pd.DataFrame(response['data'])
                    
                    status_placeholder_edit = st.empty()
                    
                    if st.button('変更を保存する', type='primary', disabled=is_month_closed):
                        if len(edited_df) != len(st.session_state.edit_cache):
                            st.error(f"⚠️ データ件数に不整合が発生しました（取得:{len(edited_df)}件 / 元データ:{len(st.session_state.edit_cache)}件）。一度画面を更新して再度お試しください。")
                        else:
                            status_placeholder_edit.markdown(SPINNER_HTML, unsafe_allow_html=True)
                            
                            try:
                                record_df = st.session_state.full_record_df.copy()
                                mask = (record_df['比較用日付'] >= pd.to_datetime(start_date)) & (record_df['比較用日付'] <= pd.to_datetime(end_date))
                                record_df = record_df[~mask].copy()
                                
                                for idx in edited_df.index:
                                    name = str(edited_df.at[idx, '名前'])
                                    # 個別辞書から受給者証番号を取得
                                    edited_df.at[idx, '受給者証番号'] = current_client_dict.get(name, {}).get('num', "")
                                    
                                record_df = pd.concat([record_df, edited_df[current_columns]], ignore_index=True)
                                record_df.drop(columns=['比較用日付'], inplace=True, errors='ignore')
                                record_df = record_df.drop_duplicates(subset=['記載日', '名前'], keep='last').reset_index(drop=True)
                                record_df = record_df.sort_values(by=['記載日', '名前']).reset_index(drop=True)
                                
                                if update_entire_sheet(g_client, st.session_state.current_sheet_id, current_sheet_name, record_df):
                                    st.session_state.success_msg = '記録をスプレッドシートに更新しました'
                                    st.session_state.edit_need_reload = True
                                    st.rerun()
                                else:
                                    st.error("データの更新に失敗しました。")
                            except Exception as e:
                                st.error(f"更新処理中にエラーが発生しました: {str(e)}")
                                
            if st.session_state.role in ["管理者", "開発管理者"]:
                st.markdown("<br><hr><br>", unsafe_allow_html=True)
                if is_month_closed:
                    if st.button(f"{target_month}分の締めを解除する", use_container_width=True, key="unclose_edit"):
                        update_system_setting(g_client, st.session_state.current_sheet_id, setting_key, 'False')
                        st.session_state.init_settings[setting_key] = 'False'
                        st.session_state.success_msg = f"{target_month}月の締めを解除しました"
                        st.rerun()
                else:
                    if st.button(f"{target_month}分のデータ入力を完了（締め）する", use_container_width=True, type='secondary', key="close_edit"):
                        update_system_setting(g_client, st.session_state.current_sheet_id, setting_key, 'True')
                        st.session_state.init_settings[setting_key] = 'True'
                        notify_email = init_settings.get('notify_email', '')
                        send_closing_email(st.session_state.tenant_name, target_month, st.session_state.service_type, notify_email)
                        st.session_state.success_msg = f"{target_month}月の締め処理を完了し、ロックしました"
                        st.rerun()

        elif len(edit_dates) == 1:
            st.warning('終了日もカレンダーから選択してください')