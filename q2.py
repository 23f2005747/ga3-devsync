from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI
import os
import json

app = FastAPI()

client = OpenAI()

class CommentRequest(BaseModel):
    comment: str

class SentimentResponse(BaseModel):
    sentiment: str
    rating: int


@app.post("/comment", response_model=SentimentResponse)
async def analyze_comment(request: CommentRequest):

    if not request.comment.strip():
        raise HTTPException(status_code=400, detail="Comment cannot be empty")

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a sentiment analysis engine."
                },
                {
                    "role": "user",
                    "content": f"""
Return STRICT JSON only.
Format:
{{
  "sentiment": "positive | negative | neutral",
  "rating": 1-5
}}

Comment: {request.comment}
"""
                }
            ],
            response_format={
                "type": "json_object"
            }
        )

        result = response.choices[0].message.content
        parsed = json.loads(result)

        return parsed

    except Exception as e:
        print("FULL ERROR:", e)
        raise HTTPException(status_code=500, detail=str(e))