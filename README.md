# 知客调度台

基于 LangGraph 的智能客服多 Agent 系统。Supervisor 接收用户消息后按意图分派给知识问答、工单处理或合规审查，汇总结果后再做一次合规校验，最后通过 Vue 控制台展示对话、工具和指标。

## 架构

```
用户消息
   │
   ▼
Supervisor（路由）
   ├── Knowledge RAG   知识库检索与回答
   ├── Ticket Handler  工单创建与查询
   └── Compliance      直接进入合规审查
          │
          ▼
     Compliance Checker（所有回复必经）
          │
          ▼
     Supervisor（汇总回复）
```

| Agent | 职责 |
| --- | --- |
| Supervisor | LangGraph 编排中枢，决定分派并汇总子 Agent 结果 |
| Intent Router | 识别咨询、投诉、办理等意图，给出路由建议 |
| Knowledge RAG | 从长期记忆检索文档，生成带来源的回答 |
| Ticket Handler | 处理退款、开户、投诉等业务，创建或查询工单 |
| Compliance | 检查敏感词、个人身份信息和越权金融承诺 |

记忆分三层：

- **工作记忆**：当前会话上下文，进程内保存
- **短期记忆**：最近对话，优先写入 Redis；连不上 Redis 时回退到内存
- **长期记忆**：FAISS 向量库，启动时写入理财产品、退款政策和开户流程示例文档

内置 MCP 工具：`order_query`、`knowledge_search`、`ticket_create`、`risk_check`。

## 目录

```
python-impl/     FastAPI + LangGraph 后端
frontend/        Vue 3 + Vite 控制台（知客调度台）
docker-compose.yml
```

## 环境要求

- Python 3.12
- Node.js 20+
- 一个兼容 OpenAI 接口的模型密钥
- Redis 7（可选，用于跨进程保存会话）

## 本地启动

### 1. 后端

```powershell
cd python-impl
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

编辑 `.env`，至少填入 `OPENAI_API_KEY`。需要自定义网关时同时修改 `OPENAI_BASE_URL` 和 `MODEL_NAME`。

```powershell
python -m api.main
```

服务默认监听 `http://localhost:8000`。健康检查：`GET /health`。

### 2. 前端

```powershell
cd frontend
npm install
npm run dev
```

浏览器打开 `http://localhost:5173`。Vite 会把 `/api` 和 `/health` 代理到 `http://localhost:8000`。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/chat` | 发送消息，返回回复、会话 ID、意图和合规结果 |
| `GET` | `/api/history/{session_id}` | 读取会话历史 |
| `GET` | `/api/tools` | 列出 MCP 工具 |
| `POST` | `/api/tools/call` | 调用指定工具 |
| `GET` | `/api/metrics` | Agent 指标与最近工具调用 |
| `GET` | `/health` | 健康检查 |

`POST /api/chat` 请求体：

```json
{
  "message": "理财产品A的年化收益率是多少？",
  "user_id": "anonymous",
  "session_id": null
}
```

## 环境变量

见 `python-impl/.env.example`。

| 变量 | 说明 |
| --- | --- |
| `OPENAI_API_KEY` | 模型密钥 |
| `OPENAI_BASE_URL` | 接口地址，默认 `https://api.openai.com/v1` |
| `MODEL_NAME` | 模型名，默认 `gpt-4o` |
| `REDIS_URL` | 短期记忆，默认 `redis://localhost:6379/0` |
| `FAISS_INDEX_PATH` | 向量索引路径 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | 追踪导出地址；留空则输出到控制台 |
| `HOST` / `PORT` | 服务监听地址，默认 `0.0.0.0:8000` |

```

先在仓库根目录准备好 `OPENAI_API_KEY`。Jaeger 界面在 `http://localhost:16686`，后端在 `http://localhost:8000`。

## 许可证

MIT，见 [LICENSE](LICENSE)。
