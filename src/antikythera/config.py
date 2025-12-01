import os

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Immudb Configuration
IMMUDB_USER = os.getenv("IMMUDB_USER", "immudb")
IMMUDB_PASSWORD = os.getenv("IMMUDB_PASSWORD", "immudb")
