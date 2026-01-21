import streamlit as st
import pandas as pd
from playwright.sync_api import sync_playwright
import time
import requests
import re
import random
import os
from datetime import datetime

# --- CONFIGURATION ---
st.set_page_config(
    page_title="ABH Lead Generator",
    page_icon="assets/logo.png",
    layout="wide"
)

st.markdown("""
    <style>
        /* This removes the massive top padding */
        .block-container {
            padding-top: 2.5rem;
            padding-bottom: 5rem;
        }
        
        /* Sticky Footer Styling */
        .footer {
            position: fixed;
            left: 0;
            bottom: 0;
            width: 100%;
            background-color: rgba(255, 255, 255, 0.8);
            backdrop-filter: blur(10px);
            color: #888;
            text-align: center;
            padding: 15px 0;
            font-size: 0.85em;
            font-family: 'Inter', sans-serif;
            border-top: 1px solid rgba(0, 0, 0, 0.05);
            z-index: 1000;
        }

        /* Dark mode compatibility for footer */
        @media (prefers-color-scheme: dark) {
            .footer {
                background-color: rgba(14, 17, 23, 0.8);
                border-top: 1px solid rgba(255, 255, 255, 0.1);
            }
        }
    </style>
""", unsafe_allow_html=True)

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
    # INCREASED TEXT LIMIT TO 12,000 TO CATCH TECH STACKS AT THE BOTTOM
    prompt = f"""
    You are a data extractor for a job board.
    
    Your job is to analyse the job posting, extract the Top 5 Tech Stack tools and the main Focus (1 sentence).
    
    Format:
    Tech: [Tools]
    Focus: [Goal]

    CRITICAL INSTRUCTION:
    If the text contains words like "Sign In", "Create Account", "Verify Password", "Candidate Home", or "My Account" AND lacks a clear job description, it is a Login Wall.
    In that case, output EXACTLY:
    Tech: N/A
    Focus: Apply form, check manually
    
    Job Text:
    {text[:12000]}
    """
    return query_ollama(prompt)

# --- MAIN APP UI ---

# Sidebar Controls
with st.sidebar:
    # LOGO
    st.image("assets/logo.svg", width=250)
    st.divider()

    st.header("Search Settings")
    role_input = st.text_input("Job Role", value="Data Engineer")
    region_input = st.selectbox("Region", ["EU OR \"United States\"", "EU", "\"United States\"", "\"United Kingdom\""])
    max_pages = st.slider("Max Google Pages to Scrape", 1, 10, 1)
    st.caption("Note: More pages mean longer processing time.")

    st.divider()

    st.subheader("AI Status")
    if check_ollama():
        st.success(f"🟢 Ollama ({OLLAMA_MODEL}) Connected")
        ai_ready = True
    else:
        st.error("🔴 Ollama Disconnected")
        st.info("Run 'ollama serve' in terminal")
        ai_ready = False

# Main Page Header
st.markdown("""
    <h1 style='margin-bottom: 0px; padding-top: 0px;'>
        ABH Lead Generator
    </h1>
    <p style='font-size: 1.2rem; color: #666; margin-top: 5px;'>
        Welcome! Use the filters on the left to define your search criteria.
    </p>
""", unsafe_allow_html=True)

if 'results' not in st.session_state:
    st.session_state.results = []

# --- THE SCRAPER LOGIC ---
start_btn = st.button("Generate Leads", type="primary", disabled=not ai_ready)

if start_btn:
    st.session_state.results = []
    search_query = f'site:myworkdayjobs.com {role_input} ({region_input})'

    status_box = st.status("Initializing Browser...", expanded=True)
    table_placeholder = st.empty()
    progress_bar = st.progress(0)

    with sync_playwright() as p:
        status_box.write("Loading Chrome Profile (Anti-Detection)...")

        user_data_dir = os.path.join(os.getcwd(), "chrome_profile")
        if not os.path.exists(user_data_dir):
            os.makedirs(user_data_dir)

        browser = p.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox', '--disable-infobars'],
            viewport={'width': 1280, 'height': 720}
        )

        page = browser.pages[0]

        status_box.write(f"Searching Google for: {role_input}...")
        page.goto("https://www.google.com")

        try:
            page.get_by_role("button", name=lambda t: t in ["Reject all", "Reject", "Deny", "Odbij sve"], exact=False).first.click(timeout=2000)
        except: pass

        try:
            page.wait_for_selector('textarea[name="q"]', timeout=5000)
            page.fill('textarea[name="q"]', search_query)
            page.press('textarea[name="q"]', "Enter")
        except:
            st.error("Could not type in search bar.")

        status_box.write("⚠️ Checking for Captcha... (Solve it in the browser if you see one!)")
        try:
            page.wait_for_selector('#search', timeout=0)
        except: pass

        status_box.write("✅ Search Results Found! Scraping links...")

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

            if page.locator("#pnnext").is_visible():
                page.locator("#pnnext").click()
                sleep_time = random.uniform(3.5, 7.5)
                status_box.write(f"Sleeping {round(sleep_time, 1)}s to act human...")
                time.sleep(sleep_time)
            else:
                break

        df_raw = pd.DataFrame(raw_leads).drop_duplicates(subset=["Company"])
        leads = df_raw.to_dict('records')
        total_leads = len(leads)
        status_box.write(f"Found {total_leads} unique companies. Starting AI Analysis...")

        processed_data = []

        for idx, lead in enumerate(leads):
            progress = (idx + 1) / total_leads
            progress_bar.progress(progress)
            status_box.write(f"[{idx+1}/{total_leads}] Analyzing **{lead['Company']}**...")

            try:
                # JITTER
                time.sleep(random.uniform(1.0, 2.5))

                # VISIT PAGE
                page.goto(lead['URL'], timeout=15000) # Increased timeout

                # --- FIX 1: SMART WAIT ---
                # Instead of just sleeping, we wait for the Description Box to be visible.
                # Workday almost always uses this ID. We give it 6 seconds to appear.
                try:
                    page.wait_for_selector('[data-automation-id="jobPostingDescription"]', state="visible", timeout=6000)
                except:
                    # If selector not found, maybe it's a different layout. We proceed to fallback.
                    pass

                # --- FIX 2: SCROLL TO TRIGGER LAZY LOAD ---
                # We scroll to the bottom to ensure all text is rendered
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(1)

                # EXTRACT TEXT
                text = ""
                try:
                    text = page.locator('[data-automation-id="jobPostingDescription"]').inner_text()
                except:
                    # Fallback: Get body but try to ignore nav bars
                    text = page.inner_text("body")

                # VALIDATION
                if len(text) < 100 or "Candidate Home" in text[:200] and len(text) < 500:
                     # If text is suspiciously short, it failed to load.
                     status_box.write("    -> ⚠️ Page didn't load correctly. Skipping.")
                     continue

                # AI ANALYZE
                analysis = analyze_job(text)
                if "INVALID" in analysis:
                    continue
                lead['Analysis'] = analysis

                # GOOGLE SIZE CHECK
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

                st.session_state.results = processed_data
                df_live = pd.DataFrame(processed_data)
                if not df_live.empty:
                    df_live = df_live.sort_values(by="Employees", ascending=False)
                    table_placeholder.dataframe(df_live, use_container_width=True)

            except Exception as e:
                # print(e) # Debugging only
                continue

        browser.close()
        status_box.update(label="✅ Scraping Complete!", state="complete", expanded=False)

if st.session_state.results:
    st.divider()
    df_final = pd.DataFrame(st.session_state.results)
    if not df_final.empty:
        df_final = df_final.sort_values(by="Employees", ascending=False)

        col1, col2 = st.columns([1, 1])
        with col1:
            st.metric("Total Leads", len(df_final))
        with col2:
            csv = df_final.to_csv(index=False).encode('utf-8')
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
            st.download_button(
                label="Download CSV",
                data=csv,
                file_name=f"leads_{timestamp}.csv",
                mime="text/csv",
                type="primary"
            )

# --- FOOTER ---
st.markdown(
    """
    <div class='footer'>
        Built with ❤️ for <b>Atlantbh</b> | 2026 <br>
        Developed by <a href='https://github.com/makbanjac-abh' style='color: #434c5e; text-decoration: none; font-weight: 600;'>Mak Banjac</a>
    </div>
    """,
    unsafe_allow_html=True
)