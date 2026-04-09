FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

WORKDIR /app
COPY . /app

# 🌟 核心修复：告诉系统这是静默安装，千万别弹窗问问题！
ENV DEBIAN_FRONTEND=noninteractive

# 安装 git 和 tzdata
RUN apt-get update && apt-get install -y git tzdata && rm -rf /var/lib/apt/lists/*

# 设置北京时间
ENV TZ="Asia/Shanghai"

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "main_bot.py"]