import os
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic(
    api_key=os.environ.get("RANDOM_API"), 
)
for message in client.messages.create(
    max_tokens=1024,
    messages=[{
        "content": "Hello, world",
        "role": "user",
    }],
    model="claude-opus-4-6",
):
  print(message)