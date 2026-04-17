import os

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Immudb Configuration
IMMUDB_USER = os.getenv("IMMUDB_USER", "immudb")
IMMUDB_PASSWORD = os.getenv("IMMUDB_PASSWORD", "immudb")
IMMUDB_HOST = os.getenv("IMMUDB_HOST", "localhost")
IMMUDB_PORT = int(os.getenv("IMMUDB_PORT", 3322))
IMMUDB_MAX_GRPC_MESSAGE_LENGTH = int(os.getenv("IMMUDB_MAX_GRPC_MESSAGE_LENGTH", 33554432))  # 32MB default

# Redis Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# MQTT Broker Configuration
MQTT_BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "127.0.0.1")
MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", 1883))
