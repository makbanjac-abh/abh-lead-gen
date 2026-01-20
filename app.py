import streamlit as st
import pandas as pd
from playwright.sync_api import sync_playwright
import time
import requests
import re
import random
from datetime import datetime

# --- CONFIGURATION ---
st.set_page_config(page_title="ABH Lead Generator", layout="wide")
OLLAMA_MODEL = "llama3.2"

# --- HELPER FUNCTIONS ---
def check_ollama():
    try:
        requests.get('http://localhost:11434')
        return True
    except:
        return False

def query_ollama(prompt):
    try:
        response = requests.post('http://localhost:11434/api/generate', json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1}
        })
        return response.json().get('response', '').strip()
    except:
        return "AI Error"

def clean_employee_count(text):
    prompt = f"Extract the single integer number of employees from: '{text[:500]}'. Return ONLY digits (e.g. 5000). If none, return 0."
    res = query_ollama(prompt)
    digits = re.sub(r'\D', '', res)
    return int(digits) if digits else 0

def analyze_job(text):
    prompt = f"""
    Analyze this job text. Extract:
    1. Tech Stack (Top 5 tools)
    2. Focus (1 sentence goal)
    If invalid/error page, return "INVALID".
    
    Format:
    Tech: [List]
    Focus: [Sentence]
    
    Text: {text[:6000]}
    """
    return query_ollama(prompt)

# --- MAIN APP UI ---
st.title("Atlantbh Lead Generator")
st.markdown("Scraper je trenutno podešen za Data Engineer enterprise poslove sa **Workday** platformom.")

# Sidebar Controls
with st.sidebar:
    st.header("Search Settings")
    role_input = st.text_input("Job Role", value="Data Engineer")
    region_input = st.selectbox("Region", ["EU OR \"United States\"", "EU", "\"United States\"", "\"United Kingdom\""])
    max_pages = st.slider("Max Google Pages to Scrape", 1, 10, 3)
    
    st.divider()
    
    st.subheader("AI Status")
    if check_ollama():
        st.success(f"🟢 Ollama ({OLLAMA_MODEL}) Connected")
        ai_ready = True
    else:
        st.error("🔴 Ollama Disconnected")
        st.info("Run 'ollama serve' in terminal")
        ai_ready = False

# Session State to hold data
if 'results' not in st.session_state:
    st.session_state.results = []

# --- THE SCRAPER LOGIC ---
start_btn = st.button("Start Lead Generation", type="primary", disabled=not ai_ready)

if start_btn:
    st.session_state.results = [] # Clear old results
    search_query = f'site:myworkdayjobs.com {role_input} ({region_input})'
    
    status_box = st.status("Initializing Browser...", expanded=True)
    table_placeholder = st.empty()
    progress_bar = st.progress(0)
    
    with sync_playwright() as p:
        # Launch Browser
        status_box.write("Launching Chrome...")
        browser = p.chromium.launch(headless=False, args=['--disable-blink-features=AutomationControlled'])
        page = browser.new_page()
        
        # Google Search
        status_box.write(f"Searching Google for: {role_input}...")
        page.goto("https://www.google.com")
        
        # Cookie Handler
        try:
            page.get_by_role("button", name=lambda t: t in ["Reject all", "Reject", "Deny", "Odbij sve"], exact=False).first.click(timeout=2000)
        except: pass

        try:
            page.wait_for_selector('textarea[name="q"]', timeout=5000)
            page.fill('textarea[name="q"]', search_query)
            page.press('textarea[name="q"]', "Enter")
        except:
            st.error("Could not type in search bar.")

        # SMART CAPTCHA WAIT
        status_box.write("⚠️ Checking for Captcha... (Solve it in the browser if you see one!)")
        # We wait indefinitely for the results container (#search) to appear
        # If user is solving captcha, this line waits. Once solved, it proceeds.
        try:
            page.wait_for_selector('#search', timeout=0) 
        except:
            pass
            
        status_box.write("✅ Search Results Found! Scraping links...")
        
        # 1. Harvest Links
        raw_leads = []
        for i in range(max_pages):
            status_box.write(f"Scraping Google Page {i+1}/{max_pages}...")
            links = page.locator('a[href*="myworkdayjobs.com"]').all()
            
            for link in links:
                try:
                    url = link.get_attribute("href")
                    if "google.com" not in url and "//" in url:
                        company = url.split("//")[1].split(".")[0].capitalize()
                        if company not in ["Www", "Myworkdayjobs"]:
                            raw_leads.append({"Company": company, "URL": url})
                except: continue
            
            # Next Page
            if page.locator("#pnnext").is_visible():
                page.locator("#pnnext").click()
                time.sleep(random.uniform(2, 4))
            else:
                break
        
        # Deduplicate
        df_raw = pd.DataFrame(raw_leads).drop_duplicates(subset=["Company"])
        leads = df_raw.to_dict('records')
        total_leads = len(leads)
        status_box.write(f"Found {total_leads} unique companies. Starting AI Analysis...")
        
        # 2. Analyze & Enrich
        processed_data = []
        
        for idx, lead in enumerate(leads):
            # Update UI
            progress = (idx + 1) / total_leads
            progress_bar.progress(progress)
            status_box.write(f"[{idx+1}/{total_leads}] Analyzing **{lead['Company']}**...")
            
            try:
                # Visit Job
                page.goto(lead['URL'], timeout=10000)
                page.wait_for_load_state("domcontentloaded")
                time.sleep(1)
                
                # Get Text
                try: text = page.locator('[data-automation-id="jobPostingDescription"]').inner_text(timeout=1000)
                except: text = page.inner_text("body")[:5000]
                
                # AI Analyze
                analysis = analyze_job(text)
                if "INVALID" in analysis:
                    continue # Skip bad leads
                lead['Analysis'] = analysis
                
                # Google Employee Count
                status_box.write(f"Checking size of {lead['Company']}...")
                page.goto(f"https://www.google.com/search?q={lead['Company']}+number+of+employees")
                try:
                    page.wait_for_selector('#search', timeout=5000)
                    snippet = page.inner_text("#search")[:1000]
                    count = clean_employee_count(snippet)
                except:
                    count = 0
                lead['Employees'] = count
                
                processed_data.append(lead)
                
                # Update Live Table
                st.session_state.results = processed_data
                df_live = pd.DataFrame(processed_data)
                # Sort by employees for the live view
                if not df_live.empty:
                    df_live = df_live.sort_values(by="Employees", ascending=False)
                    table_placeholder.dataframe(df_live, use_container_width=True)
                
            except Exception as e:
                print(e)
                continue
                
        browser.close()
        status_box.update(label="✅ Scraping Complete!", state="complete", expanded=False)

# --- EXPORT SECTION ---
if st.session_state.results:
    st.divider()
    df_final = pd.DataFrame(st.session_state.results)
    if not df_final.empty:
        df_final = df_final.sort_values(by="Employees", ascending=False)
        
        col1, col2 = st.columns([1, 1])
        with col1:
            st.metric("Total Leads", len(df_final))
        with col2:
            # CSV Download Button
            csv = df_final.to_csv(index=False).encode('utf-8')
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
            st.download_button(
                label="📥 Download CSV",
                data=csv,
                file_name=f"leads_{timestamp}.csv",
                mime="text/csv",
                type="primary"
            )