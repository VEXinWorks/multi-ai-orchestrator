#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Simple WhatsApp Business webhook handler using Flask.

This script receives incoming messages, classifies intent (greeting, quote_request, complaint),
sends templated responses. Includes sample Flask routes for /webhook and /healthz.
No external API calls (mock responses).

Usage example:
    python3 vexin_whatsapp_bot.py --help
"""

import argparse
from flask import Flask, request, jsonify

app = Flask(__name__)

class IntentClassifier:
    def classify(self, message: str) -> str:
        if "hello" in message.lower():
            return "greeting"
        elif "quote" in message.lower() and "request" in message.lower():
            return "quote_request"
        else:
            return "complaint"

def send_response(intent: str, message: str) -> dict:
    responses = {
        "greeting": {"text": "Hello! How can I help you?"},
        "quote_request": {"text": "Please provide more information about the quote request."},
        "complaint": {"text": "Sorry to hear that. Please contact our support team."}
    }
    return jsonify(responses[intent])

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        message = request.json['message']
        classifier = IntentClassifier()
        intent = classifier.classify(message)
        response = send_response(intent, message)
        return response
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/healthz', methods=['GET'])
def healthz():
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='WhatsApp Business webhook handler')
    parser.add_argument('--host', default='0.0.0.0', help='Host IP address')
    parser.add_argument('--port', type=int, default=5000, help='Server port number')
    args = parser.parse_args()
    
    app.run(host=args.host, port=args.port)