#!/bin/bash

# Start Flask app in the foreground with the specified backend
exec python /app/y_social.py --host 0.0.0.0 --port 5000
