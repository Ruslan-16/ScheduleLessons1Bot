import os
from dotenv import load_dotenv

load_dotenv()

print("BOT_TOKEN:", os.getenv("BOT_TOKEN"))
print("ADMIN_ID:", os.getenv("ADMIN_ID"))
print("S3_ACCESS_KEY:", os.getenv("S3_ACCESS_KEY"))
print("S3_SECRET_KEY:", os.getenv("S3_SECRET_KEY"))
print("S3_BUCKET_NAME:", os.getenv("S3_BUCKET_NAME"))
print("S3_ENDPOINT_URL:", os.getenv("S3_ENDPOINT_URL"))
