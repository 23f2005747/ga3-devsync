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

# Gemini
from google import genai
from google.genai import types

load_dotenv()

# ----------------------------
# AI PIPE (Sentiment Analysis)
# ----------------------------

client = OpenAI(
    api_key=os.getenv("AI_PIPE_TOKEN"),
    base_url=os.getenv("AI_PIPE_BASE_URL")
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# SENTIMENT ENDPOINT
# ----------------------------

class CommentRequest(BaseModel):
    comment: str


@app.post("/comment")
async def analyze_comment(request: CommentRequest):
    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a sentiment analysis system. Return ONLY valid JSON with fields: sentiment (positive, negative, neutral) and rating (1-5)."
                },
                {
                    "role": "user",
                    "content": request.comment
                }
            ],
            temperature=0
        )

        content = response.choices[0].message.content
        parsed = json.loads(content)

        return parsed

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ----------------------------
# CODE INTERPRETER SECTION
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


import re

def analyze_error_with_ai(code: str, tb: str) -> List[int]:
    # Match ONLY exec code traceback lines
    match = re.search(r'File "<string>", line (\d+)', tb)

    if not match:
        match = re.search(r'File "", line (\d+)', tb)

    if match:
        return [int(match.group(1))]

    # Fallback to Gemini if needed
    try:
        gemini_client = genai.Client(
            api_key=os.getenv("GEMINI_API_KEY")
        )

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

    else:
        error_lines = analyze_error_with_ai(
            request.code,
            execution["output"]
        )

        return {
            "error": error_lines,
            "result": execution["output"]
        }