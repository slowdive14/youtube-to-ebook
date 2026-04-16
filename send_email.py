"""
Part 4: Send Newsletter via Email
Sends the generated articles as a nicely formatted email newsletter with EPUB attachment.
"""

import sys
import io

# Fix Windows console encoding for Unicode characters
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import os
import smtplib
import markdown
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from dotenv import load_dotenv
from ebooklib import epub

# Load your credentials
load_dotenv()
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")


def create_epub(articles, language='en'):
    """
    Create an EPUB ebook from the articles for reading on mobile devices.
    Returns the path to the generated EPUB file.
    language: 'en' for English, 'ko' for Korean
    """
    today = datetime.now().strftime("%B %d, %Y")
    lang_suffix = "_ko" if language == 'ko' else "_en"
    filename = f"youtube_digest_{datetime.now().strftime('%Y%m%d')}{lang_suffix}.epub"
    filepath = os.path.join(os.path.dirname(__file__), filename)

    # Create the ebook
    book = epub.EpubBook()

    # Set metadata
    book.set_identifier(f"youtube-digest-{datetime.now().strftime('%Y%m%d%H%M%S')}-{language}")
    if language == 'ko':
        book.set_title(f"YouTube 다이제스트 - {today}")
        book.set_language("ko")
    else:
        book.set_title(f"YouTube Digest - {today}")
        book.set_language("en")
    book.add_author("YouTube Newsletter Bot")

    # CSS for nice formatting on ebook readers
    style = """
    body {
        font-family: Georgia, serif;
        line-height: 1.6;
        padding: 1em;
    }
    h1 {
        font-size: 1.5em;
        margin-top: 1em;
        border-bottom: 1px solid #ccc;
        padding-bottom: 0.3em;
    }
    h2 {
        font-size: 1.3em;
        margin-top: 1em;
    }
    h3 {
        font-size: 1.1em;
    }
    .intro {
        background: #f5f5f5;
        padding: 1em;
        border-left: 3px solid #666;
        margin-bottom: 1.5em;
        font-size: 0.95em;
    }
    .watch-link {
        margin-top: 1.5em;
        padding: 0.5em;
        background: #f0f0f0;
        display: block;
    }
    """
    nav_css = epub.EpubItem(
        uid="style_nav",
        file_name="style/nav.css",
        media_type="text/css",
        content=style
    )
    book.add_item(nav_css)

    chapters = []

    # Create a chapter for each article
    for i, article in enumerate(articles):
        # Convert markdown to HTML
        article_html = markdown.markdown(article['article'])

        chapter_content = f"""
        <html>
        <head>
            <link rel="stylesheet" type="text/css" href="style/nav.css"/>
        </head>
        <body>
            <div class="intro">
                <p><em>This article is based on the video "<strong>{article['title']}</strong>" from the YouTube channel <strong>{article['channel']}</strong>.</em></p>
            </div>
            {article_html}
            <p class="watch-link">Watch the original video: {article['url']}</p>
        </body>
        </html>
        """

        chapter = epub.EpubHtml(
            title=article['title'][:50],
            file_name=f"chapter_{i+1}.xhtml",
            lang="en"
        )
        chapter.content = chapter_content
        chapter.add_item(nav_css)

        book.add_item(chapter)
        chapters.append(chapter)

    # Create table of contents
    book.toc = tuple(chapters)

    # Add navigation files
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # Set the reading order
    book.spine = ["nav"] + chapters

    # Write the EPUB file
    epub.write_epub(filepath, book)

    lang_name = "Korean" if language == 'ko' else "English"
    print(f"  [OK] Created {lang_name} EPUB: {filename}")
    return filepath


def create_newsletter_html(articles, language='en', audio_cids=None):
    """
    Create a beautifully formatted HTML newsletter from the articles.
    Uses larger fonts for better readability.
    language: 'en' for English, 'ko' for Korean
    audio_cids: List of Content-IDs for audio attachments (optional)
    """
    today = datetime.now().strftime("%B %d, %Y")

    lang_code = 'ko' if language == 'ko' else 'en'
    html = f"""
    <!DOCTYPE html>
    <html lang="{lang_code}">
    <head>
        <meta charset="utf-8">
        <style>
            body {{
                font-family: Georgia, serif;
                font-size: 18px;
                max-width: 700px;
                margin: 0 auto;
                padding: 20px;
                background-color: #f9f9f9;
                color: #333;
            }}
            .header {{
                text-align: center;
                padding: 30px 0;
                border-bottom: 3px solid #333;
                margin-bottom: 30px;
            }}
            .header h1 {{
                margin: 0;
                font-size: 32px;
                letter-spacing: 2px;
            }}
            .header p {{
                color: #666;
                font-size: 18px;
                margin: 10px 0 0 0;
            }}
            .article {{
                background: white;
                padding: 30px;
                margin-bottom: 30px;
                border-radius: 5px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            }}
            .article-intro {{
                background: #f8f8f8;
                padding: 15px 20px;
                border-left: 4px solid #666;
                margin-bottom: 25px;
                font-size: 16px;
                color: #555;
                line-height: 1.6;
            }}
            .article-content {{
                font-size: 18px;
                line-height: 2.0;
            }}
            .article-content h1 {{
                color: #1a1a1a;
                font-size: 28px;
                margin-top: 35px;
                margin-bottom: 20px;
                padding-bottom: 10px;
                border-bottom: 2px solid #eee;
            }}
            .article-content h2 {{
                color: #2a2a2a;
                font-size: 24px;
                margin-top: 30px;
                margin-bottom: 15px;
            }}
            .article-content h3 {{
                color: #3a3a3a;
                font-size: 20px;
                margin-top: 25px;
                margin-bottom: 12px;
            }}
            .article-content p {{
                font-size: 18px;
                margin-bottom: 1.5em;
                text-align: justify;
            }}
            .article-content ul, .article-content ol {{
                margin: 1.5em 0;
                padding-left: 2em;
            }}
            .article-content li {{
                margin-bottom: 0.8em;
                line-height: 1.8;
            }}
            .article-content blockquote {{
                margin: 1.5em 0;
                padding: 15px 20px;
                background: #f5f5f5;
                border-left: 4px solid #ccc;
                font-style: italic;
            }}
            .article-content strong {{
                color: #111;
            }}
            .watch-link {{
                display: inline-block;
                margin-top: 20px;
                padding: 12px 24px;
                background: #ff0000;
                color: white !important;
                text-decoration: none;
                border-radius: 5px;
                font-size: 16px;
            }}
            .footer {{
                text-align: center;
                color: #999;
                font-size: 14px;
                padding: 20px;
            }}
            .epub-note {{
                text-align: center;
                background: #e8f4e8;
                padding: 15px;
                border-radius: 5px;
                margin-bottom: 30px;
                font-size: 16px;
            }}
        </style>
    </head>
    <body>
        <header class="header">
            <h1>{"YouTube 다이제스트" if language == 'ko' else "YOUR YOUTUBE DIGEST"}</h1>
            <p>{today}</p>
        </header>
        <main>
    """

    if audio_cids:
        audio_player_html = ""
        for i, cid in enumerate(audio_cids):
            part_label = ""
            if len(audio_cids) > 1:
                part_label = f" (Part {i+1})"
            
            audio_player_html += f"""
            <div style="margin: 20px 0; padding: 15px; background: #e1f5fe; border-radius: 8px; text-align: center;">
                <p style="margin: 0 0 10px 0; font-weight: bold; color: #0277bd;">🎧 Listen to this newsletter{part_label}</p>
                <audio controls style="width: 100%; max-width: 400px;">
                    <source src="cid:{cid}" type="audio/mpeg">
                    Your email client does not support the audio element.
                </audio>
                <p style="margin: 5px 0 0 0; font-size: 12px; color: #666;">
                    (If player doesn't appear, please check attachments)
                </p>
            </div>
            """
        html += audio_player_html

    for i, article in enumerate(articles):
        # Convert markdown article to HTML
        article_html = markdown.markdown(article['article'])
        
        html += f"""
        <article class="article">
            <div class="article-intro">
                <em>This article is based on the video "<strong>{article['title']}</strong>" from the YouTube channel <strong>{article['channel']}</strong>.</em>
            </div>
            <section class="article-content">
                {article_html}
            </section>
            <a href="{article['url']}" class="watch-link">Watch the original video</a>
        </article>
        """

    html += """
        </main>
        <footer class="footer">
            Generated by YouTube Newsletter Bot
        </footer>
    </body>
    </html>
    """

    return html


def send_newsletter(articles, recipient_email=None, language='en', audio_paths=None):
    """
    Send the newsletter via Gmail.
    If no recipient specified, sends to yourself.
    language: 'en' for English, 'ko' for Korean
    audio_paths: list of paths to audio files to attach (optional)
    """
    if not articles:
        print("No articles to send!")
        return False

    # Default to sending to yourself
    if recipient_email is None:
        recipient_email = GMAIL_ADDRESS

    lang_name = "Korean" if language == 'ko' else "English"
    print(f"\nPreparing {lang_name} newsletter for {recipient_email}...")

    # Create the email (alternative for text/html)
    msg = MIMEMultipart("alternative")
    
    # Construct dynamic subject line
    first_title = articles[0]['title']
    if len(first_title) > 40:
        first_title = first_title[:37] + "..."
    
    count = len(articles)
    if language == 'ko':
        if count > 1:
            subject = f"{first_title} 외 {count-1}건 | YouTube 다이제스트"
        else:
            subject = f"{first_title} | YouTube 다이제스트"
    else:
        if count > 1:
            subject = f"{first_title} & {count-1} more | YouTube Digest"
        else:
            subject = f"{first_title} | YouTube Digest"
            
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = recipient_email

    # Create HTML content
    audio_cids = []
    if audio_paths:
        for i, path in enumerate(audio_paths):
            if os.path.exists(path):
                audio_cids.append(f"newsletter_audio_{i}")
        
    html_content = create_newsletter_html(articles, language=language, audio_cids=audio_cids)

    # Create plain text version (simple fallback)
    if language == 'ko':
        text_content = "YouTube 다이제스트\n\n"
    else:
        text_content = "Your YouTube Newsletter\n\n"
    for article in articles:
        text_content += f"--- {article['channel']} ---\n"
        text_content += f"{article['article']}\n"
        text_content += f"Watch: {article['url']}\n\n"

    # Attach both text versions to body
    msg.attach(MIMEText(text_content, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    # Attach audio files if provided
    if audio_paths:
        for i, path in enumerate(audio_paths):
            if os.path.exists(path):
                try:
                    base_name = os.path.basename(path)
                    cid = f"newsletter_audio_{i}"
                    
                    with open(path, "rb") as f:
                        part = MIMEBase('audio', 'mpeg')
                        part.set_payload(f.read())
                    
                    encoders.encode_base64(part)
                    
                    # Content-ID must match what we put in the HTML
                    part.add_header('Content-ID', f'<{cid}>')
                    part.add_header('Content-Disposition', f'inline; filename="{base_name}"')
                    
                    msg.attach(part)
                    print(f"  Attached inline audio: {base_name}")
                except Exception as e:
                    print(f"  [!] Failed to attach audio {path}: {e}")

    # Also attach legacy passed audio_files if they aren't already attached
    # (This handles the case where audio_files passed explicitly but not in article dict, usually just for testing)
    # Removed legacy audio_files attachment logic as we now use single audio_path
        
    try:
        # Connect to Gmail and send
        print("  Sending email...")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, recipient_email, msg.as_string())

        print(f"[OK] {lang_name} newsletter sent successfully!")
        
        return True

    except Exception as e:
        print(f"[X] Failed to send email: {e}")
        return False


def send_newsletter_bilingual(english_articles, korean_articles, recipient_email=None, audio_paths_en=None, audio_paths_ko=None):
    """
    Send both English and Korean newsletters.
    """
    success_en = False
    success_ko = False

    if english_articles:
        success_en = send_newsletter(english_articles, recipient_email, language='en', audio_paths=audio_paths_en)

    if korean_articles:
        success_ko = send_newsletter(korean_articles, recipient_email, language='ko', audio_paths=audio_paths_ko)

    return success_en or success_ko


# Test it standalone
if __name__ == "__main__":
    # Test with mock articles
    test_articles = [
        {
            "title": "Test Article",
            "channel": "Test Channel",
            "url": "https://youtube.com/watch?v=test",
            "article": "# Test Headline\n\nThis is a test article with **bold** and *italic* text.\n\n## Section 1\n\nSome content here."
        }
    ]

    print("Sending test newsletter...")
    
    # Check for test audio from generate_audio.py
    if os.path.exists("test_audio.mp3"):
        print("  Found test_audio.mp3, adding to article...")
        test_articles[0]["audio_path"] = "test_audio.mp3"
        
    send_newsletter(test_articles)
