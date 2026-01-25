"""Test script for Selenium transcript extraction"""
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time

video_id = '0J2_YGuNrDo'

chrome_options = Options()
chrome_options.add_argument('--headless')
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--disable-dev-shm-usage')
chrome_options.add_argument('--window-size=1920,1080')
chrome_options.add_argument('--lang=en-US')

service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=chrome_options)

try:
    # Force hl=en to ensure consistent button text
    url = f'https://www.youtube.com/watch?v={video_id}&hl=en'
    print(f'Loading: {url}')
    driver.get(url)
    
    # Wait and scroll a bit to trigger lazy loading
    time.sleep(5)
    driver.execute_script("window.scrollTo(0, 500);")
    time.sleep(2)
    
    print(f'Page title: {driver.title}')
    
    # Try multiple ways to expand description
    try:
        expand_selectors = ['tp-yt-paper-button#expand', '#expand', 'ytd-text-inline-expander [button-renderer]']
        expanded = False
        for selector in expand_selectors:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, selector)
                if btn.is_displayed():
                    btn.click()
                    print(f'Clicked expand button via {selector}')
                    expanded = True
                    time.sleep(2)
                    break
            except:
                continue
        if not expanded:
            print('Could not find specific expand button, trying general click on description')
            driver.find_element(By.ID, 'description-inner').click()
            time.sleep(2)
    except Exception as e:
        print(f'Expand error: {e}')
    
    # Search for transcript button across ALL elements
    print('Searching for transcript button...')
    transcript_clicked = False
    
    # Strategy 1: Specific CSS Selector recommended for modern YouTube
    try:
        print('Trying Strategy 1...')
        wait = WebDriverWait(driver, 10)
        btn = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "ytd-video-description-transcript-section-renderer button")))
        driver.execute_script("arguments[0].scrollIntoView(true);", btn)
        time.sleep(1)
        driver.execute_script("arguments[0].click();", btn)
        print('Clicked transcript button via specific CSS selector and JS!')
        transcript_clicked = True
        time.sleep(5)
    except Exception as e:
        print(f'Strategy 1 failed: {e}, trying Strategy 2...')

    if not transcript_clicked:
        # Strategy 2: Look for elements containing "Transcript" text across ALL tags
        all_elements = driver.find_elements(By.XPATH, "//*[contains(text(), 'Transcript') or contains(text(), 'transcript')]")
        print(f'Found {len(all_elements)} elements with "transcript" text')
        
        for el in all_elements:
            try:
                tag = el.tag_name
                text = el.text[:30]
                print(f'Trying to click: <{tag}> text="{text}"')
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
                time.sleep(1)
                driver.execute_script("arguments[0].click();", el)
                print('Success via JS click!')
                transcript_clicked = True
                time.sleep(5)
                # Check if segments appeared
                segments = driver.find_elements(By.CSS_SELECTOR, "ytd-transcript-segment-renderer")
                if segments:
                    break
            except:
                continue
    
    if not transcript_clicked:
        print('Could not find/click transcript button')
    
    # Look for transcript segments
    print('Checking global text for transcript content...')
    time.sleep(10)
    
    body_text = driver.find_element(By.TAG_NAME, "body").text
    print(f'Global text length: {len(body_text)}')
    
    import re
    timestamps = re.findall(r'\d+:\d+', body_text)
    print(f'Found {len(timestamps)} timestamp-like strings in global text')
    
    if len(timestamps) > 10:
        print('SUCCESS! Transcript seems to be visible in global text.')
        # Try to find where it starts
        first_ts = timestamps[0]
        start_idx = body_text.find(first_ts)
        print(f'Transcript preview: {body_text[start_idx:start_idx+1000]}...')
    else:
        print('No significant timestamps found in global text. Trying to find engagement panel content again...')
        # Maybe it's hidden?
        js_get_all = "return document.body.innerText;"
        all_txt = driver.execute_script(js_get_all)
        ts_all = re.findall(r'\d+:\d+', all_txt)
        print(f'JS innerText found {len(ts_all)} timestamps')
        if len(ts_all) > 10:
            print('Success via JS innerText!')
            print(f'Preview: {all_txt[all_txt.find(ts_all[0]):][:1000]}')

finally:
    driver.quit()
    print('Done!')
