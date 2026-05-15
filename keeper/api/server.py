"""Keeper HTTP API Server — FastAPI 实现

提供 REST API + WebSocket 接口，支持：
- 自然语言查询（Agent 模式 / Classic 模式）
- WebSocket 流式输出（Agent 工具调用实时推送）
- 系统状态查询
- 巡检历史查询
- Runbook 执行
- 健康检查

安全：
- Bearer Token 认证（KEEPER_API_TOKEN 环境变量）
- Rate Limiting（每分钟 60 次请求/IP）
- CORS 白名单

启动方式：
    python -m keeper.api.server
    uvicorn keeper.api.server:app --host 0.0.0.0 --port 8900
"""
import os
import time
import asyncio
import json
from typing import Optional, Dict, Any, List
from collections import defaultdict
from dataclasses import dataclass

try:
    from fastapi import FastAPI, HTTPException, Depends, Header, WebSocket, WebSocketDisconnect, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel, Field
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

from ..config import AppConfig


# ─── Pydantic 请求/响应模型 ───────────────────────────────────

if FASTAPI_AVAILABLE:

    class QueryRequest(BaseModel):
        """自然语言查询请求"""
        query: str = Field(..., description="自然语言查询文本", examples=["检查本机服务器状态"])
        mode: str = Field("agent", description="运行模式：agent（智能模式）或 classic（经典路由）")
        context: Optional[Dict[str, Any]] = Field(None, description="可选上下文信息")

    class QueryResponse(BaseModel):
        """查询响应"""
        success: bool = Field(..., description="是否执行成功")
        response: str = Field(..., description="Agent 回复文本")
        mode: str = Field(..., description="实际使用的模式")
        tools_used: List[str] = Field(default_factory=list, description="本次调用的工具列表")
        duration_ms: int = Field(0, description="执行耗时（毫秒）")

    class StatusResponse(BaseModel):
        """系统状态响应"""
        version: str = Field(..., description="Keeper 版本号")
        llm_configured: bool = Field(..., description="LLM 是否已配置")
        llm_provider: str = Field("", description="LLM 提供商")
        llm_model: str = Field("", description="当前模型")
        mode: str = Field("agent", description="默认运行模式")
        uptime_seconds: int = Field(..., description="运行时间（秒）")
        tools_count: int = Field(0, description="可用工具数量")

    class HealthResponse(BaseModel):
        """健康检查响应"""
        status: str = Field(..., description="健康状态", examples=["ok"])
        version: str = Field(..., description="版本号")
        timestamp: str = Field(..., description="服务器时间")

    class RunbookRequest(BaseModel):
        """Runbook 执行请求"""
        name: str = Field(..., description="Runbook 名称", examples=["disk_cleanup"])
        variables: Optional[Dict[str, str]] = Field(None, description="运行时变量覆盖")
        auto_confirm: bool = Field(False, description="是否自动确认破坏性步骤")

    class RunbookResponse(BaseModel):
        """Runbook 执行响应"""
        success: bool
        summary: str
        steps_completed: int
        steps_total: int

    class ErrorResponse(BaseModel):
        """错误响应"""
        detail: str
        error_code: str = "UNKNOWN"


# ─── Rate Limiter ────────────────────────────────────────────

class RateLimiter:
    """简单的内存 Rate Limiter（基于滑动窗口）"""

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: Dict[str, List[float]] = defaultdict(list)

    def is_allowed(self, client_id: str) -> bool:
        """检查客户端是否被限流"""
        now = time.time()
        window_start = now - self.window_seconds

        # 清理过期记录
        self._requests[client_id] = [
            t for t in self._requests[client_id] if t > window_start
        ]

        # 检查是否超限
        if len(self._requests[client_id]) >= self.max_requests:
            return False

        # 记录本次请求
        self._requests[client_id].append(now)
        return True

    def get_remaining(self, client_id: str) -> int:
        """获取剩余配额"""
        now = time.time()
        window_start = now - self.window_seconds
        recent = [t for t in self._requests.get(client_id, []) if t > window_start]
        return max(0, self.max_requests - len(recent))


# ─── 应用创建 ────────────────────────────────────────────────

def create_app() -> "FastAPI":
    """创建 FastAPI 应用"""
    if not FASTAPI_AVAILABLE:
        raise ImportError("FastAPI 未安装，请运行: pip install fastapi uvicorn")

    app = FastAPI(
        title="Keeper API",
        description=(
            "Keeper 智能运维 Agent HTTP API\n\n"
            "提供自然语言驱动的服务器管理能力，支持 REST 和 WebSocket 两种接入方式。\n\n"
            "## 认证\n"
            "所有 `/api/v1/*` 接口需要 Bearer Token 认证：\n"
            "```\nAuthorization: Bearer <your-token>\n```\n"
            "Token 通过环境变量 `KEEPER_API_TOKEN` 配置。\n\n"
            "## WebSocket\n"
            "WebSocket 接口 `/ws/query` 支持流式输出，实时推送工具调用过程。"
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS
    allowed_origins = os.getenv("KEEPER_CORS_ORIGINS", "*").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 全局状态
    app.state.config = AppConfig.from_env()
    app.state.start_time = time.time()
    app.state.agent = None
    app.state.rate_limiter = RateLimiter(
        max_requests=int(os.getenv("KEEPER_RATE_LIMIT", "60")),
        window_seconds=60,
    )

    # ─── 认证依赖 ─────────────────────────────────────────

    API_TOKEN = os.getenv("KEEPER_API_TOKEN", "")

    async def verify_token(authorization: Optional[str] = Header(None)):
        """Bearer Token 认证"""
        if not API_TOKEN:
            return  # 未配置 token 则跳过认证
        if not authorization:
            raise HTTPException(status_code=401, detail="Missing Authorization header")
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid token format, use: Bearer <token>")
        token = authorization[7:]
        if token != API_TOKEN:
            raise HTTPException(status_code=403, detail="Invalid or expired token")

    # ─── Rate Limiting 中间件 ─────────────────────────────

    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        """请求频率限制中间件"""
        # 跳过健康检查和文档
        if request.url.path in ("/health", "/docs", "/redoc", "/openapi.json"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        limiter = app.state.rate_limiter

        if not limiter.is_allowed(client_ip):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests, please try again later", "error_code": "RATE_LIMITED"},
                headers={"Retry-After": "60"},
            )

        response = await call_next(request)
        # 添加 Rate Limit 头
        response.headers["X-RateLimit-Limit"] = str(limiter.max_requests)
        response.headers["X-RateLimit-Remaining"] = str(limiter.get_remaining(client_ip))
        return response

    # ─── 路由 ─────────────────────────────────────────────

    @app.get("/health", response_model=HealthResponse, tags=["系统"])
    async def health():
        """健康检查（无需认证）

        用于负载均衡器/K8s 探针的健康检查端点。
        """
        from datetime import datetime
        return HealthResponse(
            status="ok",
            version="1.0.0",
            timestamp=datetime.now().isoformat(),
        )

    @app.get("/api/v1/status", response_model=StatusResponse, dependencies=[Depends(verify_token)], tags=["系统"])
    async def get_status():
        """获取系统状态

        返回 Keeper 运行状态、LLM 配置信息和可用工具数量。
        """
        config = app.state.config
        uptime = int(time.time() - app.state.start_time)
        from ..agent.tools_registry import ALL_TOOLS
        return StatusResponse(
            version="1.0.0",
            llm_configured=config.is_llm_configured(),
            llm_provider=config.llm.provider,
            llm_model=config.llm.model,
            mode="agent",
            uptime_seconds=uptime,
            tools_count=len(ALL_TOOLS),
        )

    @app.post("/api/v1/query", response_model=QueryResponse, dependencies=[Depends(verify_token)], tags=["Agent"])
    async def query(req: QueryRequest):
        """自然语言查询（核心接口）

        发送自然语言指令，Agent 自主选择工具并执行。
        支持 agent（智能多步推理）和 classic（经典路由）两种模式。

        **示例请求：**
        ```json
        {"query": "检查本机服务器状态", "mode": "agent"}
        {"query": "扫描漏洞 --host 192.168.1.100", "mode": "classic"}
        ```
        """
        config = app.state.config
        start = time.time()

        if req.mode == "agent":
            try:
                from ..agent.hybrid import HybridAgent
                if app.state.agent is None:
                    app.state.agent = HybridAgent(config)
                response = app.state.agent.process(req.query)
                tools = []
                if app.state.agent._agent_loop and app.state.agent._agent_loop.last_turn:
                    tools = [tc.tool_name for tc in app.state.agent._agent_loop.last_turn.tool_calls]
            except Exception as e:
                response = f"[错误] {str(e)}"
                tools = []
        else:
            try:
                from ..core.agent import Agent
                from ..nlu.langchain_engine import LangChainEngine, LLMProvider
                provider_map = {"openai_compatible": LLMProvider.OPENAI_COMPATIBLE, "anthropic": LLMProvider.ANTHROPIC}
                provider = provider_map.get(config.llm.provider, LLMProvider.OPENAI_COMPATIBLE)
                engine = LangChainEngine(provider=provider, api_key=config.llm.api_key, base_url=config.llm.base_url, model=config.llm.model)
                agent = Agent(nlu_engine=engine, config=config)
                response = agent.process(req.query)
                tools = []
            except Exception as e:
                response = f"[错误] {str(e)}"
                tools = []

        duration = int((time.time() - start) * 1000)

        return QueryResponse(
            success=not response.startswith("[错误]"),
            response=response,
            mode=req.mode,
            tools_used=tools,
            duration_ms=duration,
        )

    # ─── WebSocket 流式查询 ───────────────────────────────

    @app.websocket("/ws/query")
    async def ws_query(websocket: WebSocket):
        """WebSocket 流式查询

        连接后发送 JSON 消息进行查询，Agent 执行过程中实时推送事件。

        **认证：** 通过 query parameter `token` 或首条消息中的 `token` 字段。

        **客户端发送格式：**
        ```json
        {"type": "query", "query": "检查本机", "token": "your-token"}
        ```

        **服务端推送事件类型：**
        - `{"type": "thinking", "message": "..."}`
        - `{"type": "tool_call", "tool": "...", "args": {...}}`
        - `{"type": "tool_result", "tool": "...", "success": true, "duration_ms": 123}`
        - `{"type": "text", "content": "..."}`
        - `{"type": "done", "response": "...", "tools_used": [...], "duration_ms": 123}`
        - `{"type": "error", "message": "..."}`
        """
        await websocket.accept()

        # 认证（通过 query param 或首条消息）
        token_param = websocket.query_params.get("token", "")
        if API_TOKEN and token_param != API_TOKEN:
            # 等待首条消息中的 token
            pass  # 认证在消息处理中进行

        config = app.state.config

        try:
            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                except json.JSONDecodeError:
                    await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                    continue

                # 认证检查
                if API_TOKEN:
                    msg_token = msg.get("token", token_param)
                    if msg_token != API_TOKEN:
                        await websocket.send_json({"type": "error", "message": "Unauthorized"})
                        continue

                msg_type = msg.get("type", "query")
                if msg_type == "ping":
                    await websocket.send_json({"type": "pong"})
                    continue

                if msg_type != "query":
                    await websocket.send_json({"type": "error", "message": f"Unknown message type: {msg_type}"})
                    continue

                query_text = msg.get("query", "")
                if not query_text:
                    await websocket.send_json({"type": "error", "message": "Empty query"})
                    continue

                # 执行查询并流式推送
                start = time.time()
                try:
                    from ..agent.hybrid import HybridAgent
                    if app.state.agent is None:
                        app.state.agent = HybridAgent(config)

                    # 创建 WebSocket 流式回调
                    async def ws_callback(event):
                        if isinstance(event, dict):
                            await websocket.send_json(event)
                        else:
                            await websocket.send_json({"type": "text", "content": str(event)})

                    # 由于 HybridAgent.process 是同步的，在线程中运行
                    # 使用同步回调收集事件，然后异步发送
                    events_buffer = []

                    def sync_callback(event):
                        events_buffer.append(event)

                    app.state.agent.set_stream_callback(sync_callback)

                    # 在线程池中运行同步代码
                    loop = asyncio.get_event_loop()
                    response = await loop.run_in_executor(
                        None, app.state.agent.process, query_text
                    )

                    # 发送缓冲的事件
                    for evt in events_buffer:
                        if isinstance(evt, dict):
                            await websocket.send_json(evt)
                        else:
                            await websocket.send_json({"type": "text", "content": str(evt)})

                    # 发送完成消息
                    duration = int((time.time() - start) * 1000)
                    tools = []
                    if app.state.agent._agent_loop and app.state.agent._agent_loop.last_turn:
                        tools = [tc.tool_name for tc in app.state.agent._agent_loop.last_turn.tool_calls]

                    await websocket.send_json({
                        "type": "done",
                        "response": response,
                        "tools_used": tools,
                        "duration_ms": duration,
                    })

                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Agent 执行失败: {str(e)}",
                    })

        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    # ─── 历史与分析 ───────────────────────────────────────

    @app.get("/api/v1/history", dependencies=[Depends(verify_token)], tags=["数据"])
    async def get_history(host: Optional[str] = None, hours: int = 24, limit: int = 50):
        """巡检历史查询

        获取巡检数据的历史记录，支持按主机和时间范围过滤。
        """
        try:
            from ..storage.history import InspectionHistory
            history = InspectionHistory()
            if host:
                records = history.get_by_time_range(host, hours=hours)
            else:
                hosts = history.get_all_hosts()
                records = []
                for h in hosts[:10]:
                    records.extend(history.get_latest(h, n=5))

            return {
                "success": True,
                "count": len(records),
                "records": [
                    {
                        "host": r.host,
                        "timestamp": r.timestamp,
                        "cpu": r.cpu_percent,
                        "memory": r.memory_percent,
                        "disk": r.disk_percent,
                        "load": r.load_avg_1m,
                    }
                    for r in records[:limit]
                ],
            }
        except Exception as e:
            return {"success": False, "error": str(e), "records": []}

    @app.get("/api/v1/audit", dependencies=[Depends(verify_token)], tags=["数据"])
    async def get_audit_logs(hours: int = 24, host: Optional[str] = None, intent: Optional[str] = None, limit: int = 100):
        """获取审计日志

        查询 Agent 操作的审计记录。
        """
        from ..core.audit import AuditLogger
        audit = AuditLogger()
        records = audit.get_history(hours=hours, limit=limit, host=host, intent=intent)
        return {
            "success": True,
            "count": len(records),
            "records": [
                {
                    "timestamp": r.timestamp,
                    "intent": r.intent,
                    "host": r.host,
                    "result": r.result,
                    "response_time_ms": r.response_time_ms,
                }
                for r in records
            ],
        }

    # ─── Runbook ──────────────────────────────────────────

    @app.post("/api/v1/runbook/run", response_model=RunbookResponse, dependencies=[Depends(verify_token)], tags=["Runbook"])
    async def run_runbook(req: RunbookRequest):
        """执行 Runbook

        执行预定义的运维手册流程（磁盘清理、服务重启、日志轮转）。
        """
        try:
            from ..runbook.executor import RunbookExecutor, list_builtin_runbooks
            from pathlib import Path

            executor = RunbookExecutor(
                confirm_callback=lambda _: req.auto_confirm,
                output_callback=lambda _: None,
            )

            template_dir = Path(__file__).parent.parent / "runbook" / "templates"
            yaml_path = template_dir / f"{req.name}.yaml"

            if not yaml_path.exists():
                raise HTTPException(
                    status_code=404,
                    detail=f"Runbook '{req.name}' not found. Available: {list_builtin_runbooks()}",
                )

            runbook = executor.load_from_yaml(str(yaml_path))

            # 在线程池中执行（可能耗时）
            loop = asyncio.get_event_loop()
            success, summary = await loop.run_in_executor(
                None, executor.execute, runbook, req.variables
            )

            from ..runbook.models import StepStatus
            completed = sum(1 for s in runbook.steps if s.status == StepStatus.DONE)

            return RunbookResponse(
                success=success,
                summary=summary,
                steps_completed=completed,
                steps_total=len(runbook.steps),
            )
        except HTTPException:
            raise
        except Exception as e:
            return RunbookResponse(success=False, summary=str(e), steps_completed=0, steps_total=0)

    @app.get("/api/v1/runbooks", dependencies=[Depends(verify_token)], tags=["Runbook"])
    async def list_runbooks():
        """列出可用 Runbook

        返回所有内置的运维手册模板名称。
        """
        from ..runbook.executor import list_builtin_runbooks
        return {"runbooks": list_builtin_runbooks()}

    # ─── 工具列表 ─────────────────────────────────────────

    @app.get("/api/v1/tools", dependencies=[Depends(verify_token)], tags=["Agent"])
    async def list_tools():
        """列出 Agent 可用工具

        返回所有注册的 Agent 工具及其描述。
        """
        from ..agent.tools_registry import ALL_TOOLS
        tools = []
        for t in ALL_TOOLS:
            name = t.name if hasattr(t, "name") else t.__name__
            doc = (t.description if hasattr(t, "description") else t.__doc__) or ""
            tools.append({"name": name, "description": doc.split("\n")[0]})
        return {"tools": tools, "count": len(tools)}

    @app.get("/api/v1/memory", dependencies=[Depends(verify_token)], tags=["数据"])
    async def get_memory(n: int = 10, keyword: Optional[str] = None, host: Optional[str] = None):
        """获取 Agent 操作记忆

        查询 Agent 的长期记忆（跨会话持久化）。
        """
        from ..agent.memory import AgentMemory
        memory = AgentMemory()
        if keyword:
            entries = memory.search(keyword, limit=n)
        elif host:
            entries = memory.get_host_history(host, limit=n)
        else:
            entries = memory.get_recent(n)

        return {
            "success": True,
            "count": len(entries),
            "total": memory.count,
            "entries": [
                {
                    "timestamp": e.timestamp,
                    "user_input": e.user_input,
                    "tools_used": e.tools_used,
                    "conclusion": e.conclusion,
                    "host": e.host,
                    "category": e.category,
                }
                for e in entries
            ],
        }

    # ─── 异步批量操作接口 ─────────────────────────────────

    @app.post("/api/v1/batch/ping", dependencies=[Depends(verify_token)], tags=["批量操作"])
    async def batch_ping(hosts: List[str], count: int = 4):
        """并发 Ping 多台主机

        异步并发 ping 所有指定主机，返回各主机的连通性结果。
        """
        from ..utils.async_utils import async_ping_hosts
        results = await async_ping_hosts(hosts, count=count)
        return {"success": True, "count": len(results), "results": results}

    @app.post("/api/v1/batch/inspect", dependencies=[Depends(verify_token)], tags=["批量操作"])
    async def batch_inspect(hosts: List[str]):
        """异步批量服务器巡检

        并发巡检多台服务器，比同步 ThreadPoolExecutor 更高效。
        """
        from ..utils.async_utils import async_batch_inspect
        from ..tools.server import format_batch_report
        statuses = await async_batch_inspect(hosts, max_concurrency=10)
        thresholds = {"cpu": 80, "memory": 85, "disk": 90}
        return {
            "success": True,
            "count": len(statuses),
            "report": format_batch_report(statuses, thresholds),
            "hosts": [
                {
                    "host": s.host,
                    "cpu": s.cpu_percent,
                    "memory": s.memory_percent,
                    "disk": s.disk_percent,
                    "load": s.load_avg_1m,
                    "ssh_failed": s.ssh_failed,
                }
                for s in statuses
            ],
        }

    @app.post("/api/v1/batch/ports", dependencies=[Depends(verify_token)], tags=["批量操作"])
    async def batch_check_ports(targets: List[Dict[str, Any]]):
        """并发端口检测

        批量检测多个 host:port 的连通性。

        **请求体格式：**
        ```json
        [{"host": "192.168.1.1", "port": 80}, {"host": "192.168.1.2", "port": 443}]
        ```
        """
        from ..utils.async_utils import async_check_ports
        results = await async_check_ports(targets)
        return {"success": True, "count": len(results), "results": results}

    return app


# ─── 应用实例（供 uvicorn 直接引用）─────────────────────────

if FASTAPI_AVAILABLE:
    app = create_app()


# ─── 直接运行入口 ────────────────────────────────────────────

def main():
    """启动 API Server"""
    if not FASTAPI_AVAILABLE:
        print("[错误] FastAPI 未安装，请运行:")
        print("  pip install fastapi uvicorn")
        return

    import uvicorn

    host = os.getenv("KEEPER_API_HOST", "0.0.0.0")
    port = int(os.getenv("KEEPER_API_PORT", "8900"))

    print(f"[Keeper API] 启动中... http://{host}:{port}")
    print(f"[Keeper API] 文档: http://{host}:{port}/docs")
    print(f"[Keeper API] WebSocket: ws://{host}:{port}/ws/query")

    uvicorn.run(
        "keeper.api.server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
