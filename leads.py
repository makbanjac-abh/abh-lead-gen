import pandas as pd
from playwright.sync_api import sync_playwright
import time
import random

def get_leads():
    # Target: Enterprise firms (Workday users) hiring Data Engineers
    # Logic: We scrape Google, not LinkedIn.
    search_query = 'site:myworkdayjobs.com "Data Engineer" (EU OR "United States")'
    
    with sync_playwright() as p:
        # Launch browser (Headless=False so you can see it working/debug)
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        
        # 1. Go to Google
        page.goto("https://www.google.com")
        
        # Handle cookie consent if in EU (Basic check)
        try:
            page.get_by_role("button", name="Reject all").click(timeout=2000)
        except:
            pass

        # 2. Perform Search
        search_box = page.get_by_role("combobox", name="Search")
        search_box.fill(search_query)
        search_box.press("Enter")
        page.wait_for_timeout(2000)

        results = []
        
        # 3. Scrape first 3 pages
        for i in range(3):
            print(f"Scraping Page {i+1}...")
            
            # Select all search result containers
            links = page.locator("div.g a").all()
            
            for link in links:
                url = link.get_attribute("href")
                title = link.inner_text().split("\n")[0]
                
                # Filter for actual job posts (skip google internal links)
                if url and "myworkdayjobs.com" in url:
                    # Clean company name from URL (e.g., 'nvidia.myworkday...' -> nvidia)
                    company = url.split("https://")[1].split(".")[0]
                    
                    results.append({
                        "Company": company.capitalize(),
                        "Role": "Data Engineer", # Inferred from query
                        "Source URL": url,
                        "Title Snippet": title
                    })

            # Random sleep to act human
            time.sleep(random.uniform(2, 5))
            
            # Click 'Next' page
            try:
                page.get_by_role("link", name="Next").click()
                page.wait_for_timeout(3000)
            except:
                print("No more pages.")
                break

        browser.close()
        return results

# Run and Save
leads = get_leads()
df = pd.DataFrame(leads)
df.drop_duplicates(subset=["Company"], inplace=True) # One lead per company
df.to_csv("leads.csv", index=False)
print(f"Found {len(df)} unique enterprise companies.")