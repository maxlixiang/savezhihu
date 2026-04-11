FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

WORKDIR /app
COPY . /app

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y git tzdata && rm -rf /var/lib/apt/lists/*

ENV TZ="Asia/Shanghai"
# 🌟 核心修复：强制 Python 实时输出日志，绝不吞没报错！
ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "main_bot.py"]