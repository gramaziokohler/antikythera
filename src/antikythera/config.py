import os

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

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
