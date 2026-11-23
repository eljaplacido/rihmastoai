"""The product's settings: every credential comes from the environment at run time."""

import os

DATA_DIR = os.environ.get("DATA_DIR", "data")
STORAGE_KEY_ID = os.environ.get("STORAGE_KEY_ID", "")
mail_api_token = os.environ.get("MAIL_API_TOKEN", "")
token_env = "MAIL_API_TOKEN"
reset_password = "please-reset-password"
