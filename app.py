from flask import Flask, request, render_template_string
import requests
import re
import base64
import os

app = Flask(__name__)

# ================== তোমার Pixeldrain API Key এখানে দাও ==================
PIXELDRAIN_API_KEY = "644e8abe-4256-4b36-bb01-d7f57dd2c04f"

# Google Drive file ID বের করার ফাংশন
def get_file_id(url):
    if "drive.google.com/file/d/" in url:
        return re.search(r"/file/d/([a-zA-Z0-9_-]+)", url).group(1)
    elif "id=" in url:
        return re.search(r"id=([a-zA-Z0-9_-]+)", url).group(1)
    return None

# ================== নতুন ফিক্সড স্ট্রিম ফাংশন (১০০ এমবি+ এখন কাজ করবে) ==================
def get_gdrive_stream(file_id):
    session = requests.Session()
    url = f"https://docs.google.com/uc?export=download&id={file_id}"
    
    # প্রথম চেক
    response = session.get(url, allow_redirects=True)
    
    # ছোট ফাইল → সরাসরি ফাইল স্ট্রিম পাওয়া গেছে
    if response.status_code == 200 and "content-disposition" in [k.lower() for k in response.headers]:
        content_type = response.headers.get("Content-Type", "").lower()
        if "text/html" not in content_type:
            return response
    
    # বড় ফাইল → virus scan warning page এসেছে
    html = response.text
    
    # confirm token বের করা
    confirm_match = re.search(r'name="confirm"\s+value="([a-zA-Z0-9_-]+)"', html, re.IGNORECASE)
    confirm = confirm_match.group(1) if confirm_match else "t"
    
    # uuid বের করা (যদি থাকে)
    uuid_match = re.search(r'name="uuid"\s+value="([a-zA-Z0-9_-]+)"', html, re.IGNORECASE)
    uuid_val = uuid_match.group(1) if uuid_match else None
    
    # সঠিক ডাউনলোড লিংক (নতুন Google endpoint)
    download_url = "https://drive.usercontent.google.com/download"
    params = {
        "id": file_id,
        "export": "download",
        "confirm": confirm
    }
    if uuid_val:
        params["uuid"] = uuid_val
    
    # এখন আসল ফাইল স্ট্রিম
    stream_response = session.get(download_url, params=params, stream=True, allow_redirects=True)
    
    # যদি এখনো HTML আসে তাহলে এরর দাও
    if stream_response.status_code != 200 or "text/html" in stream_response.headers.get("Content-Type", "").lower():
        raise Exception("Google Drive virus scan warning bypass failed. Please try again or use a different file.")
    
    return stream_response

# Pixeldrain-এ আপলোড (streaming)
def upload_to_pixeldrain(gdrive_stream, filename):
    upload_url = f"https://pixeldrain.com/api/file/{filename}"
    auth = base64.b64encode(f":{PIXELDRAIN_API_KEY}".encode()).decode()
    
    headers = {
        "Authorization": f"Basic {auth}",
        "User-Agent": "Mozilla/5.0"
    }
    
    def generate():
        for chunk in gdrive_stream.iter_content(chunk_size=1024*1024):  # 1MB chunk
            if chunk:
                yield chunk
    
    r = requests.put(upload_url, data=generate(), headers=headers, stream=True)
    return r.json()

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        gd_link = request.form.get("link")
        custom_name = request.form.get("name", "").strip()
        
        file_id = get_file_id(gd_link)
        if not file_id:
            return "Invalid Google Drive link!"
        
        try:
            gdrive_response = get_gdrive_stream(file_id)
            
            # ফাইলের নাম বের করা
            if not custom_name:
                cd = gdrive_response.headers.get("Content-Disposition", "")
                if "filename=" in cd:
                    custom_name = cd.split("filename=")[-1].strip('"')
                else:
                    custom_name = f"file_{file_id[:8]}.bin"
            
            result = upload_to_pixeldrain(gdrive_response, custom_name)
            
            if result.get("success") or "id" in result:
                pd_link = f"https://pixeldrain.com/f/{result['id']}"
                return f'''
                <h2>✅ আপলোড সফল!</h2>
                <p><a href="{pd_link}" target="_blank">{pd_link}</a></p>
                <a href="/">আবার নতুন লিংক দাও</a>
                '''
            else:
                return f"Error: {result}"
                
        except Exception as e:
            return f"Error: {str(e)}"
    
    return render_template_string('''
    <h1>Google Drive → Pixeldrain</h1>
    <form method="post">
        <input type="text" name="link" placeholder="Google Drive লিংক দাও" style="width:100%;padding:10px" required><br><br>
        <input type="text" name="name" placeholder="কাস্টম ফাইল নাম (ঐচ্ছিক)" style="width:100%;padding:10px"><br><br>
        <button type="submit" style="padding:15px 30px;font-size:18px">আপলোড করো Pixeldrain-এ</button>
    </form>
    ''')

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
