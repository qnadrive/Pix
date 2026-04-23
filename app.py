from flask import Flask, request, jsonify
import requests
import re
import base64
import os
import threading
import uuid
import queue # নতুন ইম্পোর্ট
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

PIXELDRAIN_API_KEY = "1a283756-5b5a-45c6-adcb-e0859d6e9d2f"

jobs = {}

# ================== Queue System ==================
# একসাথে সর্বোচ্চ কয়টি ফাইল আপলোড হবে (512MB RAM এর জন্য 2 টি নিরাপদ)
MAX_CONCURRENT_UPLOADS = 2
upload_queue = queue.Queue()

def get_file_id(url):
    if "drive.google.com/file/d/" in url:
        return re.search(r"/file/d/([a-zA-Z0-9_-]+)", url).group(1)
    elif "id=" in url:
        return re.search(r"id=([a-zA-Z0-9_-]+)", url).group(1)
    return None

def get_gdrive_stream(file_id):
    session = requests.Session()
    url = f"https://docs.google.com/uc?export=download&id={file_id}"
    response = session.get(url, allow_redirects=True)
    
    html = response.text.lower()
    if "virus scan warning" in html or "download anyway" in html:
        confirm_match = re.search(r'name="confirm"\s+value="([a-zA-Z0-9_-]+)"', response.text, re.IGNORECASE)
        confirm = confirm_match.group(1) if confirm_match else "t"
        
        uuid_match = re.search(r'name="uuid"\s+value="([a-zA-Z0-9_-]+)"', response.text, re.IGNORECASE)
        uuid_val = uuid_match.group(1) if uuid_match else None
        
        download_url = "https://drive.usercontent.google.com/download"
        params = {"id": file_id, "export": "download", "confirm": confirm}
        if uuid_val:
            params["uuid"] = uuid_val
            
        return session.get(download_url, params=params, stream=True, allow_redirects=True)
    
    return response

def background_upload(job_id, file_id, custom_name):
    jobs[job_id]['status'] = 'running'
    try:
        gdrive_response = get_gdrive_stream(file_id)
        
        if not custom_name:
            cd = gdrive_response.headers.get("Content-Disposition", "")
            custom_name = cd.split("filename=")[-1].strip('"') if "filename=" in cd else f"file_{file_id[:8]}.bin"
        
        upload_url = f"https://pixeldrain.com/api/file/{custom_name}"
        auth = base64.b64encode(f":{PIXELDRAIN_API_KEY}".encode()).decode()
        headers = {"Authorization": f"Basic {auth}", "User-Agent": "Mozilla/5.0"}
        
        def generate():
            # Chunk size 512KB করা হলো মেমরি সেভ করার জন্য
            for chunk in gdrive_response.iter_content(chunk_size=512*1024):
                if chunk: yield chunk
        
        r = requests.put(upload_url, data=generate(), headers=headers, stream=True)
        result = r.json()
        
        if result.get("success") or "id" in result:
            jobs[job_id]['status'] = 'done'
            jobs[job_id]['result'] = f"https://pixeldrain.com/f/{result['id']}"
        else:
            raise Exception(str(result))
    except Exception as e:
        jobs[job_id]['status'] = 'failed'
        jobs[job_id]['error'] = str(e)

# ================== Worker Thread ==================
# এই ফাংশনটি সবসময় ব্যাকগ্রাউন্ডে চলবে এবং Queue থেকে একটি করে জব নিয়ে কাজ করবে
def worker():
    while True:
        job_id, file_id, custom_name = upload_queue.get()
        background_upload(job_id, file_id, custom_name)
        upload_queue.task_done()

# সার্ভার চালু হওয়ার সাথে সাথে Worker Thread গুলো চালু করে দেওয়া হলো
for _ in range(MAX_CONCURRENT_UPLOAVER_UPLOADS):
    t = threading.Thread(target=worker)
    t.daemon = True
    t.start()
# ===================================================

@app.route("/api/submit", methods=["POST"])
def api_submit():
    data = request.get_json()
    gd_link = data.get("link")
    custom_name = data.get("name", "").strip()
    
    file_id = get_file_id(gd_link)
    if not file_id:
        return jsonify({"error": "Invalid Google Drive link!"}), 400
    
    job_id = str(uuid.uuid4())
    jobs[job_id] = {'status': 'queued', 'result': None, 'error': None}
    
    # থ্রেড তৈরি করার বদলে Queue তে জব পাঠিয়ে দেওয়া হলো
    upload_queue.put((job_id, file_id, custom_name))
    
    return jsonify({"success": True, "job_id": job_id, "message": "আপলোড কিউ হয়েছে!"})

@app.route("/api/status/<job_id>")
def api_status(job_id):
    if job_id not in jobs:
        return jsonify({"error": "Job ID পাওয়া যায়নি!"}), 404
    return jsonify(jobs[job_id])

@app.route("/", methods=["GET", "POST"])
def index():
    return "API is running. Use /api/submit and /api/status/"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
