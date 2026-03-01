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

# ----------------------------
# APP + CORS
# ----------------------------

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# AI PIPE (Sentiment Analysis)
# ----------------------------

ai_pipe_client = OpenAI(
    api_key=os.getenv("AI_PIPE_TOKEN"),
    base_url=os.getenv("AI_PIPE_BASE_URL")
)

# ----------------------------
# 1️⃣ SENTIMENT ENDPOINT
# ----------------------------

class CommentRequest(BaseModel):
    comment: str


@app.post("/comment")
async def analyze_comment(request: CommentRequest):
    try:
        response = ai_pipe_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Return ONLY valid JSON with fields: sentiment (positive, negative, neutral) and rating (1-5)."
                },
                {
                    "role": "user",
                    "content": request.comment
                }
            ],
            temperature=0
        )

        parsed = json.loads(response.choices[0].message.content)
        return parsed

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ----------------------------
# 2️⃣ CODE INTERPRETER
# ----------------------------

class CodeRequest(BaseModel):
    code: str


class ErrorAnalysis(BaseModel):
    error_lines: List[int]


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


def analyze_error_with_ai(code: str, tb: str) -> List[int]:
    # 🔥 First: deterministic extraction from traceback
    match = re.search(r'File "<string>", line (\d+)', tb)
    if not match:
        match = re.search(r'File "", line (\d+)', tb)

    if match:
        return [int(match.group(1))]

    # Fallback to Gemini
    try:
        gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

        prompt = f"""
Identify the exact line number(s) where the error occurred.

CODE:
{code}

TRACEBACK:
{tb}

Return only JSON:
{{ "error_lines": [line_numbers] }}
"""

        response = gemini_client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "error_lines": types.Schema(
                            type=types.Type.ARRAY,
                            items=types.Schema(type=types.Type.INTEGER),
                        )
                    },
                    required=["error_lines"],
                ),
            ),
        )

        result = ErrorAnalysis.model_validate_json(response.text)
        return result.error_lines

    except Exception:
        return []


@app.post("/code-interpreter")
def code_interpreter(request: CodeRequest):
    execution = execute_python_code(request.code)

    if execution["success"]:
        return {
            "error": [],
            "result": execution["output"]
        }

    error_lines = analyze_error_with_ai(request.code, execution["output"])

    return {
        "error": error_lines,
        "result": execution["output"]
    }


# ----------------------------
# 3️⃣ YOUTUBE TIMESTAMP FINDER
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
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
        ext = info["ext"]

    return os.path.join(temp_dir, f"audio.{ext}")


def upload_audio_to_gemini(file_path: str):
    gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    uploaded_file = gemini_client.files.upload(file=file_path)

    # Poll until ACTIVE
    while True:
        file_info = gemini_client.files.get(name=uploaded_file.name)
        if file_info.state.name == "ACTIVE":
            break
        time.sleep(2)

    return uploaded_file


def find_timestamp(uploaded_file, topic: str) -> str:
    gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    response = gemini_client.models.generate_content(
        model="gemini-2.0-flash",
        contents=[
            uploaded_file,
            f"""
Find the FIRST timestamp where this topic is spoken in the audio.

Topic: {topic}

Return ONLY JSON:
{{ "timestamp": "HH:MM:SS" }}

Format MUST be exactly HH:MM:SS.
"""
        ],
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

def seconds_to_hhmmss(seconds: float) -> str:
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

@app.post("/ask")
def ask(request: AskRequest):
    try:
        ydl_opts = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitlesformat": "vtt",
            "quiet": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(request.video_url, download=False)

        # Get subtitles
        subtitles = info.get("automatic_captions") or info.get("subtitles")

        if not subtitles:
            raise HTTPException(status_code=400, detail="No captions available")

        # Pick English
        en_subs = subtitles.get("en") or list(subtitles.values())[0]

        # Download subtitle content
        subtitle_url = en_subs[0]["url"]

        import requests
        response = requests.get(subtitle_url)
        vtt_text = response.text

        # Parse VTT
        lines = vtt_text.split("\n")

        for i in range(len(lines)):
            if request.topic.lower() in lines[i].lower():
                # Timestamp is previous line
                timestamp_line = lines[i-1]
                start_time = timestamp_line.split(" --> ")[0]

                # Convert HH:MM:SS.mmm to HH:MM:SS
                hhmmss = start_time.split(".")[0]

                return {
                    "timestamp": hhmmss,
                    "video_url": request.video_url,
                    "topic": request.topic
                }

        # If not found
        return {
            "timestamp": "00:00:00",
            "video_url": request.video_url,
            "topic": request.topic
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
