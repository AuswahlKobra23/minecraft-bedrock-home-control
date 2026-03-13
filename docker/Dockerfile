FROM python:3.12-alpine
RUN apk add --no-cache docker-cli
WORKDIR /app
COPY bedrock_home_control.py .
CMD ["python3", "-u", "bedrock_home_control.py"]
