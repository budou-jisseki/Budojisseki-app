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

COLUMNS = [
    '記載日', '名前', '受給者証番号', '出欠状況',
    '開始時間', '終了時間', '算定時間数',
    '送迎往路', '送迎復路', '食事提供', '食事量',
    '体調', '作業の取り組み', '精神や情緒', '特別な支援', '特記事項',
    '遅刻・早退', '計画', '都合', '計画開始時刻', '計画終了時刻'
]

CONDITION_OPTS = ['良好', '普通', '不良', '服薬忘れあり', 'その他']
ENGAGEMENT_OPTS = ['集中して取り組めた', '声かけにより取り組めた', '休みがちだった', '参加できなかった', 'その他']
MENTAL_OPTS = ['安定している', '少し不安定', '気分の落ち込みあり', 'イライラしていた', 'その他']
SUPPORT_OPTS = ['通常支援のみ', '個別面談を実施した', '体調不良による静養対応', '他機関との連絡調整', 'その他']
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
    <strong style="color: #0c5460;">データをスプレッドシートに保存しています。このまま数秒お待ちください...</strong>
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

# ==========================================
# テーマカラーの動的設定
# ==========================================
if st.session_state.service_type == "就労継続支援B型":
    bg_color = "#f0f8ff"
    accent_color = "#1976d2"
else:
    bg_color = "#fff5f0"
    accent_color = "#e65100"

# ==========================================
# デザイン・UIカスタマイズ
# ==========================================
st.markdown(f"""
<style>
	header {{visibility: hidden !important;}}
	footer {{visibility: hidden !important;}}
	[data-testid="stStatusWidget"] {{display: none !important;}}
	div[class^="viewerBadge"] {{display: none !important;}}
	div[class^="styles_viewerBadge"] {{display: none !important;}}
	[data-testid="manage-app-button"] {{display: none !important;}}
	[data-testid="stAppDeployButton"] {{display: none !important;}}

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
    client_dict = {'就労継続支援B型': {}, '生活介護': {}}
    if client is None:
        return client_dict
    try:
        sheet = client.open_by_key(SPREADSHEET_KEY).worksheet(MASTER_SHEET_NAME)
        records = sheet.get_all_records()
        
        if records:
            headers = list(records[0].keys())
            if '就労／生活' not in headers and '就労/生活' not in headers:
                st.warning(f"スプレッドシートの1行目に「就労／生活」という列が見当たりません。現在の列名: {', '.join(headers)}")
                
        for row in records:
            name = str(row.get('利用者名', '')).strip()
            num = str(row.get('受給者証番号', '')).strip()
            category = str(row.get('就労／生活', row.get('就労/生活', ''))).strip()
            
            if name:
                if category == '46':
                    client_dict['就労継続支援B型'][name] = num
                elif category == '22':
                    client_dict['生活介護'][name] = num
    except Exception as e:
        if 'WorksheetNotFound' in str(type(e)):
            try:
                spreadsheet = client.open_by_key(SPREADSHEET_KEY)
                new_sheet = spreadsheet.add_worksheet(title=MASTER_SHEET_NAME, rows="100", cols="3")
                new_sheet.append_row(['利用者名', '受給者証番号', '就労／生活'])
                st.warning(f"スプレッドシートに「{MASTER_SHEET_NAME}」シートを新しく作成しました。")
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
        'absence_mode': 'half',
        'enable_daily_record': 'True',
        'show_absent_action': 'True',
        'staff_password': '1111',
        'admin_password': '9999'
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

def calc_working_hours(start_str, end_str, rest_min_str):
    if not start_str or not end_str:
        return ""
    try:
        start_dt = datetime.strptime(start_str, "%H:%M")
        end_dt = datetime.strptime(end_str, "%H:%M")
        rest_min = int(rest_min_str)
        
        diff_min = (end_dt - start_dt).total_seconds() / 60
        actual_min = max(0, diff_min - rest_min)
        
        h = int(actual_min // 60)
        m = int(actual_min % 60)
        return f"{h:02d}:{m:02d}"
    except Exception:
        return ""

@st.cache_resource
def get_gspread_client():
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    if "gcp_service_account" in st.secrets:
        try:
            creds_dict = json.loads(st.secrets["gcp_service_account"])
            credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            return gspread.authorize(credentials)
        except Exception:
            return None
    elif os.path.exists(JSON_KEY_FILE):
        try:
            credentials = Credentials.from_service_account_file(JSON_KEY_FILE, scopes=scopes)
            return gspread.authorize(credentials)
        except Exception:
            return None
    else:
        try:
            credentials, _ = google.auth.default(scopes=scopes)
            return gspread.authorize(credentials)
        except Exception:
            return None

# ==========================================
# マーキング関連処理
# ==========================================
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

# ==========================================
# Google Sheets 操作関連処理
# ==========================================
def get_sheet_data(client, sheet_name):
    try:
        sheet = client.open_by_key(SPREADSHEET_KEY).worksheet(sheet_name)
        records = sheet.get_all_records()
        if not records:
            return pd.DataFrame(columns=COLUMNS)
        df = pd.DataFrame(records)
        for col in COLUMNS:
            if col not in df.columns:
                df[col] = ''
        df = df.astype(str)
        return df[COLUMNS]
    except Exception as e:
        return pd.DataFrame(columns=COLUMNS)

def update_entire_sheet(client, sheet_name, df, init_settings):
    try:
        sheet = client.open_by_key(SPREADSHEET_KEY).worksheet(sheet_name)
        sheet.clear()
        sheet.update([df.columns.values.tolist()] + df.values.tolist())
        
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
            st.error(f"「{sheet_name}」シートが見つかりません。スプレッドシートに作成してください。")
        else:
            st.error(f"データの一括更新に失敗しました: {e}")
        return False

def clear_text(key):
    if key in st.session_state:
        st.session_state[key] = ""

init_settings = load_init_settings()

# ==========================================
# イベントコールバック処理
# ==========================================
def on_attendance_change():
    am = st.session_state.am_ab_new
    pm = st.session_state.pm_ab_new
    if am and pm:
        st.session_state.st_new = ""
        st.session_state.et_new = ""
        st.session_state.meal_new = "×"
        st.session_state.tardy_new = False
    elif am and not pm:
        st.session_state.st_new = init_settings['pm_start_time']
        st.session_state.et_new = init_settings['end_time']
        st.session_state.meal_new = "×"
    elif pm and not am:
        st.session_state.st_new = init_settings['start_time']
        st.session_state.et_new = init_settings['am_end_time']
        st.session_state.meal_new = "〇"
    else:
        st.session_state.st_new = init_settings['start_time']
        st.session_state.et_new = init_settings['end_time']
        st.session_state.meal_new = "〇"

def on_full_attendance_change():
    if st.session_state.full_ab_new:
        st.session_state.st_new = ""
        st.session_state.et_new = ""
        st.session_state.meal_new = "×"
        st.session_state.tardy_new = False
    else:
        st.session_state.st_new = init_settings['start_time']
        st.session_state.et_new = init_settings['end_time']
        st.session_state.meal_new = "〇"

def on_b_attendance_change():
    am = st.session_state.b_am_ab
    pm = st.session_state.b_pm_ab
    if am and pm:
        st.session_state.b_st = ""
        st.session_state.b_et = ""
        st.session_state.b_meal = "×"
        st.session_state.b_tardy = False
    elif am and not pm:
        st.session_state.b_st = init_settings['pm_start_time']
        st.session_state.b_et = init_settings['end_time']
        st.session_state.b_meal = "×"
    elif pm and not am:
        st.session_state.b_st = init_settings['start_time']
        st.session_state.b_et = init_settings['am_end_time']
        st.session_state.b_meal = "〇"
    else:
        st.session_state.b_st = init_settings['start_time']
        st.session_state.b_et = init_settings['end_time']
        st.session_state.b_meal = "〇"

def on_b_full_attendance_change():
    if st.session_state.b_full_ab:
        st.session_state.b_st = ""
        st.session_state.b_et = ""
        st.session_state.b_meal = "×"
        st.session_state.b_tardy = False
    else:
        st.session_state.b_st = init_settings['start_time']
        st.session_state.b_et = init_settings['end_time']
        st.session_state.b_meal = "〇"

# ==========================================
# メイン画面の初期化
# ==========================================
app_title = f"{st.session_state.service_type} 実績入力" if st.session_state.logged_in else "実績入力システム"
st.markdown(f'<h1 class="main-title">{app_title}</h1>', unsafe_allow_html=True)

g_client = get_gspread_client()
if g_client is None and st.session_state.logged_in:
    st.error("認証情報が取得できません。設定を確認してください。")
    st.stop()

all_client_dict = load_client_master(g_client)

# ==========================================
# ログイン画面
# ==========================================
if not st.session_state.logged_in:
    st.write("### ログイン")
    password = st.text_input("パスワードを入力してください", type="password", autocomplete="new-password")
    
    staff_pw = init_settings.get('staff_password', '1111')
    admin_pw = init_settings.get('admin_password', '9999')
    
    if st.button("ログイン", type="primary", use_container_width=True):
        if password == staff_pw:
            st.session_state.logged_in = True
            st.session_state.role = "一般職員"
            st.rerun()
        elif password == admin_pw:
            st.session_state.logged_in = True
            st.session_state.role = "管理者"
            st.rerun()
        else:
            st.error("パスワードが間違っています")

    st.markdown("<br><hr>", unsafe_allow_html=True)
    st.write("スマホからアクセスする場合")
    app_url = os.environ.get('APP_URL')
    network_url = app_url if app_url else f"http://{get_local_ip()}:8501"
    st.markdown(f"<div style='font-size:0.9rem; color:#666;'>{network_url}</div>", unsafe_allow_html=True)
    st.image(generate_qr(network_url), width=180)

# ==========================================
# メイン画面
# ==========================================
else:
    if st.session_state.success_msg:
        st.success(st.session_state.success_msg)
        st.session_state.success_msg = None

    col1, col2, col3 = st.columns([1.5, 1, 1])
    with col1:
        st.write(f"権限: {st.session_state.role}")
    with col2:
        if st.button('更新', use_container_width=True):
            st.rerun()
    with col3:
        if st.button("退出", use_container_width=True):
            st.session_state.clear()
            st.rerun()

    st.markdown("<div style='font-size: 0.9rem; font-weight: bold; color: #666; margin-top: 15px; margin-bottom: 5px;'>対象サービス切り替え</div>", unsafe_allow_html=True)
    st.selectbox(
        "対象サービス", 
        ["就労継続支援B型", "生活介護"], 
        key="service_type",
        label_visibility="collapsed"
    )
    
    current_sheet_name = '就労B2' if st.session_state.service_type == '就労継続支援B型' else '生活介護'
    current_client_dict = all_client_dict.get(st.session_state.service_type, {})
    client_names = list(current_client_dict.keys()) if current_client_dict else ['未設定']
    enable_record = init_settings.get('enable_daily_record', 'True').lower() == 'true'
    show_absent_action = init_settings.get('show_absent_action', 'True').lower() == 'true'

    if st.session_state.role == "管理者":
        tab_new, tab_batch, tab_all, tab_edit = st.tabs(["新規入力", "個人・複数日入力", "全員一括入力", "過去の記録を編集"])
    else:
        tabs = st.tabs(["新規入力"])
        tab_new = tabs[0]

    # ----------------------------------------
    # 新規入力タブ
    # ----------------------------------------
    with tab_new:
        if 'st_new' not in st.session_state: st.session_state.st_new = init_settings['start_time']
        if 'et_new' not in st.session_state: st.session_state.et_new = init_settings['end_time']
        if 'meal_new' not in st.session_state: st.session_state.meal_new = "〇"

        st.write("### 基本情報")
        record_date = st.date_input("記載日", datetime.now().date(), key="date_new")
        
        st.markdown(f"<h3 style='color: {accent_color}; border-bottom: 2px solid {accent_color}; padding-bottom: 5px; margin-top: 20px; margin-bottom: 10px;'>対象の利用者</h3>", unsafe_allow_html=True)
        client_name = st.selectbox("名前（利用者）", client_names, key="name_new", label_visibility="collapsed")
        
        st.write("### 出欠状況")
        
        if init_settings.get('absence_mode', 'half').lower() == 'full':
            full_absent = st.checkbox("欠席", key="full_ab_new", on_change=on_full_attendance_change)
            if full_absent:
                attendance_status = "全日欠席"
            else:
                attendance_status = "出席"
        else:
            col_ab1, col_ab2 = st.columns(2)
            with col_ab1:
                am_absent = st.checkbox("午前欠席", key="am_ab_new", on_change=on_attendance_change)
            with col_ab2:
                pm_absent = st.checkbox("午後欠席", key="pm_ab_new", on_change=on_attendance_change)
                
            if am_absent and pm_absent:
                attendance_status = "全日欠席"
            elif am_absent:
                attendance_status = "午前欠席"
            elif pm_absent:
                attendance_status = "午後欠席"
            else:
                attendance_status = "出席"
            
        is_all_absent = (attendance_status == "全日欠席")
        
        absent_reason = ""
        absent_action = ""
        if is_all_absent:
            absent_reason = st.selectbox("欠席理由", ABSENT_REASON_OPTS, key="ab_reason_new")
            if show_absent_action:
                absent_action = st.text_input("欠席対応", key="ab_action_new")

        st.write("### 遅刻・早退")
        is_tardy_early = st.checkbox("遅刻・早退", key="tardy_new", disabled=is_all_absent)
        tardy_planned = ""
        tardy_reason = ""
        plan_start = ""
        plan_end = ""
        if is_tardy_early:
            if st.session_state.service_type == "生活介護":
                st.warning("⚠️ 遅刻・早退の時刻を「特記事項」欄に記入してください。")
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
                st.info("※遅刻・早退の理由や詳細は、必要に応じて「特記事項」欄へ記入してください。")

        st.write("### サービス提供状況")
        if is_tardy_early:
            st.warning("⚠️ 実績に合わせて時刻を編集してください")
        col_start, col_end = st.columns(2)
        with col_start:
            input_start = st.text_input("開始時間 (HH:MM)", disabled=is_all_absent, key="st_new")
        with col_end:
            input_end = st.text_input("終了時間 (HH:MM)", disabled=is_all_absent, key="et_new")

        col_t1, col_t2 = st.columns(2)
        with col_t1:
            transport_out = st.radio("送迎往路", ["〇", "×"], horizontal=True, key="to_new", disabled=is_all_absent)
        with col_t2:
            transport_ret = st.radio("送迎復路", ["〇", "×"], horizontal=True, key="tr_new", disabled=is_all_absent)

        meal_provided = st.radio("食事提供", ["〇", "×"], horizontal=True, key="meal_new", disabled=is_all_absent)
        
        meal_amount_val = ""
        if not is_all_absent and meal_provided == "〇":
            meal_amount_val = st.number_input("食事量", min_value=1, max_value=10, value=10, step=1, key="meal_amt_new")

        if enable_record:
            st.write("### 1日の記録")
            condition = st.selectbox("体調", CONDITION_OPTS, key="cond_new", disabled=is_all_absent)
            engagement = st.selectbox("作業の取り組み", ENGAGEMENT_OPTS, key="eng_new", disabled=is_all_absent)
            mental = st.selectbox("精神や情緒", MENTAL_OPTS, key="men_new", disabled=is_all_absent)
            support = st.selectbox("特別な支援", SUPPORT_OPTS, key="sup_new", disabled=is_all_absent)
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
            status_placeholder_new.markdown(SPINNER_HTML, unsafe_allow_html=True)
            
            r_min = "0" if (attendance_status in ["午前欠席", "午後欠席"]) else init_settings['rest_time_min']
            calc_time = "" if is_all_absent else calc_working_hours(input_start, input_end, r_min)
            recipient_num = current_client_dict.get(client_name, "")
            
            final_remarks = remarks
            if is_all_absent:
                final_remarks = f"【欠席理由: {absent_reason}】"
                if show_absent_action and absent_action:
                    final_remarks += f"対応: {absent_action}"
                if remarks:
                    final_remarks += f" / {remarks}"
            
            row_data = [
                record_date.strftime('%Y-%m-%d'), 
                client_name, 
                recipient_num, 
                attendance_status,
                "" if is_all_absent else input_start, 
                "" if is_all_absent else input_end, 
                calc_time,
                "" if is_all_absent else transport_out, 
                "" if is_all_absent else transport_ret, 
                "" if is_all_absent else meal_provided,
                "" if (is_all_absent or meal_provided == "×") else str(meal_amount_val),
                "" if is_all_absent else condition,
                "" if is_all_absent else engagement,
                "" if is_all_absent else mental,
                "" if is_all_absent else support,
                final_remarks,
                "" if is_all_absent else ("〇" if is_tardy_early else ""),
                "" if is_all_absent else (tardy_planned if is_tardy_early else ""),
                "" if is_all_absent else (tardy_reason if is_tardy_early else ""),
                "" if is_all_absent else (plan_start if (is_tardy_early and tardy_planned == "計画あり") else ""),
                "" if is_all_absent else (plan_end if (is_tardy_early and tardy_planned == "計画あり") else "")
            ]
            
            record_df = get_sheet_data(g_client, current_sheet_name)
            new_df = pd.DataFrame([row_data], columns=COLUMNS)
            updated_df = pd.concat([record_df, new_df], ignore_index=True)
            updated_df = updated_df.drop_duplicates(subset=['記載日', '名前'], keep='last').reset_index(drop=True)
            
            if update_entire_sheet(g_client, current_sheet_name, updated_df, init_settings):
                st.session_state.success_msg = f'{client_name} さんの実績を記録しました'
                reset_keys = ['st_new', 'et_new', 'meal_new', 'meal_amt_new', 'am_ab_new', 'pm_ab_new', 'full_ab_new', 'to_new', 'tr_new', 'cond_new', 'eng_new', 'men_new', 'sup_new', 'remarks_new', 'ab_reason_new', 'ab_action_new', 'tardy_new', 't_plan_new', 't_rsn_new', 'p_st_new', 'p_et_new']
                for k in reset_keys:
                    if k in st.session_state:
                        del st.session_state[k]
                st.rerun()

    # ----------------------------------------
    # 管理者のみのタブ
    # ----------------------------------------
    if st.session_state.role == "管理者":
        
        with tab_batch:
            if 'b_st' not in st.session_state: st.session_state.b_st = init_settings['start_time']
            if 'b_et' not in st.session_state: st.session_state.b_et = init_settings['end_time']
            if 'b_meal' not in st.session_state: st.session_state.b_meal = "〇"

            st.write("### 一括登録する内容を設定してください")
            batch_dates = st.date_input('対象期間', value=(datetime.now().date(), datetime.now().date()), key="date_batch")
            
            col_ex1, col_ex2 = st.columns(2)
            with col_ex1:
                exclude_saturday = st.checkbox("土曜日を除外する", value=True, key="exclude_sat")
            with col_ex2:
                exclude_sunday_holiday = st.checkbox("日曜日・祝祭日を除外する", value=True, key="exclude_sun_hol")
            
            st.markdown(f"<h3 style='color: {accent_color}; border-bottom: 2px solid {accent_color}; padding-bottom: 5px; margin-top: 20px; margin-bottom: 10px;'>対象の利用者</h3>", unsafe_allow_html=True)
            b_client_name = st.selectbox('名前（利用者）', client_names, key='name_batch', label_visibility="collapsed")
            
            st.write("### 出欠状況")
            if init_settings.get('absence_mode', 'half').lower() == 'full':
                b_full_absent = st.checkbox("欠席", key="b_full_ab", on_change=on_b_full_attendance_change)
                if b_full_absent:
                    b_attendance = "全日欠席"
                else:
                    b_attendance = "出席"
            else:
                col_bab1, col_bab2 = st.columns(2)
                with col_bab1:
                    b_am_absent = st.checkbox("午前欠席", key="b_am_ab", on_change=on_b_attendance_change)
                with col_bab2:
                    b_pm_absent = st.checkbox("午後欠席", key="b_pm_ab", on_change=on_b_attendance_change)
                    
                if b_am_absent and b_pm_absent:
                    b_attendance = "全日欠席"
                elif b_am_absent:
                    b_attendance = "午前欠席"
                elif b_pm_absent:
                    b_attendance = "午後欠席"
                else:
                    b_attendance = "出席"
                
            is_b_all_absent = (b_attendance == "全日欠席")
            
            b_absent_reason = ""
            b_absent_action = ""
            if is_b_all_absent:
                b_absent_reason = st.selectbox("欠席理由", ABSENT_REASON_OPTS, key="b_ab_reason")
                if show_absent_action:
                    b_absent_action = st.text_input("欠席対応", key="b_ab_action")

            st.write("### 遅刻・早退")
            b_is_tardy_early = st.checkbox("遅刻・早退", key="b_tardy", disabled=is_b_all_absent)
            b_tardy_planned = ""
            b_tardy_reason = ""
            b_plan_start = ""
            b_plan_end = ""
            if b_is_tardy_early:
                if st.session_state.service_type == "生活介護":
                    st.warning("⚠️ 遅刻・早退の時刻を「特記事項」欄に記入してください。")
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
                    st.info("※遅刻・早退の理由や詳細は、必要に応じて「特記事項」欄へ記入してください。")
            
            st.write("### サービス提供状況")
            if b_is_tardy_early:
                st.warning("⚠️ 実績に合わせて時刻を編集してください")
            col_bs, col_be = st.columns(2)
            with col_bs:
                b_start = st.text_input("開始時間 (HH:MM)", disabled=is_b_all_absent, key="b_st")
            with col_be:
                b_end = st.text_input("終了時間 (HH:MM)", disabled=is_b_all_absent, key="b_et")

            col_bt1, col_bt2 = st.columns(2)
            with col_bt1:
                b_transport_out = st.radio("送迎往路", ["〇", "×"], horizontal=True, key='b_to', disabled=is_b_all_absent)
            with col_bt2:
                b_transport_ret = st.radio("送迎復路", ["〇", "×"], horizontal=True, key='b_tr', disabled=is_b_all_absent)

            b_meal_provided = st.radio("食事提供", ["〇", "×"], horizontal=True, key='b_meal', disabled=is_b_all_absent)
            
            b_meal_amount_val = ""
            if not is_b_all_absent and b_meal_provided == "〇":
                b_meal_amount_val = st.number_input("食事量", min_value=1, max_value=10, value=10, step=1, key="b_meal_amt")

            if enable_record:
                st.write("### 1日の記録")
                b_condition = st.selectbox("体調", CONDITION_OPTS, key='b_cond', disabled=is_b_all_absent)
                b_engagement = st.selectbox("作業の取り組み", ENGAGEMENT_OPTS, key='b_eng', disabled=is_b_all_absent)
                b_mental = st.selectbox("精神や情緒", MENTAL_OPTS, key='b_men', disabled=is_b_all_absent)
                b_support = st.selectbox("特別な支援", SUPPORT_OPTS, key='b_sup', disabled=is_b_all_absent)
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
                        st.error('月を跨ぐ一括登録はできません。同じ月内で期間を指定してください。')
                    else:
                        status_placeholder_batch.markdown(SPINNER_HTML, unsafe_allow_html=True)
                        
                        new_rows_df = []
                        b_recipient_num = current_client_dict.get(b_client_name, "")
                        r_min = "0" if (b_attendance in ["午前欠席", "午後欠席"]) else init_settings['rest_time_min']
                        b_calc_time = "" if is_b_all_absent else calc_working_hours(b_start, b_end, r_min)
                        
                        b_final_remarks = b_remarks
                        if is_b_all_absent:
                            b_final_remarks = f"【欠席理由: {b_absent_reason}】"
                            if show_absent_action and b_absent_action:
                                b_final_remarks += f"対応: {b_absent_action}"
                            if b_remarks:
                                b_final_remarks += f" / {b_remarks}"
                        
                        for i in range((end_date - start_date).days + 1):
                            current_date = start_date + timedelta(days=i)
                            
                            is_saturday = (current_date.weekday() == 5)
                            is_sunday_or_holiday = (current_date.weekday() == 6) or jpholiday.is_holiday(current_date)
                            
                            if exclude_saturday and is_saturday:
                                continue
                            if exclude_sunday_holiday and is_sunday_or_holiday:
                                continue
                                
                            if is_saturday:
                                current_start = init_settings.get('SAT_start_time', '10:00')
                                current_end = init_settings.get('SAT_end_time', '12:00')
                                current_calc_time = "" if is_b_all_absent else calc_working_hours(current_start, current_end, r_min)
                            else:
                                current_start = b_start
                                current_end = b_end
                                current_calc_time = b_calc_time
                            
                            new_rows_df.append([
                                current_date.strftime('%Y-%m-%d'),
                                b_client_name,
                                b_recipient_num,
                                b_attendance,
                                "" if is_b_all_absent else current_start,
                                "" if is_b_all_absent else current_end,
                                current_calc_time,
                                "" if is_b_all_absent else b_transport_out,
                                "" if is_b_all_absent else b_transport_ret,
                                "" if is_b_all_absent else b_meal_provided,
                                "" if (is_b_all_absent or b_meal_provided == "×") else str(b_meal_amount_val),
                                "" if is_b_all_absent else b_condition,
                                "" if is_b_all_absent else b_engagement,
                                "" if is_b_all_absent else b_mental,
                                "" if is_b_all_absent else b_support,
                                b_final_remarks,
                                "" if is_b_all_absent else ("〇" if b_is_tardy_early else ""),
                                "" if is_b_all_absent else (b_tardy_planned if b_is_tardy_early else ""),
                                "" if is_b_all_absent else (b_tardy_reason if b_is_tardy_early else ""),
                                "" if is_b_all_absent else (b_plan_start if (b_is_tardy_early and b_tardy_planned == "計画あり") else ""),
                                "" if is_b_all_absent else (b_plan_end if (b_is_tardy_early and b_tardy_planned == "計画あり") else "")
                            ])
                        
                        if not new_rows_df:
                            st.warning('登録対象となる日がありません。（指定期間が全て除外日など）')
                        else:
                            record_df = get_sheet_data(g_client, current_sheet_name)
                            new_df = pd.DataFrame(new_rows_df, columns=COLUMNS)
                            updated_df = pd.concat([record_df, new_df], ignore_index=True)
                            updated_df = updated_df.drop_duplicates(subset=['記載日', '名前'], keep='last').reset_index(drop=True)
                            
                            if update_entire_sheet(g_client, current_sheet_name, updated_df, init_settings):
                                st.session_state.success_msg = f'{b_client_name} さんの実績を {len(new_rows_df)}件 一括登録しました'
                                reset_keys = ['b_st', 'b_et', 'b_meal', 'b_meal_amt', 'b_am_ab', 'b_pm_ab', 'b_full_ab', 'b_to', 'b_tr', 'b_cond', 'b_eng', 'b_men', 'b_sup', 'remarks_batch', 'b_ab_reason', 'b_ab_action', 'b_tardy', 'b_t_plan', 'b_t_rsn', 'b_p_st', 'b_p_et']
                                for k in reset_keys:
                                    if k in st.session_state:
                                        del st.session_state[k]
                                st.rerun()

        with tab_all:
            st.write("### 全員一括登録する内容を設定してください")
            all_date = st.date_input("記載日", datetime.now().date(), key="date_all")
            
            valid_clients = [name for name in client_names if name != '未設定']
            st.info(f"現在選択されているサービス（{st.session_state.service_type}）の登録者全員（{len(valid_clients)}名）に対して、以下の同じ内容で一括登録します。")
            
            if 'all_st' not in st.session_state: st.session_state.all_st = init_settings['start_time']
            if 'all_et' not in st.session_state: st.session_state.all_et = init_settings['end_time']
            if 'all_meal' not in st.session_state: st.session_state.all_meal = "〇"

            st.write("### サービス提供状況 (デフォルト設定)")
            col_alls, col_alle = st.columns(2)
            with col_alls:
                all_start = st.text_input("開始時間 (HH:MM)", key="all_st")
            with col_alle:
                all_end = st.text_input("終了時間 (HH:MM)", key="all_et")

            col_allt1, col_allt2 = st.columns(2)
            with col_allt1:
                all_transport_out = st.radio("送迎往路", ["〇", "×"], horizontal=True, key='all_to')
            with col_allt2:
                all_transport_ret = st.radio("送迎復路", ["〇", "×"], horizontal=True, key='all_tr')

            all_meal_provided = st.radio("食事提供", ["〇", "×"], horizontal=True, key='all_meal')
            
            all_meal_amount_val = ""
            if all_meal_provided == "〇":
                all_meal_amount_val = st.number_input("食事量 (デフォルト)", min_value=1, max_value=10, value=10, step=1, key="all_meal_amt")

            if enable_record:
                st.write("### 1日の記録 (デフォルト設定)")
                all_condition = st.selectbox("体調", CONDITION_OPTS, key='all_cond')
                all_engagement = st.selectbox("作業の取り組み", ENGAGEMENT_OPTS, key='all_eng')
                all_mental = st.selectbox("精神や情緒", MENTAL_OPTS, key='all_men')
                all_support = st.selectbox("特別な支援", SUPPORT_OPTS, key='all_sup')
            else:
                all_condition = ""
                all_engagement = ""
                all_mental = ""
                all_support = ""
            
            status_placeholder_all = st.empty()
            submit_all = st.button(label='全員分を一括登録する', use_container_width=True, type='primary', key='submit_all')
            
            if submit_all:
                if not valid_clients:
                    st.warning('登録対象となる利用者がいません。')
                else:
                    status_placeholder_all.markdown(SPINNER_HTML, unsafe_allow_html=True)
                    
                    new_rows_df = []
                    r_min = init_settings['rest_time_min']
                    all_calc_time = calc_working_hours(all_start, all_end, r_min)
                    
                    for c_name in valid_clients:
                        c_recipient_num = current_client_dict.get(c_name, "")
                        
                        new_rows_df.append([
                            all_date.strftime('%Y-%m-%d'),
                            c_name,
                            c_recipient_num,
                            "出席",
                            all_start,
                            all_end,
                            all_calc_time,
                            all_transport_out,
                            all_transport_ret,
                            all_meal_provided,
                            str(all_meal_amount_val) if all_meal_provided == "〇" else "",
                            all_condition,
                            all_engagement,
                            all_mental,
                            all_support,
                            "",
                            "",
                            "",
                            "",
                            "",
                            ""
                        ])
                    
                    record_df = get_sheet_data(g_client, current_sheet_name)
                    new_df = pd.DataFrame(new_rows_df, columns=COLUMNS)
                    updated_df = pd.concat([record_df, new_df], ignore_index=True)
                    updated_df = updated_df.drop_duplicates(subset=['記載日', '名前'], keep='last').reset_index(drop=True)
                    
                    if update_entire_sheet(g_client, current_sheet_name, updated_df, init_settings):
                        st.session_state.success_msg = f'{len(new_rows_df)}名の実績を一括登録しました。「過去の記録を編集」タブから個別修正を行ってください。'
                        reset_keys = ['all_st', 'all_et', 'all_meal', 'all_meal_amt', 'all_to', 'all_tr', 'all_cond', 'all_eng', 'all_men', 'all_sup']
                        for k in reset_keys:
                            if k in st.session_state:
                                del st.session_state[k]
                        st.rerun()

        with tab_edit:
            today = datetime.now().date()
            edit_dates = st.date_input('カレンダーから編集する期間', value=(today, today), key='edit_dates')
            
            if len(edit_dates) == 2:
                start_date, end_date = edit_dates
                record_df = get_sheet_data(g_client, current_sheet_name)
                
                if not record_df.empty:
                    start_ts = pd.to_datetime(start_date)
                    end_ts = pd.to_datetime(end_date)
                    record_df['比較用日付'] = pd.to_datetime(record_df['記載日'], errors='coerce')
                    mask = (record_df['比較用日付'] >= start_ts) & (record_df['比較用日付'] <= end_ts)
                    
                    target_records = record_df[mask].copy()
                    
                    if target_records.empty:
                        st.warning('指定された期間に記録がありません')
                    else:
                        with st.form(key='edit_form'):
                            edited_df = st.data_editor(
                                target_records[COLUMNS],
                                column_config={
                                    "名前": st.column_config.SelectboxColumn("名前", options=client_names),
                                    "出欠状況": st.column_config.SelectboxColumn("出欠状況", options=["出席", "午前欠席", "午後欠席", "全日欠席"]),
                                    "送迎往路": st.column_config.SelectboxColumn("送迎往路", options=["〇", "×"]),
                                    "送迎復路": st.column_config.SelectboxColumn("送迎復路", options=["〇", "×"]),
                                    "食事提供": st.column_config.SelectboxColumn("食事提供", options=["〇", "×"]),
                                    "食事量": st.column_config.NumberColumn("食事量", min_value=1, max_value=10, step=1),
                                    "体調": st.column_config.SelectboxColumn("体調", options=CONDITION_OPTS),
                                    "作業の取り組み": st.column_config.SelectboxColumn("作業の取り組み", options=ENGAGEMENT_OPTS),
                                    "精神や情緒": st.column_config.SelectboxColumn("精神や情緒", options=MENTAL_OPTS),
                                    "特別な支援": st.column_config.SelectboxColumn("特別な支援", options=SUPPORT_OPTS),
                                    "遅刻・早退": st.column_config.SelectboxColumn("遅刻・早退", options=["〇", ""]),
                                    "計画": st.column_config.SelectboxColumn("計画", options=["計画あり", "計画なし", ""]) if st.session_state.service_type == "生活介護" else None,
                                    "都合": st.column_config.SelectboxColumn("都合", options=["利用者都合", "事業所都合", ""]) if st.session_state.service_type == "生活介護" else None,
                                    "計画開始時刻": st.column_config.TextColumn("計画開始時刻") if st.session_state.service_type == "生活介護" else None,
                                    "計画終了時刻": st.column_config.TextColumn("計画終了時刻") if st.session_state.service_type == "生活介護" else None,
                                },
                                num_rows="dynamic", use_container_width=True, key="data_editor"
                            )
                            
                            status_placeholder_edit = st.empty()
                            save_btn = st.form_submit_button('変更を保存する', type='primary')
                            
                        if save_btn:
                            status_placeholder_edit.markdown(SPINNER_HTML, unsafe_allow_html=True)
                            
                            deleted_indices = set(target_records.index) - set(edited_df.index)
                            if deleted_indices:
                                record_df.drop(index=list(deleted_indices), inplace=True)
                            
                            if len(edited_df) > 0:
                                for idx in edited_df.index:
                                    status = str(edited_df.at[idx, '出欠状況'])
                                    name = str(edited_df.at[idx, '名前'])
                                    
                                    edited_df.at[idx, '受給者証番号'] = current_client_dict.get(name, "")
                                    
                                    if status == "全日欠席":
                                        for col in ['開始時間', '終了時間', '算定時間数', '送迎往路', '送迎復路', '食事提供', '食事量', '体調', '作業の取り組み', '精神や情緒', '特別な支援', '特記事項', '遅刻・早退', '計画', '都合', '計画開始時刻', '計画終了時刻']:
                                            edited_df.at[idx, col] = ''
                                            
                                record_df = record_df.drop(index=edited_df.index)
                                record_df = pd.concat([record_df, edited_df[COLUMNS]], ignore_index=True)
                            
                            record_df.drop(columns=['比較用日付'], inplace=True, errors='ignore')
                            
                            record_df = record_df.drop_duplicates(subset=['記載日', '名前'], keep='last').reset_index(drop=True)
                            
                            if update_entire_sheet(g_client, current_sheet_name, record_df, init_settings):
                                st.session_state.success_msg = '記録をスプレッドシートに更新しました'
                                st.rerun()
                    record_df.drop(columns=['比較用日付'], inplace=True, errors='ignore')
                else:
                    st.warning('スプレッドシートに記録がまだありません')
            elif len(edit_dates) == 1:
                st.warning('終了日もカレンダーから選択してください')