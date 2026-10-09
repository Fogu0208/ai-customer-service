/** 五个 Agent 的展示元数据（与后端 agents/ 包一一对应） */

export interface AgentMeta {
  key: string
  name: string
  role: string
  icon: string
  color: string // tailwind 色阶基色
  desc: string
}

export const AGENTS: AgentMeta[] = [
  {
    key: 'supervisor',
    name: 'Supervisor',
    role: '调度总管',
    icon: '🧠',
    color: 'violet',
    desc: 'LangGraph 编排中枢，决定把任务分派给谁',
  },
  {
    key: 'intent_router',
    name: 'Intent Router',
    role: '意图识别',
    icon: '🎯',
    color: 'blue',
    desc: 'LLM 分类用户意图，输出结构化路由建议',
  },
  {
    key: 'knowledge_rag',
    name: 'Knowledge RAG',
    role: '知识问答',
    icon: '📚',
    color: 'emerald',
    desc: 'FAISS 检索长期记忆，生成带引用的回答',
  },
  {
    key: 'ticket_handler',
    name: 'Ticket Handler',
    role: '工单处理',
    icon: '🎫',
    color: 'amber',
    desc: '通过 MCP 工具创建/查询工单与订单',
  },
  {
    key: 'compliance_checker',
    name: 'Compliance',
    role: '合规审查',
    icon: '🛡️',
    color: 'rose',
    desc: '金融话术合规校验，不通过则触发重写',
  },
]

export function agentMeta(key: string): AgentMeta {
  return (
    AGENTS.find((a) => a.key === key) ?? {
      key,
      name: key || 'Assistant',
      role: '智能体',
      icon: '🤖',
      color: 'slate',
      desc: '',
    }
  )
}

export const INTENT_LABELS: Record<string, string> = {
  knowledge_rag: '知识问答',
  ticket_handler: '工单处理',
  compliance_checker: '合规审查',
  intent_router: '意图路由',
  supervisor: '调度',
  unknown: '未识别',
}
