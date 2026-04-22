from flask import Flask, request, jsonify
import requests
import re
import base64
import os
import threading
import uuid
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# এখানে তোমার পিক্সেলড্রেন API কী বসাও
PIXELDRAIN_API_KEY = "644e8abe-4256-4b36-bb01-d7f57dd2c04f"

jobs = {}

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
        
        # যদি ইউজার কাস্টম নাম না দেয়, তবে ড্রাইভের অরিজিনাল নাম নেওয়া হচ্ছে
        if not custom_name:
            cd = gdrive_response.headers.get("Content-Disposition", "")
            if "filename=" in cd:
                custom_name = cd.split("filename=")[-1].strip('"')
            else:
                custom_name = f"file_{file_id[:8]}.bin"
        
        # জব ডিকশনারিতে নাম আপডেট করা হচ্ছে যাতে ওয়ার্ডপ্রেস এটা দেখতে পায়
        jobs[job_id]['filename'] = custom_name
        
        upload_url = f"https://pixeldrain.com/api/file/{custom_name}"
        auth = base64.b64encode(f":{PIXELDRAIN_API_KEY}".encode()).decode()
        headers = {"Authorization": f"Basic {auth}", "User-Agent": "Mozilla/5.0"}
        
        def generate():
            for chunk in gdrive_response.iter_content(chunk_size=1024*1024):
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

@app.route("/api/submit", methods=["POST"])
def api_submit():
    data = request.get_json()
    gd_link = data.get("link")
    custom_name = data.get("name", "").strip()
    
    file_id = get_file_id(gd_link)
    if not file_id:
        return jsonify({"error": "Invalid Google Drive link!"}), 400
    
    job_id = str(uuid.uuid4())
    # শুরুতে ইনকামিং নাম সেট করা হচ্ছে
    jobs[job_id] = {'status': 'queued', 'result': None, 'error': None, 'filename': custom_name}
    
    thread = threading.Thread(target=background_upload, args=(job_id, file_id, custom_name))
    thread.daemon = True
    thread.start()
    
    return jsonify({"success": True, "job_id": job_id, "message": "কিউতে যোগ হয়েছে!"})

@app.route("/api/status/<job_id>")
def api_status(job_id):
    if job_id not in jobs:
        return jsonify({"error": "Job ID not found!"}), 404
    return jsonify(jobs[job_id])

@app.route("/")
def index():
    return "API is running. Monitoring active."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
