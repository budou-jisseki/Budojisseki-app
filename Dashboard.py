import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import google.auth
import os
import json
from datetime import datetime, timedelta

# ==========================================
# 設定とファイルパス
# ==========================================
JSON_KEY_FILE = 'secret.json'
SPREADSHEET_KEY = '1JQe44mjZAUo2oAyVANerXpgXjeM5z_XvJZIjB_TrN5U'
LOG_SHEET_NAME = 'システムログ'

st.set_page_config(page_title="導入効果シミュレーション", page_icon="📊", layout="wide")

# ==========================================
# データ取得関数
# ==========================================
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

def load_log_data(client):
    """スプレッドシートから本番のログデータを取得"""
    if client is None:
        return pd.DataFrame()
    try:
        sheet = client.open_by_key(SPREADSHEET_KEY).worksheet(LOG_SHEET_NAME)
        records = sheet.get_all_records()
        df = pd.DataFrame(records)
        return df
    except Exception as e:
        return pd.DataFrame()

def generate_dummy_data():
    """営業デモ用のダミーデータを生成（徐々に効率化していくシナリオ）"""
    data = []
    now = datetime.now()
    # 過去4週間のデータを生成
    for week in range(4):
        date_base = now - timedelta(days=(3 - week) * 7)
        # 1週目は1件あたり平均60秒、4週目は平均15秒になるようにシミュレーション
        base_sec_per_item = 60 - (week * 15) 
        
        # 1週間あたり50件の操作があったと仮定
        for i in range(50):
            # 新規入力（1件）と一括入力（10件）を適当に混ぜる
            if i % 5 == 0:
                count = 10
                category = "全員一括入力"
                # 一括入力はさらに1件あたりの時間が短い
                sec = count * (base_sec_per_item * 0.3)
            else:
                count = 1
                category = "新規入力"
                sec = base_sec_per_item
            
            # ゆらぎを追加
            import random
            actual_sec = max(2, int(sec * random.uniform(0.8, 1.2)))
            
            data.append({
                'タイムスタンプ': (date_base + timedelta(hours=i)).strftime('%Y-%m-%d %H:%M:%S'),
                '操作カテゴリ': category,
                '処理件数': count,
                '操作間隔(秒)': actual_sec
            })
    return pd.DataFrame(data)

# ==========================================
# UI: サイドバー（シミュレーション設定）
# ==========================================
st.sidebar.title("⚙️ 導入効果シミュレーション")
st.sidebar.markdown("---")

use_dummy = st.sidebar.checkbox("ダミーデータでデモを表示する", value=True, help="まだ本番データが溜まっていない場合の営業・プレゼン用モードです。")

st.sidebar.markdown("### 従来業務（手作業）の想定")
manual_min_per_item = st.sidebar.slider("1件あたりの手作業時間 (分)", min_value=1.0, max_value=10.0, value=3.0, step=0.5, help="紙への記録と、月末の請求ソフトへの転記にかかっていた想定時間")
hourly_wage = st.sidebar.slider("スタッフの平均時給 (円)", min_value=1000, max_value=3000, value=1200, step=50)

st.sidebar.markdown("### 分析フィルタ")
outlier_sec = st.sidebar.number_input("外れ値除外: 1件あたり最大(秒)", value=300, help="画面を開きっぱなしで放置した等の異常な時間を集計から除外します")

# ==========================================
# データの前処理
# ==========================================
client = get_gspread_client() if not use_dummy else None
raw_df = generate_dummy_data() if use_dummy else load_log_data(client)

if raw_df.empty:
    st.error("データが存在しません。スプレッドシートへのアクセスを確認するか、デモモードをオンにしてください。")
    st.stop()

# 必要な列の型変換
df = raw_df.copy()
df['タイムスタンプ'] = pd.to_datetime(df['タイムスタンプ'], errors='coerce')
df['処理件数'] = pd.to_numeric(df['処理件数'], errors='coerce').fillna(0)
df['操作間隔(秒)'] = pd.to_numeric(df['操作間隔(秒)'], errors='coerce').fillna(0)

# データ入力に関連する操作（処理件数1以上）のみに絞る
df_valid = df[df['処理件数'] > 0].copy()

# 1件あたりの時間を計算し、外れ値を除外
df_valid['1件あたり(秒)'] = df_valid['操作間隔(秒)'] / df_valid['処理件数']
df_valid = df_valid[df_valid['1件あたり(秒)'] <= outlier_sec]

# 分単位に変換
df_valid['操作間隔(分)'] = df_valid['操作間隔(秒)'] / 60
df_valid['1件あたり(分)'] = df_valid['1件あたり(秒)'] / 60

# 週のラベルを作成
df_valid['週'] = df_valid['タイムスタンプ'].dt.to_period('W').apply(lambda r: r.start_time.strftime('%m/%d') + 'の週')

# ==========================================
# 指標の計算
# ==========================================
total_items = df_valid['処理件数'].sum()
actual_total_min = df_valid['操作間隔(分)'].sum()

# 従来の想定
manual_total_min = total_items * manual_min_per_item

# 削減効果
saved_min = manual_total_min - actual_total_min
saved_hours = saved_min / 60
saved_cost = saved_hours * hourly_wage

# ==========================================
# メイン画面表示
# ==========================================
st.title("🚀 IT導入による業務効率化レポート")
st.markdown("日々の記録から請求データ作成までをデジタル化した場合の、**リアルな時間・コスト削減効果**を可視化します。")

if use_dummy:
    st.info("💡 現在は「ダミーデータ」を表示しています。サイドバーのチェックを外すと、実際のスプレッドシートのログを集計します。")

# --- トップパネル (KPI) ---
st.markdown("### 💰 月間の削減インパクト")
col1, col2, col3 = st.columns(3)
with col1:
    st.metric(label="処理した総データ件数", value=f"{int(total_items):,} 件")
with col2:
    st.metric(label="推定 削減時間 (月間)", value=f"{saved_hours:.1f} 時間", delta=f"従来想定: {manual_total_min/60:.1f}時間")
with col3:
    st.metric(label="推定 人件費カット効果", value=f"¥ {int(saved_cost):,}", delta="IT加算要件にも貢献！")

st.markdown("---")

# --- セクション1: 従来との所要時間比較 ---
st.markdown("### ⏱️ 1件あたりの作業時間比較 (従来の手作業 vs アプリ)")
col_chart1, col_text1 = st.columns([2, 1])

# アプリの入力手段ごとの平均を計算
avg_single = df_valid[df_valid['操作カテゴリ'].str.contains('新規入力|編集', na=False)]['1件あたり(分)'].mean()
avg_batch = df_valid[df_valid['操作カテゴリ'].str.contains('一括', na=False)]['1件あたり(分)'].mean()

if pd.isna(avg_single): avg_single = 0
if pd.isna(avg_batch): avg_batch = 0

compare_data = pd.DataFrame({
    '入力方法': ['従来 (手書き+転記)', 'アプリ (個別入力)', 'アプリ (一括機能)'],
    '1件あたりの所要時間(分)': [manual_min_per_item, avg_single, avg_batch]
})

with col_chart1:
    st.bar_chart(compare_data.set_index('入力方法'), use_container_width=True)

with col_text1:
    st.markdown("""
    **営業アピールポイント：**
    * 従来は紙の記録と請求ソフトへの二重入力が発生していました。
    * アプリの「全員一括入力」を使えば、1件あたりの時間はほぼゼロに等しくなります。
    * **「月末の残業消滅」** を強力に後押しするデータです。
    """)

# --- セクション2: 週次の定着度・効率化推移 ---
st.markdown("### 📈 アプリ定着度と効率化の推移 (週次)")
col_chart2, col_text2 = st.columns([2, 1])

# 週ごとの件数と平均時間の推移
weekly_stats = df_valid.groupby('週').agg(
    処理件数=('処理件数', 'sum'),
    平均時間_分=('1件あたり(分)', 'mean')
).reset_index()

with col_chart2:
    st.line_chart(weekly_stats.set_index('週')['平均時間_分'], use_container_width=True)

with col_text2:
    st.markdown("""
    **営業アピールポイント（IT加算・定着率）：**
    * グラフの右肩下がりは、スタッフがシステムに慣れ、**学習効果が表れている証拠**です。
    * 単にシステムを入れただけでなく、「現場でしっかり活用され、結果を出している」という実績として、行政や経営層への強力な報告材料になります。
    """)

# 生データ確認用
with st.expander("📊 集計の元データ (システムログ) を確認する"):
    st.dataframe(df_valid[['タイムスタンプ', '操作カテゴリ', '処理件数', '操作間隔(秒)', '1件あたり(分)']], use_container_width=True)