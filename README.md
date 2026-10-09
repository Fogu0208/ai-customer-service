# 知客调度台

基于 LangGraph 的智能客服多 Agent 系统。Supervisor 调用意图识别 Agent 得到结构化意图后，分派给知识问答、工单处理或风险升级流程，所有回复经过合规审查后再汇总输出，最后通过 Vue 控制台展示对话、工具和指标。

## 架构

```
用户消息
   │
   ▼
Supervisor（调用 Intent Router 做结构化意图识别）
   ├── 咨询类      → Knowledge RAG     知识库检索与回答
   ├── 办理类      → Ticket Handler    工单创建与查询
   └── 资金安全类  → 风险升级（紧急工单 + 转人工）→ Knowledge RAG 给出安全指引
          │
          ▼
     Compliance Checker（所有回复必经）
          │
          ▼
     Supervisor（汇总回复）
```


| Agent          | 职责                                            |
| -------------- | --------------------------------------------- |
| Supervisor     | LangGraph 编排中枢，按意图分派并汇总子 Agent 结果             |
| Intent Router  | 输出一级/二级意图、置信度、关键实体和建议路由，结合最近 4 轮对话理解追问       |
| Knowledge RAG  | Query 改写、向量召回、LLM 重排，生成带来源的回答                 |
| Ticket Handler | 处理退款、开户、投诉等业务，创建或查询工单；资金安全事件直接建紧急工单并升级人工     |
| Compliance     | 两阶段审查：规则引擎拦截明确的个人信息泄露，疑似违规用语交给 LLM 结合语境复核     |


记忆分三层：

- **工作记忆**：当前会话上下文，进程内保存
- **短期记忆**：最近对话，优先写入 Redis；连不上 Redis 时回退到内存
- **长期记忆**：FAISS 向量库，用 `BAAI/bge-m3` 向量化。启动时加载 `python-impl/data/knowledge_base/` 下的 21 篇金融客服 FAQ，索引持久化到 `vector_store/`，重启时直接读取；Embedding 不可用时降级为中文二元组关键词检索

内置 MCP 工具：`order_query`、`knowledge_search`、`ticket_create`、`risk_check`。

## 目录

```
python-impl/     FastAPI + LangGraph 后端
  data/          知识库文档
  eval/          离线评测集与评测脚本
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

编辑 `.env`，至少填入 `OPENAI_API_KEY`。需要自定义网关时同时修改 `OPENAI_BASE_URL` 和 `MODEL_NAME`。所用网关需要同时提供 `/embeddings` 接口（如硅基流动），否则请单独配置 `EMBEDDING_BASE_URL` 和 `EMBEDDING_API_KEY`。

修改或删除知识库文档后，请删除 `python-impl/vector_store/` 让索引重建。

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


| 方法     | 路径                          | 说明                      |
| ------ | --------------------------- | ----------------------- |
| `POST` | `/api/chat`                 | 发送消息，返回回复、会话 ID、意图和合规结果 |
| `GET`  | `/api/history/{session_id}` | 读取会话历史                  |
| `GET`  | `/api/tools`                | 列出 MCP 工具               |
| `POST` | `/api/tools/call`           | 调用指定工具                  |
| `GET`  | `/api/metrics`              | Agent 指标与最近工具调用         |
| `GET`  | `/health`                   | 健康检查                    |


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


| 变量                            | 说明                                  |
| ----------------------------- | ----------------------------------- |
| `OPENAI_API_KEY`              | 模型密钥                                |
| `OPENAI_BASE_URL`             | 接口地址，默认 `https://api.openai.com/v1` |
| `MODEL_NAME`                  | 模型名，默认 `gpt-4o`                     |
| `REDIS_URL`                   | 短期记忆，默认 `redis://localhost:6379/0`  |
| `FAISS_INDEX_PATH`            | 向量索引路径                              |
| `EMBEDDING_MODEL`             | 向量化模型，默认 `BAAI/bge-m3`              |
| `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` | Embedding 接口地址与密钥，留空则复用 `OPENAI_*` |
| `KNOWLEDGE_BASE_DIR`          | 知识库目录，默认 `python-impl/data/knowledge_base` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | 追踪导出地址；留空则输出到控制台                    |
| `HOST` / `PORT`               | 服务监听地址，默认 `0.0.0.0:8000`            |


## 离线评测

`python-impl/eval/datasets/` 下有三份人工标注的评测集：

| 文件                 | 条数 | 内容                                    |
| ------------------ | -- | ------------------------------------- |
| `routing.jsonl`    | 48 | 用户问题及应路由到的 Agent                      |
| `retrieval.jsonl`  | 42 | 口语化问题及应命中的知识库文档                       |
| `compliance.jsonl` | 40 | 客服回复及是否应拦截，含个人信息、违规用语、越权承诺、不当言论和易误判的正常回复 |
| `compliance_holdout.jsonl` | 25 | 合规留出集，改进合规审查后新写，只用于验证、不参与调优 |

```powershell
cd python-impl
python -m eval.run_eval                      # 全部评测
python -m eval.run_eval --suite retrieval    # 单项：routing / retrieval / compliance
python -m eval.run_eval --limit 5            # 每项只取前 5 条
python -m eval.run_eval --suite compliance --compliance-set compliance_holdout.jsonl
```

报告和逐条明细保存在 `python-impl/eval/results/`。以 Qwen2.5-7B-Instruct + bge-m3 为例：

| 评测项 | 改进前 | 改进后 |
| --- | --- | --- |
| 路由准确率 | 81.2%（直接 prompt 输出 Agent 名） | 93.8%（结构化意图识别） |
| 资金安全类路由召回 | 25.0% | 83.3% |
| 检索 Recall@1 | 78.6%（关键词） | 95.2%（向量），97.6%（改写+向量+重排） |
| 合规 F1（开发集 40 条） | 0.889 | 1.000 |
| 合规 F1（留出集 25 条） | 0.933 | 1.000 |

合规开发集上的改进参考了该集合的错例（否定语境、订单号、尾号展示），留出集数字更能代表泛化效果；两份数据量都较小，结论仅供参考。

## 许可证

MIT，见 [LICENSE](LICENSE)。