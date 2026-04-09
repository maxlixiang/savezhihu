FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

WORKDIR /app
COPY . /app

# 🌟 核心：安装 tzdata(时区数据) 和 git，并清理缓存减小体积
RUN apt-get update && apt-get install -y git tzdata && rm -rf /var/lib/apt/lists/*
# 🌟 强制将 Docker 系统时区设为北京时间
ENV TZ="Asia/Shanghai"

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "main_bot.py"]