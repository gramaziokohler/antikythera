import os

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Immudb Configuration
IMMUDB_USER = os.getenv("IMMUDB_USER", "immudb")
IMMUDB_PASSWORD = os.getenv("IMMUDB_PASSWORD", "immudb")
IMMUDB_MAX_GRPC_MESSAGE_LENGTH = int(os.getenv("IMMUDB_MAX_GRPC_MESSAGE_LENGTH", 33554432))  # 32MB default
