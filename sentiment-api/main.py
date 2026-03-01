from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI
import os
from dotenv import load_dotenv
import json

load_dotenv()

client = OpenAI(
    api_key=os.getenv("AI_PIPE_TOKEN"),
    base_url=os.getenv("BASE_URL")
)

app = FastAPI()

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
