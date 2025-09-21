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

# Custom CSS for better styling
st.markdown("""
<style>
    .config-section {
        background: #f8f9fa;
        padding: 1.5rem;
        border-radius: 10px;
        margin: 1rem 0;
        border-left: 4px solid #007bff;
    }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        text-align: center;
        margin: 0.5rem 0;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    .warning-card {
        background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        text-align: center;
        margin: 0.5rem 0;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    .success-card {
        background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        text-align: center;
        margin: 0.5rem 0;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    .confirm-button {
        background: linear-gradient(135deg, #56ab2f 0%, #a8e6cf 100%);
        color: white;
        padding: 1rem 2rem;
        border-radius: 10px;
        border: none;
        font-size: 16px;
        font-weight: bold;
        cursor: pointer;
    }
</style>
""", unsafe_allow_html=True)

# Publisher configurations
PUBLISHER_CONFIGS = {
    "crikey": {
        "bulk_url": "https://docs.google.com/spreadsheets/d/1SNG4-nWcm3ClYf3lsC6Kkucx07jukPzAgjAoeiDTz_g/edit?gid=1986199885#gid=1986199885",
        "adx_url": "https://docs.google.com/spreadsheets/d/1SNG4-nWcm3ClYf3lsC6Kkucx07jukPzAgjAoeiDTz_g/edit?gid=1986199885#gid=1986199885",
        "pub_url": "https://docs.google.com/spreadsheets/d/14hobXBFAI8y8iTHMGE8DqvOSImC6TsxZTlZ7V0CeMsQ/edit?gid=0#gid=0",
        "network_code": "22817566290",
        "batch_prefix": "new"
    },
    "psv": {
        "bulk_url": "https://docs.google.com/spreadsheets/d/1b2cuF6n6LrENhQF8Ai5mnHCsURDJiHcNkxJir455920/edit?usp=sharing",
        "adx_url": "https://docs.google.com/spreadsheets/d/1b2cuF6n6LrENhQF8Ai5mnHCsURDJiHcNkxJir455920/edit?usp=sharing",
        "pub_url": "https://docs.google.com/spreadsheets/d/16WQVVND2jjPCBeClKdI8btmVLect_8cDa0zZtq7EkkE/edit?usp=sharing",
        "network_code": "21775744923",
        "batch_prefix": "P"
    }
}

# Common constants
VALID_ADX = ["adpixis"]
VALID_FORMATS = ["rewarded", "interstitial", "appopen", "banner", "native"]

def excel_col_to_index(col):
    """Convert Excel column letters to zero-based index"""
    col = col.upper()
    index = 0
    for i, char in enumerate(reversed(col)):
        index += (ord(char) - ord('A') + 1) * (26**i)
    return index - 1

def excel_columns(start: str, end: str):
    """Generate list of Excel columns from start to end"""
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

@st.cache_resource
def authenticate_gsheets():
    if 'creds' not in st.session_state:
        # Load client secrets from Streamlit secrets or JSON string
        # Example: st.secrets["GOOGLE_CLIENT_SECRETS"] = '{"installed":{...}}'
        client_secrets_json = st.secrets.get("GOOGLE_CLIENT_SECRETS")
        if not client_secrets_json:
            st.error("⚠️ Google client secrets not found in Streamlit secrets.")
            return None

        client_config = json.loads(client_secrets_json)

        flow = Flow.from_client_config(
            client_config,
            scopes=SCOPES,
            redirect_uri='urn:ietf:wg:oauth:2.0:oob'
        )

        # Generate auth URL
        auth_url, _ = flow.authorization_url(prompt='consent')

        st.write("### Sign in with Google to access your Sheets")
        st.write(f"[Click here to sign in]({auth_url})")

        # Ask user to paste the code after signing in
        code = st.text_input("Enter the code you received after signing in:")

        if code:
            flow.fetch_token(code=code)
            creds = flow.credentials
            st.session_state['creds'] = creds
        else:
            return None
    else:
        creds = st.session_state['creds']

    # Authorize gspread client
    gc = gspread.authorize(creds)
    return gc

def load_sheet(_gc, url, tab, header=0, columns=None):
    """Load data from Google Sheet"""
    try:
        ws = _gc.open_by_url(url).worksheet(tab)
        df = get_as_dataframe(ws, evaluate_formulas=True, header=header)
        
        # Drop empty rows/cols
        df = df.dropna(how="all", axis=0).dropna(how="all", axis=1)
        
        # Strip column names if header exists
        if header == 0:
            df.columns = df.columns.str.strip()
        
        if columns:
            col_indices = [excel_col_to_index(c) for c in columns]
            df = df.iloc[:, col_indices]
        
        return df
    except Exception as e:
        st.error(f"Error loading sheet {tab}: {str(e)}")
        return pd.DataFrame()

def extract_parts(text):
    """Extract placement and UPR from text"""
    if pd.isna(text):
        return None, None
    parts = [p.strip() for p in str(text).split(';')]
    placement = None
    upr = None
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
    """Validate ad unit name format"""
    name = str(name).strip()
    parts = name.split("_")
    
    if len(parts) != 5:
        return "❌ Wrong Parts"
    
    adx_name, pub_name, fmt, price, batch = parts
    
    if adx_name not in VALID_ADX: return "❌ Wrong AdX"
    if pub_name not in valid_pubs: return "❌ Wrong Pub"
    if fmt not in VALID_FORMATS: return "❌ Wrong Format"
    if batch not in valid_batches: return "❌ Wrong Batch"
    if " " in name: return "❌ Extra Spaces"
    
    try:
        float(price)
    except:
        return "❌ Wrong Price"
    
    return "✅ Valid"

def check_upr_exists(actual_floor, ad_unit, adx_df, tolerance=0.01):
    """Check if UPR exists in AdX for given ad unit and floor"""
    if pd.isna(actual_floor):
        return False
    
    adx_rows = adx_df[adx_df['Code'] == ad_unit]
    if adx_rows.empty:
        return False
    
    for placement_str in adx_rows['Placements'].dropna():
        upr_matches = re.findall(r"UPR \\$\\s*([0-9]*\\.?[0-9]+)", str(placement_str))
        for upr_str in upr_matches:
            try:
                upr_val = round(float(upr_str), 2)
                if abs(upr_val - round(float(actual_floor), 2)) <= tolerance:
                    return True
            except:
                continue
    return False

def generate_batch_list(batch_prefix, start, end):
    """Generate batch list based on prefix and range"""
    return [f"{batch_prefix}{i}" for i in range(start, end + 1)]

def main():
    st.title("🔍 Publisher AdUnit Validation Dashboard")
    st.markdown("---")
    
    # Initialize session state
    if 'data_loaded' not in st.session_state:
        st.session_state.data_loaded = False
    if 'config_confirmed' not in st.session_state:
        st.session_state.config_confirmed = False
    
    # Configuration Section
    if not st.session_state.config_confirmed:
        st.header("⚙️ Configuration")
        
        with st.container():
            st.markdown('<div class="config-section">', unsafe_allow_html=True)
            
            # Publisher Selection
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("🏢 Publisher Selection")
                selected_publisher = st.selectbox(
                    "Select Publisher",
                    options=list(PUBLISHER_CONFIGS.keys()),
                    index=0,
                    help="Choose the publisher you want to validate"
                )
                
                pub_config = PUBLISHER_CONFIGS[selected_publisher]
                st.info(f"**Network Code:** {pub_config['network_code']}")
                st.info(f"**Batch Prefix:** {pub_config['batch_prefix']}")
            
            with col2:
                st.subheader("📦 Batch Configuration")
                
                batch_start = st.number_input(
                    "Start Batch Number", 
                    min_value=1, 
                    max_value=20, 
                    value=1,
                    help="Starting number for batch range"
                )
                
                batch_end = st.number_input(
                    "End Batch Number", 
                    min_value=1, 
                    max_value=20, 
                    value=6,
                    help="Ending number for batch range"
                )
                
                if batch_start <= batch_end:
                    selected_batches = generate_batch_list(pub_config['batch_prefix'], batch_start, batch_end)
                    st.success(f"**Batches to validate:** {', '.join(selected_batches)}")
                else:
                    st.error("Start batch must be less than or equal to end batch")
                    st.stop()
            
            st.markdown("---")
            
            # Sheet Configuration
            st.subheader("📑 Sheet Configuration")
            
            col3, col4, col5 = st.columns(3)
            
            with col3:
                bulk_tab = st.text_input("Bulk Upload Tab Name", value="Sheet5")
                adx_tab = st.text_input("AdX Tab Name", value="adx")
            
            with col4:
                pub_tab = st.text_input("Publisher Tab Name", value="Sheet 1")
                col_start = st.text_input("Publisher Sheet - Start Column", value="C")
            
            with col5:
                col_end = st.text_input("Publisher Sheet - End Column", value="H")
                st.write("")  # Empty space for alignment
            
            st.markdown("---")
            
            # Configuration Summary
            st.subheader("📋 Configuration Summary")
            
            config_summary = {
                "Publisher": selected_publisher.upper(),
                "Network Code": pub_config['network_code'],
                "Batch Range": f"{pub_config['batch_prefix']}{batch_start} to {pub_config['batch_prefix']}{batch_end}",
                "Total Batches": len(selected_batches),
                "Bulk Tab": bulk_tab,
                "AdX Tab": adx_tab,
                "Publisher Tab": pub_tab,
                "Column Range": f"{col_start} to {col_end}"
            }
            
            col_summary1, col_summary2 = st.columns(2)
            
            with col_summary1:
                for key, value in list(config_summary.items())[:4]:
                    st.write(f"**{key}:** {value}")
            
            with col_summary2:
                for key, value in list(config_summary.items())[4:]:
                    st.write(f"**{key}:** {value}")
            
            st.markdown('</div>', unsafe_allow_html=True)
            
            # Confirm Configuration Button
            st.markdown("---")
            if st.button("✅ Confirm Configuration & Load Data", type="primary", use_container_width=True):
                # Store configuration in session state
                st.session_state.selected_publisher = selected_publisher
                st.session_state.pub_config = pub_config
                st.session_state.selected_batches = selected_batches
                st.session_state.bulk_tab = bulk_tab
                st.session_state.adx_tab = adx_tab
                st.session_state.pub_tab = pub_tab
                st.session_state.col_start = col_start
                st.session_state.col_end = col_end
                st.session_state.config_confirmed = True
                st.rerun()
    
    # Data Loading and Validation Section
    if st.session_state.config_confirmed:
        # Show current configuration at top
        st.subheader("📋 Current Configuration")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.info(f"**Publisher:** {st.session_state.selected_publisher.upper()}")
            st.info(f"**Network Code:** {st.session_state.pub_config['network_code']}")
        
        with col2:
            st.info(f"**Batches:** {len(st.session_state.selected_batches)} selected")
            st.info(f"**Range:** {st.session_state.selected_batches[0]} to {st.session_state.selected_batches[-1]}")
        
        with col3:
            if st.button("🔄 Change Configuration", type="secondary"):
                st.session_state.config_confirmed = False
                st.session_state.data_loaded = False
                st.rerun()
        
        st.markdown("---")
        
        # Authentication check
        st.title("Google Sheets Loader with Sign-In")
        gc = authenticate_gsheets()
    
        if gc:
            try:
                sheet_url = st.text_input("Enter your Google Sheet URL:")
                if sheet_url:
                    sheet = gc.open_by_url(sheet_url).sheet1
                    data = sheet.get_all_records()
                    st.write("### Sheet Data")
                    st.dataframe(data)
            except Exception as e:
                st.error(f"Error loading sheet: {e}")
        else:
            st.warning("Please authenticate with Google first.")
        
        # Load data
        if not st.session_state.data_loaded:
            with st.spinner("🔄 Loading data from Google Sheets..."):
                try:
                    # Load AdX data
                    st.write("📊 Loading AdX data...")
                    adx = load_sheet(gc, st.session_state.pub_config['adx_url'], st.session_state.adx_tab, header=None)
                    if adx.empty:
                        st.error(f"❌ Failed to load AdX data from tab: {st.session_state.adx_tab}")
                        st.stop()
                    
                    # Process AdX data
                    if str(adx.iloc[0,0]).startswith("#Note:"):
                        adx = adx.iloc[1:].reset_index(drop=True)
                    
                    adx.columns = adx.iloc[0]
                    adx = adx[1:].reset_index(drop=True)
                    adx.columns = adx.columns.str.strip()
                    
                    # Check required columns
                    if 'Placements' not in adx.columns or 'Code' not in adx.columns:
                        st.error(f"❌ AdX sheet must have 'Code' and 'Placements' columns. Found: {list(adx.columns)}")
                        st.stop()
                    
                    # Extract placement and UPR
                    adx[['PlacementName', 'UPR']] = adx['Placements'].apply(lambda x: pd.Series(extract_parts(x)))
                    adx['UPR'] = pd.to_numeric(adx['UPR'], errors='coerce').round(2)
                    
                    # Load Bulk data
                    st.write("📊 Loading Bulk data...")
                    bulk = load_sheet(gc, st.session_state.pub_config['bulk_url'], st.session_state.bulk_tab, header=0)
                    if bulk.empty:
                        st.error(f"❌ Failed to load Bulk data from tab: {st.session_state.bulk_tab}")
                        st.stop()
                        
                    bulk.columns = bulk.columns.str.strip()
                    
                    # Check for Actual Floor column
                    if 'Actual Floor' in bulk.columns:
                        actual_floor_col = 'Actual Floor'
                    else:
                        st.error(f"❌ No column named 'Actual Floor' found in Bulk sheet. Available columns: {list(bulk.columns)}")
                        st.stop()
                    
                    bulk[actual_floor_col] = pd.to_numeric(bulk[actual_floor_col], errors='coerce').round(2)
                    
                    # Load Publisher data
                    st.write("📊 Loading Publisher data...")
                    try:
                        selected_columns = excel_columns(st.session_state.col_start, st.session_state.col_end)
                        pub_df = load_sheet(gc, st.session_state.pub_config['pub_url'], st.session_state.pub_tab, header=0, columns=selected_columns)
                    except Exception as e:
                        st.error(f"❌ Error loading publisher data: {str(e)}")
                        st.error(f"Check column range {st.session_state.col_start}-{st.session_state.col_end} and tab name '{st.session_state.pub_tab}'")
                        pub_df = pd.DataFrame()
                    
                    # Store data in session state
                    st.session_state.adx = adx
                    st.session_state.bulk = bulk
                    st.session_state.pub_df = pub_df
                    st.session_state.actual_floor_col = actual_floor_col
                    st.session_state.data_loaded = True
                    
                except Exception as e:
                    st.error(f"❌ Error loading data: {str(e)}")
                    st.stop()
        
        # Process validation if data is loaded
        if st.session_state.data_loaded:
            st.success("✅ Data loaded successfully!")
            
            # Get data from session state
            adx = st.session_state.adx
            bulk = st.session_state.bulk
            pub_df = st.session_state.pub_df
            actual_floor_col = st.session_state.actual_floor_col
            
            with st.spinner("🔍 Processing validations..."):
                # Create valid publishers list
                valid_pubs = [st.session_state.selected_publisher]
                
                # Bulk validation
                bulk['Exists_in_AdX'] = bulk['Ad Unit Name'].isin(adx['Code'])
                bulk['AdUnit_Validation'] = bulk['Ad Unit Name'].apply(
                    lambda x: validate_adunit(x, valid_pubs, st.session_state.selected_batches)
                )
                
                # UPR matching
                bulk['UPR_Match'] = bulk.apply(
                    lambda r: check_upr_exists(r[actual_floor_col], r['Ad Unit Name'], adx, tolerance=0.01), axis=1
                )
                
                # Additional lookups
                adx_placement_lookup = adx.groupby('Code')['PlacementName'].first()
                bulk['PlacementName'] = bulk['Ad Unit Name'].map(adx_placement_lookup).fillna("NaN")
                
                adx_floor_lookup = adx.groupby('Code')['UPR'].first()
                bulk['AdX_Floor'] = bulk['Ad Unit Name'].map(adx_floor_lookup)
                
                bulk['Floor_Diff'] = (bulk[actual_floor_col] - bulk['AdX_Floor']).round(2)
                
                # Issue detection
                bulk['HasIssue'] = (~bulk['Exists_in_AdX']) | (~bulk['UPR_Match']) | (bulk['PlacementName'] == "NaN")
                
                # Publisher validation
                pub_results = []
                if not pub_df.empty:
                    pattern = rf'^/23104024203,{st.session_state.pub_config["network_code"]}/(.+)$'
                    
                    for col in pub_df.columns:
                        for val in pub_df[col].dropna().astype(str).str.strip():
                            entry_result = {"Entry": val, "Column": col, "Validation": "✅"}
                            
                            if re.search(r"\\s", val):
                                entry_result["Validation"] = "❌ Contains space(s)"
                            else:
                                prefix_pattern = rf'^/23104024203,{st.session_state.pub_config["network_code"]}/'
                                if not re.match(prefix_pattern, val):
                                    entry_result["Validation"] = f"❌ Invalid Format or n/w code mismatch"
                                else:
                                    match = re.match(pattern, val)
                                    if match:
                                        adunit_code = match.group(1)
                                        if adunit_code not in adx['Code'].values:
                                            entry_result["Validation"] = "❌ Missing in AdX"
                            
                            pub_results.append(entry_result)
                
                pub_validation_df = pd.DataFrame(pub_results) if pub_results else pd.DataFrame()
            
            # Calculate metrics
            total_entries = len(bulk)
            total_issues = bulk['HasIssue'].sum()
            success_rate = ((total_entries - total_issues) / total_entries * 100) if total_entries > 0 else 0
            pub_issues = (pub_validation_df["Validation"] != "✅").sum() if not pub_validation_df.empty else 0
            
            # Display metrics
            st.header("📊 Validation Results")
            
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.markdown(f"""
                <div class="metric-card">
                    <h3>📊 Total Entries</h3>
                    <h2>{total_entries:,}</h2>
                </div>
                """, unsafe_allow_html=True)
            
            with col2:
                st.markdown(f"""
                <div class="warning-card">
                    <h3>⚠️ Issues Found</h3>
                    <h2>{total_issues:,}</h2>
                </div>
                """, unsafe_allow_html=True)
            
            with col3:
                st.markdown(f"""
                <div class="success-card">
                    <h3>✅ Success Rate</h3>
                    <h2>{success_rate:.1f}%</h2>
                </div>
                """, unsafe_allow_html=True)
            
            with col4:
                st.markdown(f"""
                <div class="warning-card">
                    <h3>🚨 Pub Issues</h3>
                    <h2>{pub_issues:,}</h2>
                </div>
                """, unsafe_allow_html=True)
            
            # Tabs for results
            tab1, tab2 = st.tabs(["🔍 AdUnit Validation", "📈 Publisher Validation"])
            
            with tab1:
                st.subheader("🔍 AdUnit Validation Results")
                
                # Filters
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    show_issues_only = st.checkbox("🚨 Show Issues Only", value=True)
                
                with col2:
                    validation_filter = st.selectbox(
                        "Validation Status",
                        options=["All"] + list(bulk['AdUnit_Validation'].unique()),
                        index=0
                    )
                
                with col3:
                    exists_filter = st.selectbox(
                        "Exists in AdX",
                        options=["All", "Yes", "No"],
                        index=0
                    )
                
                with col4:
                    upr_filter = st.selectbox(
                        "UPR Match",
                        options=["All", "Yes", "No"],
                        index=0
                    )
                
                # Apply filters
                display_df = bulk.copy()
                
                if show_issues_only:
                    display_df = display_df[display_df['HasIssue']]
                
                if validation_filter != "All":
                    display_df = display_df[display_df['AdUnit_Validation'] == validation_filter]
                
                if exists_filter != "All":
                    filter_value = exists_filter == "Yes"
                    display_df = display_df[display_df['Exists_in_AdX'] == filter_value]
                
                if upr_filter != "All":
                    filter_value = upr_filter == "Yes"
                    display_df = display_df[display_df['UPR_Match'] == filter_value]
                
                st.info(f"📊 Showing {len(display_df):,} entries (filtered from {len(bulk):,} total)")
                
                # Display table
                if not display_df.empty:
                    display_columns = ['Ad Unit Name', 'Exists_in_AdX', 'UPR_Match', 'PlacementName', 
                                      actual_floor_col, 'AdX_Floor', 'Floor_Diff', 'AdUnit_Validation']
                    
                    # Format display
                    display_table = display_df[display_columns].copy()
                    display_table['Exists_in_AdX'] = display_table['Exists_in_AdX'].map({True: '✅', False: '❌'})
                    display_table['UPR_Match'] = display_table['UPR_Match'].map({True: '✅', False: '❌'})
                    
                    st.dataframe(display_table, use_container_width=True, height=500)
                    
                    # Download button
                    csv = display_df.to_csv(index=False)
                    st.download_button(
                        label=f"📥 Download {st.session_state.selected_publisher.upper()} AdUnit Results",
                        data=csv,
                        file_name=f'{st.session_state.selected_publisher}_adunit_validation_{datetime.now().strftime("%Y%m%d_%H%M")}.csv',
                        mime='text/csv',
                        type="primary"
                    )
                else:
                    st.warning("No data matches the selected filters.")
            
            with tab2:
                st.subheader("📈 Publisher Validation Results")
                
                if not pub_validation_df.empty:
                    # Show basic metrics
                    valid_count = (pub_validation_df["Validation"] == "✅").sum()
                    invalid_count = (pub_validation_df["Validation"] != "✅").sum()
                    total_pub_entries = len(pub_validation_df)
                    pub_success_rate = (valid_count / total_pub_entries * 100) if total_pub_entries > 0 else 0
                    
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("✅ Valid Entries", valid_count)
                    with col2:
                        st.metric("❌ Invalid Entries", invalid_count) 
                    with col3:
                        st.metric("📊 Success Rate", f"{pub_success_rate:.1f}%")
                    
                    # Show issues if any
                    issues = pub_validation_df[pub_validation_df["Validation"] != "✅"]
                    
                    if not issues.empty:
                        st.subheader("🔎 Publisher Issues")
                        
                        # Search functionality
                        search_term = st.text_input("🔍 Search in entries:", placeholder="Enter search term...")
                        
                        if search_term:
                            issues = issues[issues["Entry"].str.contains(search_term, case=False, na=False)]
                        
                        if not issues.empty:
                            st.dataframe(issues, use_container_width=True, height=400)
                            
                            # Download button
                            csv = issues.to_csv(index=False)
                            st.download_button(
                                label=f"📥 Download {st.session_state.selected_publisher.upper()} Publisher Issues",
                                data=csv,
                                file_name=f'{st.session_state.selected_publisher}_publisher_issues_{datetime.now().strftime("%Y%m%d_%H%M")}.csv',
                                mime='text/csv'
                            )
                        else:
                            st.info("No issues match your search criteria.")
                    else:
                        st.success("🎉 No publisher validation issues found!")
                    
                    # Sample valid entries
                    valid_entries = pub_validation_df[pub_validation_df["Validation"] == "✅"].head(10)
                    if not valid_entries.empty:
                        with st.expander("✅ Sample Valid Entries"):
                            st.dataframe(valid_entries, use_container_width=True)
                else:
                    st.warning(f"No publisher data available for validation.")

if __name__ == "__main__":
    main()
