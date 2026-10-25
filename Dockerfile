FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FU_WU_HOST=0.0.0.0 \
    PORT=8001 \
    MCP_HTTP_KAI_QI=false

WORKDIR /app

# onnxruntime / Pillow / chromadb 编译/运行所需的系统库
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libgomp1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN mkdir -p /data/文档库 /data/shu_ju /app/ri_zhi

ENV WEN_DANG_KU=/data/文档库 \
    SQLITE_LU_JING=/data/shu_ju/wen_dang_ku.db \
    CHROMA_LU_JING=/data/shu_ju/chroma \
    MO_XING_HUAN_CUN=/data/shu_ju/models \
    RI_ZHI_MU_LU=/data/shu_ju/logs \
    SHE_ZHI_WEN_JIAN=/data/shu_ju/she_zhi.json

EXPOSE 8001
CMD ["python", "run.py"]
