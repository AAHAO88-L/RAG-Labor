# 劳动法智能助手 — RAG 问答系统

基于 RAG（检索增强生成）的劳动法知识问答系统，使用 ChromaDB 向量检索 + Deepseek API。

## 项目结构

```
├── app.py                    # Gradio 网页界面
├── api.py                    # FastAPI 后端（REST + SSE 流式）
├── auth.py                   # JWT 用户认证
├── database.py               # SQLite 数据库层（用户 + 对话）
├── launch.py                 # 一键启动脚本
├── main.py                   # RAG 检索核心 + 命令行入口
├── ingest.py                 # 构建 ChromaDB 索引
├── ui_helpers.py             # Gradio 界面辅助函数
├── static/
│   ├── style.css             # 界面样式
│   └── app.js                # 前端交互逻辑
├── models/
│   ├── embeddings.py         # BGE 向量模型
│   └── llm.py                # Deepseek API 调用
├── utils/
│   └── text_loader.py        # 文本文件加载
├── data/                     # 法律法规文本
├── .env                      # API 配置（不上传）
├── .env.example              # 配置模板
├── .gitignore
└── requirements.txt
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入必要的配置项：
#   DEEPSEEK_API_KEY  — Deepseek API Key
#   JWT_SECRET        — JWT 签名密钥（用 openssl rand -hex 32 生成）
#   CORS_ORIGINS      — 允许的前端来源（默认 http://127.0.0.1:7860）
```

### 3. 构建索引

```bash
python ingest.py
```

### 4. 启动

**一键启动（推荐）**：
```bash
python launch.py
```
同时启动 FastAPI 后端 (port 8000) + Gradio 界面 (port 7860)。

**分别启动**：
```bash
# 终端 1：启动 API
uvicorn api:app --host 127.0.0.1 --port 8000

# 终端 2：启动界面
python app.py
```

**命令行模式**：
```bash
python main.py --ask "劳动合同可以解除的情形有哪些？"
```

## 技术栈

- **向量模型**: BAAI/bge-large-zh-v1.5（本地运行，mean pooling）
- **向量检索**: ChromaDB（L2 距离，持久化存储）
- **查询增强**: 多路查询重写 + HyDE 假设文档嵌入
- **大语言模型**: Deepseek Chat API（流式输出）
- **后端**: FastAPI（SSE 流式 + JWT 认证）
- **前端**: Gradio（Chatbot UI）
- **存储**: SQLite（WAL 模式，线程复用连接）

## 安全说明

- `.env` 文件包含密钥，已在 `.gitignore` 中排除
- 生产环境请务必修改 `JWT_SECRET` 为强随机值
- API Key 泄露后请在 Deepseek 平台立即轮换
