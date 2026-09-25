# 后端服务镜像: Python 3.11 精简版
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 1. 先复制依赖清单并安装 (利用 Docker 分层缓存: 依赖变更频率远低于代码)
# PIP_INDEX_URL 可在构建时覆盖: 国内服务器传阿里云镜像加速, 默认官方源
COPY requirements.txt .
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} -r requirements.txt

# 2. 复制应用代码
COPY app ./app
COPY run.py .

# 3. 非 root 用户运行 (安全最佳实践: 即使被攻破也无法读写宿主系统)
RUN useradd -m appuser \
    && mkdir -p logs data \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# 生产模式启动: 不开启 reload, 多进程由外部编排(如 uvicorn --workers 或 K8s 多副本)负责
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
