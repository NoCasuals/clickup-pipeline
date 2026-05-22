import re
import os
import io
import streamlit as st
import pandas as pd
import plotly.express as px
import gspread
from google.oauth2.service_account import Credentials

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Model Progress Dashboard", layout="wide", initial_sidebar_state="expanded")

hide_st_style = """<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;} div[data-testid="stToolbar"] {visibility: hidden;}</style>"""
st.markdown(hide_st_style, unsafe_allow_html=True)

# --- 2. THE SECURITY GATE (Must be placed before EVERYTHING else) ---
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

# Pull password from URL parameter (?pwd=...)
url_password = st.query_params.get("pwd", "")
# Pull master password from Streamlit Secrets
secret_password = st.secrets.get("DASHBOARD_PASSWORD", "fallback_local_password")

if url_password == secret_password:
    st.session_state["authenticated"] = True

# If auth fails, render the lock screen and kill the script immediately
if not st.session_state["authenticated"]:
    st.title("🔒 Private Operational Dashboard")
    user_input = st.text_input("Enter Access Password:", type="password")
    
    if user_input == secret_password:
        st.session_state["authenticated"] = True
        st.rerun()
    else:
        if user_input:
            st.error("Invalid credentials.")
        st.warning("This directory is restricted. Please authenticate to view.")
        st.stop() # <-- COMPLETELY HALTS THE SCRIPT. Sidebar and data will not load.

# --- 3. DATA FETCHING & CACHING ---
@st.cache_data(ttl=600)
def load_data():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    if os.path.exists("creds.json"):
        creds = Credentials.from_service_account_file("creds.json", scopes=scopes)
    elif "gcp_service_account" in st.secrets:
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    else:
        st.error("Missing Google Credentials.")
        st.stop()

    client = gspread.authorize(creds)
    SHEET_URL = "https://docs.google.com/spreadsheets/d/1RE039NcnPeQtQrvI5zjLyADzAr-ZseBPUq388SxkV-Y/edit"
    sheet = client.open_by_url(SHEET_URL).worksheets()[1] 
    
    raw_data = sheet.get_all_values()
    df = pd.DataFrame(raw_data[1:], columns=raw_data[0])
    df.columns = ["Model Name", "Date", "KPI"]
    
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce').dt.date
    df['KPI'] = pd.to_numeric(df['KPI'], errors='coerce')
    df = df.dropna(subset=['Date', 'KPI'])
    
    df['Project Code'] = df['Model Name'].str.extract(r'(D\d{6})')
    df['Project Code'] = df['Project Code'].fillna('Standalone/Other')
    
    overlap_groups = df.groupby(['Date', 'KPI'])['Model Name'].transform(lambda x: '<br> • '.join(sorted(x.unique())))
    df['Overlapping Models'] = '• ' + overlap_groups
    df['Overlap Count'] = df.groupby(['Date', 'KPI'])['Model Name'].transform('nunique')
    
    df = df.sort_values(by=['Model Name', 'Date'])
    return df

df = load_data()

# --- 4. URL EMBED ROUTING CONTROLS ---
view_mode = st.query_params.get("view", "all").lower()

# --- 5. SIDEBAR CONTROLS & CONFIGURATION ---
st.sidebar.header("📊 Dashboard Settings")
jitter_mode = st.sidebar.checkbox("⚡ Separate Overlapping Points", value=False)
group_by_project = st.sidebar.checkbox("📁 Group Legend by Project Code", value=False)

st.sidebar.markdown("---")
st.sidebar.subheader("🔍 Filters")
all_projects = sorted(df['Project Code'].unique())
selected_projects = st.sidebar.multiselect("Filter by Project Code:", options=all_projects, default=[])
filtered_df = df if not selected_projects else df[df['Project Code'].isin(selected_projects)]

all_models = sorted(filtered_df['Model Name'].unique())
selected_models = st.sidebar.multiselect("Filter by Specific Model:", options=all_models, default=[])
final_df = filtered_df if not selected_models else filtered_df[filtered_df['Model Name'].isin(selected_models)]

# --- 6. DATA PROCESSING & VISUALIZATION ---
if final_df.empty:
    st.warning("No data available for the selected filters.")
else:
    # CHART 1: INDIVIDUAL MODELS
    if view_mode in ["all", "models"]:
        st.title("KPI per Model Over Time")
        unique_model_count = len(final_df['Model Name'].unique())
        calculated_height = max(650, (unique_model_count * 18) + 350)
        
        final_df['Display KPI'] = final_df['KPI']
        if jitter_mode:
            final_df['Display KPI'] = final_df['KPI'] + final_df.groupby(['Date', 'KPI']).cumcount() * 0.003
            
        fig_models = px.line(
