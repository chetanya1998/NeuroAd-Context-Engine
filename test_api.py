import requests

response = requests.post(
    "http://127.0.0.1:8000/api/media/upload-url",
    json={"url": "https://www.youtube.com/watch?v=ntz2c2z54dg"}
)
print("Status:", response.status_code)
print("Body:", response.text)
