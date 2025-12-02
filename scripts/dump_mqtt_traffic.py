#!/usr/bin/env python
"""
MQTT Traffic Recorder

Records MQTT messages from specified topics to a JSON file.
Press Ctrl+C to stop recording and save the file.

Usage:
    python mqtt_recorder.py [output_file] [topic1] [topic2] ...

Example:
    python mqtt_recorder.py mqtt_log.json "sensor/#" "device/status"
"""

import sys
import json
from datetime import datetime
import paho.mqtt.client as mqtt


class MQTTRecorder:
    def __init__(self, broker="localhost", port=1883, output_file="mqtt_log.json", topics=None):
        self.broker = broker
        self.port = port
        self.output_file = output_file
        self.topics = topics or ["#"]  # Subscribe to all topics by default
        self.messages = []
        self.client = mqtt.Client()
        self.running = False

        # Set up MQTT callbacks
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect

    def on_connect(self, client, userdata, flags, rc):
        """Callback when connected to MQTT broker"""
        if rc == 0:
            print(f"Connected to MQTT broker at {self.broker}:{self.port}")
            for topic in self.topics:
                client.subscribe(topic)
                print(f"Subscribed to topic: {topic}")
        else:
            print(f"Connection failed with code {rc}")

    def on_message(self, client, userdata, msg):
        """Callback when a message is received"""
        timestamp = datetime.now().isoformat()

        # Try to decode payload as string, fall back to hex if it fails
        try:
            payload = msg.payload.decode("utf-8")
        except UnicodeDecodeError:
            payload = msg.payload.hex()

        message_data = {"timestamp": timestamp, "topic": msg.topic, "payload": payload, "qos": msg.qos, "retain": msg.retain}

        self.messages.append(message_data)
        print(f"[{timestamp}] {msg.topic}: {payload}")

    def on_disconnect(self, client, userdata, rc):
        """Callback when disconnected from MQTT broker"""
        if rc != 0:
            print(f"Unexpected disconnect (code: {rc})")

    def save_messages(self):
        """Save recorded messages to JSON file"""
        try:
            with open(self.output_file, "w") as f:
                json.dump(self.messages, f, indent=2)
            print(f"\n{len(self.messages)} messages saved to {self.output_file}")
        except Exception as e:
            print(f"Error saving messages: {e}")

    def start(self):
        """Start recording MQTT traffic"""
        print(f"Starting MQTT recorder...")
        print(f"Output file: {self.output_file}")
        print(f"Topics: {', '.join(self.topics)}")
        print("Press Ctrl+C to stop recording\n")

        try:
            self.client.connect(self.broker, self.port, 60)
            self.running = True
            self.client.loop_forever()
        except KeyboardInterrupt:
            print("\n\nStopping recorder...")
        except Exception as e:
            print(f"Error: {e}")
        finally:
            self.stop()

    def stop(self):
        """Stop recording and save messages"""
        if self.running:
            self.running = False
            self.client.disconnect()
            self.save_messages()


def main():
    """Main entry point"""
    # Parse command line arguments
    output_file = "mqtt_log.json"
    topics = ["#"]

    if len(sys.argv) > 1:
        output_file = sys.argv[1]

    if len(sys.argv) > 2:
        topics = sys.argv[2:]

    # Create and start recorder
    recorder = MQTTRecorder(broker="localhost", port=1883, output_file=output_file, topics=topics)

    recorder.start()


if __name__ == "__main__":
    main()