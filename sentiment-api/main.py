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
import requests
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================
# 1️⃣ SENTIMENT (AI PIPE)
# =========================================================

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


# =========================================================
# 2️⃣ CODE INTERPRETER
# =========================================================

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


def extract_exec_line(traceback_text: str) -> List[int]:
    match = re.search(r'File "<string>", line (\d+)', traceback_text)
    if match:
        return [int(match.group(1))]
    return []


@app.post("/code-interpreter")
def code_interpreter(request: CodeRequest):
    execution = execute_python_code(request.code)

    if execution["success"]:
        return {
            "error": [],
            "result": execution["output"]
        }

    error_lines = extract_exec_line(execution["output"])

    return {
        "error": error_lines,
        "result": execution["output"]
    }


# =========================================================
# 3️⃣ YOUTUBE TRANSCRIPT TIMESTAMP FINDER
# =========================================================

class AskRequest(BaseModel):
    video_url: str
    topic: str


def extract_video_id(url: str) -> str:
    match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11})", url)
    if not match:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    return match.group(1)


def seconds_to_hhmmss(seconds: float) -> str:
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def get_transcript_text(video_id: str) -> str:
    yt = YouTubeTranscriptApi()
    transcript = yt.fetch(video_id)

    # Convert to raw data list
    transcript_list = transcript.to_raw_data()

    formatted = ""
    for entry in transcript_list:
        timestamp = seconds_to_hhmmss(entry["start"])
        text = entry["text"].replace("\n", " ")
        formatted += f"[{timestamp}] {text}\n"

    return formatted

def ask_gemini_for_timestamp(transcript: str, topic: str) -> str:

    headers = {
        "Authorization": f"Bearer {os.getenv('AI_PIPE_TOKEN')}",
        "Content-Type": "application/json",
    }

    prompt = f"""
You are a precise timestamp finder.

Below is a transcript with timestamps in HH:MM:SS format.

Find the FIRST moment where the speaker discusses:

"{topic}"

Rules:
- Return FIRST occurrence only
- Timestamp must be exactly HH:MM:SS
- No explanation
- Return ONLY JSON

Transcript:
{transcript}

Return ONLY:
{{ "timestamp": "HH:MM:SS" }}
"""

    payload = {
        "model": "google/gemini-2.0-flash-001",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.0,
    }

    response = requests.post(
        os.getenv("AI_PIPE_BASE_URL") + "/chat/completions",
        headers=headers,
        json=payload,
        timeout=60
    )

    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="AI API error")

    raw = response.json()["choices"][0]["message"]["content"].strip()

    # Remove markdown if present
    if raw.startswith("```"):
        raw = "\n".join([l for l in raw.split("\n") if not l.startswith("```")]).strip()

    try:
        result = json.loads(raw)
        return result.get("timestamp", "00:00:00")
    except:
        match = re.search(r"\d{2}:\d{2}:\d{2}", raw)
        if match:
            return match.group(0)
        return "00:00:00"


@app.post("/ask")
def ask(request: AskRequest):
    try:
        video_id = extract_video_id(request.video_url)

        transcript_text = get_transcript_text(video_id)

        timestamp = ask_gemini_for_timestamp(
            transcript_text,
            request.topic
        )

        return {
            "timestamp": timestamp,
            "video_url": request.video_url,
            "topic": request.topic
        }

    except TranscriptsDisabled:
        raise HTTPException(status_code=400, detail="Transcripts disabled")
    except NoTranscriptFound:
        raise HTTPException(status_code=400, detail="No transcript found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))