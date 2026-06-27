FROM python:3.11-slim

WORKDIR /app

# OpenCV runtime libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pdf_parser/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /tmp/figures

EXPOSE 8001

CMD ["uvicorn", "pdf_parser.main:app", "--host", "0.0.0.0", "--port", "8001"]
