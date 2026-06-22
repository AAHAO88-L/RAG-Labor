# 劳动法智能助手 — RAG 问答系统

基于 RAG（检索增强生成）的劳动法知识问答系统，使用 FAISS 向量检索 + Deepseek API。

## 项目结构

```
├── app.py                    # Gradio 网页界面
├── main.py                   # 命令行入口
├── ingest.py                 # 构建向量索引
├── models/
│   ├── embeddings.py         # BGE 向量模型
│   └── llm.py                # Deepseek API 调用
├── utils/
│   └── text_loader.py        # 文本文件加载
├── data/
│   └── laws/                 # 法律法规文本
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

### 2. 配置 API Key

```bash
cp .env.example .env
# 编辑 .env，填入你的 Deepseek API Key
```

找到 Deepseek API Key：[platform.deepseek.com](https://platform.deepseek.com/)

### 3. 构建索引

```bash
python ingest.py
```

### 4. 启动

**命令行模式：**
```bash
python main.py ask "劳动合同可以解除的情形有哪些？"
```

**网页界面（推荐）：**
```bash
streamlit run app.py
```

## 技术栈

- **向量模型**: BAAI/bge-large-zh-v1.5（本地运行）
- **向量检索**: FAISS (IndexFlatL2)
- **大语言模型**: Deepseek Chat API
- **网页界面**: Streamlit

## 安全说明

- `.env` 文件包含你的 API Key，已在 `.gitignore` 中排除
- 上传到 GitHub 前请确认 `.env` 不会被提交
- 参考 `.env.example` 配置模板
