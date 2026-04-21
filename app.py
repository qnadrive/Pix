from flask import Flask, request, render_template_string, redirect, url_for
import requests
import re
import base64
import os
import threading
import uuid

app = Flask(__name__)

# ================== তোমার Pixeldrain API Key ==================
PIXELDRAIN_API_KEY = "644e8abe-4256-4b36-bb01-d7f57dd2c04f"

# জব স্টোরেজ (ইন-মেমরি কিউ)
jobs = {}

# Google Drive file ID বের করা
def get_file_id(url):
    if "drive.google.com/file/d/" in url:
        return re.search(r"/file/d/([a-zA-Z0-9_-]+)", url).group(1)
    elif "id=" in url:
        return re.search(r"id=([a-zA-Z0-9_-]+)", url).group(1)
    return None

# Google Drive স্ট্রিম (virus scan bypass সহ)
def get_gdrive_stream(file_id):
    session = requests.Session()
    url = f"https://docs.google.com/uc?export=download&id={file_id}"
    response = session.get(url, allow_redirects=True)
    
    html = response.text.lower()
    if "virus scan warning" in html or "download anyway" in html:
        # নতুন warning page থেকে confirm + uuid বের করা
        confirm_match = re.search(r'name="confirm"\s+value="([a-zA-Z0-9_-]+)"', response.text, re.IGNORECASE)
        confirm = confirm_match.group(1) if confirm_match else "t"
        
        uuid_match = re.search(r'name="uuid"\s+value="([a-zA-Z0-9_-]+)"', response.text, re.IGNORECASE)
        uuid_val = uuid_match.group(1) if uuid_match else None
        
        download_url = "https://drive.usercontent.google.com/download"
        params = {"id": file_id, "export": "download", "confirm": confirm}
        if uuid_val:
            params["uuid"] = uuid_val
            
        stream_response = session.get(download_url, params=params, stream=True, allow_redirects=True)
        return stream_response
    
    return response  # ছোট ফাইলের ক্ষেত্রে

# ব্যাকগ্রাউন্ড আপলোড ফাংশন
def background_upload(job_id, file_id, custom_name):
    jobs[job_id]['status'] = 'running'
    try:
        gdrive_response = get_gdrive_stream(file_id)
        
        if not custom_name:
            cd = gdrive_response.headers.get("Content-Disposition", "")
            if "filename=" in cd:
                custom_name = cd.split("filename=")[-1].strip('"')
            else:
                custom_name = f"file_{file_id[:8]}.bin"
        
        # Pixeldrain আপলোড
        upload_url = f"https://pixeldrain.com/api/file/{custom_name}"
        auth = base64.b64encode(f":{PIXELDRAIN_API_KEY}".encode()).decode()
        headers = {"Authorization": f"Basic {auth}", "User-Agent": "Mozilla/5.0"}
        
        def generate():
            for chunk in gdrive_response.iter_content(chunk_size=1024*1024):
                if chunk:
                    yield chunk
        
        r = requests.put(upload_url, data=generate(), headers=headers, stream=True)
        result = r.json()
        
        if result.get("success") or "id" in result:
            pd_link = f"https://pixeldrain.com/f/{result['id']}"
            jobs[job_id]['status'] = 'done'
            jobs[job_id]['result'] = pd_link
        else:
            raise Exception(str(result))
            
    except Exception as e:
        jobs[job_id]['status'] = 'failed'
        jobs[job_id]['error'] = str(e)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        gd_link = request.form.get("link")
        custom_name = request.form.get("name", "").strip()
        
        file_id = get_file_id(gd_link)
        if not file_id:
            return "Invalid Google Drive link!"
        
        job_id = str(uuid.uuid4())
        jobs[job_id] = {'status': 'queued', 'result': None, 'error': None}
        
        # ব্যাকগ্রাউন্ডে চালু
        thread = threading.Thread(target=background_upload, args=(job_id, file_id, custom_name))
        thread.daemon = True
        thread.start()
        
        return f'''
        <h2>✅ জব কিউ হয়েছে!</h2>
        <p><strong>Job ID:</strong> {job_id}</p>
        <p>আপলোড ব্যাকগ্রাউন্ডে চলছে।</p>
        <a href="/status/{job_id}">স্ট্যাটাস চেক করো</a><br><br>
        <a href="/">নতুন লিংক দাও</a>
        '''
    
    return render_template_string('''
    <h1>Google Drive → Pixeldrain (Background Upload)</h1>
    <form method="post">
        <input type="text" name="link" placeholder="Google Drive লিংক দাও" style="width:100%;padding:10px" required><br><br>
        <input type="text" name="name" placeholder="কাস্টম ফাইল নাম (ঐচ্ছিক)" style="width:100%;padding:10px"><br><br>
        <button type="submit" style="padding:15px 30px;font-size:18px">কিউতে যোগ করো</button>
    </form>
    <p><small>বড় ফাইল হলেও লোডিং স্ক্রিন থাকবে না। জব আইডি নিয়ে স্ট্যাটাস দেখো।</small></p>
    ''')

@app.route("/status/<job_id>")
def status(job_id):
    if job_id not in jobs:
        return "Job ID পাওয়া যায়নি!"
    
    job = jobs[job_id]
    if job['status'] == 'done':
        return f'''
        <h2>✅ আপলোড সফল!</h2>
        <p><a href="{job['result']}" target="_blank">{job['result']}</a></p>
        <a href="/">নতুন লিংক দাও</a>
        '''
    elif job['status'] == 'failed':
        return f"<h2>❌ এরর হয়েছে</h2><p>{job['error']}</p><a href='/'>আবার চেষ্টা করো</a>"
    else:
        return f'''
        <h2>⏳ আপলোড চলছে...</h2>
        <p>Status: {job['status'].upper()}</p>
        <p>Job ID: {job_id}</p>
        <p>পেজটা রিফ্রেশ করো (১০-১৫ সেকেন্ড পর পর)।</p>
        <a href="/status/{job_id}">রিফ্রেশ</a><br><br>
        <a href="/">নতুন জব যোগ করো</a>
        '''

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
