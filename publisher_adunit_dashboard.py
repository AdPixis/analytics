import streamlit as st
import pandas as pd
import numpy as np
import re
from datetime import datetime

# Google Sheets / OAuth
import gspread
from gspread_dataframe import get_as_dataframe
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request

# For storing credentials temporarily (optional)
import pickle
import json

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

# Load Google OAuth client secrets from Streamlit secrets
client_secrets_json = st.secrets["GOOGLE_CLIENT_SECRETS"]
client_config = json.loads(client_secrets_json)

# Page configuration
st.set_page_config(
    page_title="Publisher AdUnit Validation Dashboard",
    page_icon="🔍",
    layout="wide"
)

# --- Cached function to create gspread client ---
@st.cache_resource
def get_gspread_client(creds):
    return gspread.authorize(creds)

# --- Helper functions ---
def excel_col_to_index(col):
    col = col.upper()
    index = 0
    for i, char in enumerate(reversed(col)):
        index += (ord(char) - ord('A') + 1) * (26**i)
    return index - 1

def excel_columns(start: str, end: str):
    def col_to_num(col):
        num = 0
        for c in col:
            num = num * 26 + (ord(c) - ord('A') + 1)
        return num
    def num_to_col(num):
        col = ""
        while num > 0:
            num, remainder = divmod(num - 1, 26)
            col = chr(65 + remainder) + col
        return col
    start_num, end_num = col_to_num(start), col_to_num(end)
    return [num_to_col(i) for i in range(start_num, end_num + 1)]

def load_sheet(gc, url, tab, header=0, columns=None):
    try:
        ws = gc.open_by_url(url).worksheet(tab)
        df = get_as_dataframe(ws, evaluate_formulas=True, header=header)
        df = df.dropna(how="all", axis=0).dropna(how="all", axis=1)
        if header == 0:
            df.columns = df.columns.str.strip()
        if columns:
            col_indices = [excel_col_to_index(c) for c in columns]
            df = df.iloc[:, col_indices]
        return df
    except Exception as e:
        st.error(f"Error loading sheet {tab}: {e}")
        return pd.DataFrame()

def extract_parts(text):
    if pd.isna(text):
        return None, None
    parts = [p.strip() for p in str(text).split(';')]
    placement, upr = None, None
    for p in parts:
        if p.startswith("UPR $"):
            try:
                upr = float(p.replace("UPR $", "").strip())
            except:
                upr = None
        else:
            placement = p
    return placement, upr

def validate_adunit(name, valid_pubs, valid_batches):
    VALID_ADX = ["adpixis"]
    VALID_FORMATS = ["rewarded", "interstitial", "appopen", "banner", "native"]

    name = str(name).strip()
    parts = name.split("_")
    if len(parts) != 5: return "❌ Wrong Parts"
    adx_name, pub_name, fmt, price, batch = parts
    if adx_name not in VALID_ADX: return "❌ Wrong AdX"
    if pub_name not in valid_pubs: return "❌ Wrong Pub"
    if fmt not in VALID_FORMATS: return "❌ Wrong Format"
    if batch not in valid_batches: return "❌ Wrong Batch"
    if " " in name: return "❌ Extra Spaces"
    try: float(price)
    except: return "❌ Wrong Price"
    return "✅ Valid"

def check_upr_exists(actual_floor, ad_unit, adx_df, tolerance=0.01):
    if pd.isna(actual_floor): return False
    adx_rows = adx_df[adx_df['Code'] == ad_unit]
    if adx_rows.empty: return False
    for placement_str in adx_rows['Placements'].dropna():
        upr_matches = re.findall(r"UPR \$\s*([0-9]*\.?[0-9]+)", str(placement_str))
        for upr_str in upr_matches:
            try:
                upr_val = round(float(upr_str), 2)
                if abs(upr_val - round(float(actual_floor), 2)) <= tolerance:
                    return True
            except: continue
    return False

def generate_batch_list(batch_prefix, start, end):
    return [f"{batch_prefix}{i}" for i in range(start, end + 1)]

# --- Google Sign-In flow ---
def authenticate_gsheets():
    if 'creds' not in st.session_state:
        flow = Flow.from_client_config(
            client_config,
            scopes=SCOPES,
            redirect_uri='urn:ietf:wg:oauth:2.0:oob'
        )
        auth_url, _ = flow.authorization_url(prompt='consent')
        st.write("### Sign in with Google to access your Sheets")
        st.write(f"[Click here to sign in]({auth_url})")
        code = st.text_input("Enter the code you received after signing in:")
        if code:
            flow.fetch_token(code=code)
            creds = flow.credentials
            st.session_state['creds'] = creds
        else:
            return None
    else:
        creds = st.session_state['creds']
    return get_gspread_client(creds)

# --- Main App ---
def main():
    st.title("🔍 Publisher AdUnit Validation Dashboard")

    gc = authenticate_gsheets()
    if not gc:
        st.warning("Please authenticate with Google first.")
        return

    # Example: Load a sheet after authentication
    sheet_url = st.text_input("Enter your Google Sheet URL:")
    if sheet_url:
        try:
            sheet = gc.open_by_url(sheet_url).sheet1
            data = sheet.get_all_records()
            st.write("### Sheet Data")
            st.dataframe(data)
        except Exception as e:
            st.error(f"Error loading sheet: {e}")

if __name__ == "__main__":
    main()
