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

import requests
import re
import xml.etree.ElementTree as ET


def extract_video_id(url: str) -> str:
    patterns = [
        r"v=([^&]+)",
        r"youtu\.be/([^?]+)"
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def seconds_to_hhmmss(seconds: float) -> str:
    seconds = int(float(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


@app.post("/ask")
def ask(request: AskRequest):
    try:
        video_id = extract_video_id(request.video_url)

        if not video_id:
            return {
                "timestamp": "00:00:00",
                "video_url": request.video_url,
                "topic": request.topic
            }

        transcript_url = f"https://video.google.com/timedtext?lang=en&v={video_id}"

        response = requests.get(transcript_url, timeout=10)

        if response.status_code != 200:
            return {
                "timestamp": "00:00:00",
                "video_url": request.video_url,
                "topic": request.topic
            }

        root = ET.fromstring(response.text)

        topic_lower = request.topic.lower()

        for child in root.findall("text"):
            text_content = child.text or ""
            if topic_lower in text_content.lower():
                start_time = child.attrib.get("start", "0")
                timestamp = seconds_to_hhmmss(start_time)

                return {
                    "timestamp": timestamp,
                    "video_url": request.video_url,
                    "topic": request.topic
                }

        # If not found
        return {
            "timestamp": "00:00:00",
            "video_url": request.video_url,
            "topic": request.topic
        }

    except Exception:
        return {
            "timestamp": "00:00:00",
            "video_url": request.video_url,
            "topic": request.topic
        }