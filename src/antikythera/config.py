import os

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Message transport between orchestrator and actors: "mqtt", "nats" or "zenoh"
TRANSPORT = os.getenv("ANTIKYTHERA_TRANSPORT", "mqtt").lower()

# Storage backend of the orchestrator service: "redis", "nats", "zenoh" or "memory"
STORAGE = os.getenv("ANTIKYTHERA_STORAGE", "redis").lower()

# NATS Configuration, used when TRANSPORT or STORAGE is "nats"
NATS_URL = os.getenv("NATS_URL", "nats://127.0.0.1:4222")
NATS_STORAGE_PREFIX = os.getenv("NATS_STORAGE_PREFIX", "antikythera")

# Zenoh Configuration, used when TRANSPORT or STORAGE is "zenoh".
# ZENOH_CONNECT lists endpoints separated by commas; ZENOH_CONFIG names a Zenoh JSON5
# configuration file to start from instead (its endpoints win over ZENOH_CONNECT).
ZENOH_CONNECT = os.getenv("ZENOH_CONNECT", "tcp/127.0.0.1:7447")
ZENOH_MODE = os.getenv("ZENOH_MODE") or None
ZENOH_CONFIG = os.getenv("ZENOH_CONFIG") or None
ZENOH_STORAGE_PREFIX = os.getenv("ZENOH_STORAGE_PREFIX", "antikythera/storage")

# Redis Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# MQTT Broker Configuration
MQTT_BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "127.0.0.1")
MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", 1883))

# Re-dispatch configuration
REDISPATCH_BASE_DELAY = int(os.getenv("REDISPATCH_BASE_DELAY", 2))
REDISPATCH_MAX_DELAY = int(os.getenv("REDISPATCH_MAX_DELAY", 90))
MAX_REDISPATCHES = int(os.getenv("MAX_REDISPATCHES", 5))
