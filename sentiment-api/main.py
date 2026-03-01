from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from typing import List
from io import StringIO
import sys
import traceback
import os
from dotenv import load_dotenv
import json
import re
import tempfile
import time
import yt_dlp

# Gemini
from google import genai
from google.genai import types

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# SENTIMENT (AI PIPE)
# ----------------------------

ai_pipe_client = OpenAI(
    api_key=os.getenv("AI_PIPE_TOKEN"),
    base_url=os.getenv("AI_PIPE_BASE_URL")
)

class CommentRequest(BaseModel):
    comment: str

@app.post("/comment")
async def analyze_comment(request: CommentRequest):
    try:
        response = ai_pipe_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "Return ONLY JSON with fields: sentiment (positive, negative, neutral) and rating (1-5)."},
                {"role": "user", "content": request.comment}
            ],
            temperature=0
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ----------------------------
# CODE INTERPRETER
# ----------------------------

class CodeRequest(BaseModel):
    code: str

def execute_python_code(code: str) -> dict:
    old_stdout = sys.stdout
    sys.stdout = StringIO()

    try:
        exec(code)
        output = sys.stdout.getvalue()
        return {"success": True, "output": output}
    except Exception:
        output = traceback.format_exc()
        return {"success": False, "output": output}
    finally:
        sys.stdout = old_stdout

@app.post("/code-interpreter")
def code_interpreter(request: CodeRequest):
    execution = execute_python_code(request.code)

    if execution["success"]:
        return {"error": [], "result": execution["output"]}

    match = re.search(r'line (\d+)', execution["output"])
    error_line = int(match.group(1)) if match else 1

    return {
        "error": [error_line],
        "result": execution["output"]
    }


# ----------------------------
# YOUTUBE AUDIO TIMESTAMP
# ----------------------------

class AskRequest(BaseModel):
    video_url: str
    topic: str


def download_audio(video_url: str) -> str:
    temp_dir = tempfile.gettempdir()
    output_template = os.path.join(temp_dir, "audio.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "quiet": True,
        "noplaylist": True,
        "extractor_args": {
            "youtube": {
                "player_client": ["android"]
            }
        }
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
        ext = info["ext"]

    return os.path.join(temp_dir, f"audio.{ext}")


def upload_and_wait(file_path: str):
    gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    uploaded_file = gemini_client.files.upload(file=file_path)

    while True:
        file_info = gemini_client.files.get(name=uploaded_file.name)
        if file_info.state.name == "ACTIVE":
            break
        time.sleep(3)

    return uploaded_file


def ask_gemini(uploaded_file, topic: str) -> str:
    gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    prompt = f"""
Analyze this audio file.

Find the EXACT FIRST time this phrase is spoken:

"{topic}"

Return ONLY JSON:
{{ "timestamp": "HH:MM:SS" }}

Rules:
- Return FIRST occurrence
- Format strictly HH:MM:SS
- No extra text
"""

    response = gemini_client.models.generate_content(
        model="gemini-2.0-flash",
        contents=[uploaded_file, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "timestamp": types.Schema(type=types.Type.STRING)
                },
                required=["timestamp"],
            ),
        ),
    )

    result = json.loads(response.text)
    return result["timestamp"]


@app.post("/ask")
def ask(request: AskRequest):
    temp_file = None
    try:
        # 1️⃣ Download audio
        temp_file = download_audio(request.video_url)

        # 2️⃣ Upload to Gemini
        uploaded_file = upload_and_wait(temp_file)

        # 3️⃣ Ask Gemini
        timestamp = ask_gemini(uploaded_file, request.topic)

        return {
            "timestamp": timestamp,
            "video_url": request.video_url,
            "topic": request.topic
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if temp_file and os.path.exists(temp_file):
            os.remove(temp_file)