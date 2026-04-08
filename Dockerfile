# 使用 Playwright 官方 Python 镜像，自带无头浏览器底层依赖，极其稳定
FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

WORKDIR /app

# 复制当前目录下所有文件到容器内
COPY . /app

# 安装 Python 库
RUN pip install --no-cache-dir -r requirements.txt

# 运行 TG 机器人主程序
CMD ["python", "main_bot.py"]