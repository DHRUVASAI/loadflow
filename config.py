import os

# Load environment variables from a local .env file if present.
# Keep this import safe so the app can start even if `python-dotenv` isn't installed yet.
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

# Read standard boto3 env var names.
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

# Legacy aliases kept for any existing references inside the codebase.
AWS_ACCESS_KEY = AWS_ACCESS_KEY_ID
AWS_SECRET_KEY = AWS_SECRET_ACCESS_KEY
AWS_REGION = AWS_DEFAULT_REGION

S3_BUCKET_NAME = "load-balancer-logs"
EC2_INSTANCE_TAGS = ["lb-server-1", "lb-server-2", "lb-server-3"]

OVERLOAD_THRESHOLD = 80
AUTO_REFRESH_INTERVAL = 3000

# Fallback to demo mode if AWS credentials are not configured.
# Credentials are considered "real" only if they don't look like the placeholder.
_demo_env = os.getenv("DEMO_MODE")
_placeholder = {"your_key_here", "your_secret_here", "", None}
_keys_present = (
    AWS_ACCESS_KEY_ID not in _placeholder
    and AWS_SECRET_ACCESS_KEY not in _placeholder
)
if _demo_env is not None:
    DEMO_MODE = str(_demo_env).strip().lower() in {"1", "true", "yes", "y", "on"}
else:
    DEMO_MODE = not _keys_present

DATABASE_PATH = "database.db"

