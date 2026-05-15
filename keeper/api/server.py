"""Keeper HTTP API Server — FastAPI 实现

提供 REST API 接口，支持：
- 自然语言查询（Agent 模式）
- 系统状态查询
- 巡检历史查询
- Runbook 执行
- 健康检查

启动方式：
    python -m keeper.api.server
    或
    uvicorn keeper.api.server:app --host 0.0.0.0 --port 8900

认证：Bearer Token（通过 KEEPER_API_TOKEN 环境变量配置）
"""
import os
import time
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

try:
    from fastapi import FastAPI, HTTPException, Depends, Header
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

from ..config import AppConfig


# ─── Pydantic 请求/响应模型 ───────────────────────────────────

if FASTAPI_AVAILABLE:

    class QueryRequest(BaseModel):
        """自然语言查询请求"""
        query: str
        mode: str = "agent"  # agent / classic
        context: Optional[Dict[str, Any]] = None

    class QueryResponse(BaseModel):
        """查询响应"""
        success: bool
        response: str
        mode: str
        tools_used: List[str] = []
        duration_ms: int = 0

    class StatusResponse(BaseModel):
        """系统状态响应"""
        version: str
        llm_configured: bool
        mode: str
        uptime_seconds: int

    class HealthResponse(BaseModel):
        """健康检查响应"""
        status: str
        version: str

    class RunbookRequest(BaseModel):
        """Runbook 执行请求"""
        name: str
        variables: Optional[Dict[str, str]] = None
        auto_confirm: bool = False

    class RunbookResponse(BaseModel):
        """Runbook 执行响应"""
        success: bool
        summary: str
        steps_completed: int
        steps_total: int


# ─── 应用创建 ────────────────────────────────────────────────

def create_app() -> "FastAPI":
    """创建 FastAPI 应用"""
    if not FASTAPI_AVAILABLE:
        raise ImportError(
            "FastAPI 未安装，请运行: pip install fastapi uvicorn"
        )

    app = FastAPI(
        title="Keeper API",
        description="智能运维 Agent HTTP API",
        version="1.0.0",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 全局状态
    app.state.config = AppConfig.from_env()
    app.state.start_time = time.time()
    app.state.agent = None

    # ─── 认证 ─────────────────────────────────────────────

    API_TOKEN = os.getenv("KEEPER_API_TOKEN", "")

    async def verify_token(authorization: Optional[str] = Header(None)):
        """Bearer Token 认证"""
        if not API_TOKEN:
            return  # 未配置 token 则跳过认证
        if not authorization:
            raise HTTPException(status_code=401, detail="Missing Authorization header")
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid token format")
        token = authorization[7:]
        if token != API_TOKEN:
            raise HTTPException(status_code=403, detail="Invalid token")

    # ─── 路由 ─────────────────────────────────────────────

    @app.get("/health", response_model=HealthResponse)
    async def health():
        """健康检查（无需认证）"""
        return HealthResponse(status="ok", version="1.0.0")

    @app.get("/api/v1/status", response_model=StatusResponse, dependencies=[Depends(verify_token)])
    async def get_status():
        """系统状态"""
        config = app.state.config
        uptime = int(time.time() - app.state.start_time)
        return StatusResponse(
            version="1.0.0",
            llm_configured=config.is_llm_configured(),
            mode="agent",
            uptime_seconds=uptime,
        )

    @app.post("/api/v1/query", response_model=QueryResponse, dependencies=[Depends(verify_token)])
    async def query(req: QueryRequest):
        """自然语言查询（核心接口）"""
        config = app.state.config
        start = time.time()

        if req.mode == "agent":
            # Agent 模式
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
            # 经典模式
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

    @app.get("/api/v1/history", dependencies=[Depends(verify_token)])
    async def get_history(host: Optional[str] = None, hours: int = 24, limit: int = 50):
        """巡检历史查询"""
        try:
            from ..storage.history import InspectionHistory
            history = InspectionHistory()
            if host:
                records = history.get_by_time_range(host, hours=hours)
            else:
                # 获取所有主机的最新记录
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

    @app.post("/api/v1/runbook/run", response_model=RunbookResponse, dependencies=[Depends(verify_token)])
    async def run_runbook(req: RunbookRequest):
        """执行 Runbook"""
        try:
            from ..runbook.executor import RunbookExecutor, list_builtin_runbooks
            from pathlib import Path

            executor = RunbookExecutor(
                confirm_callback=lambda _: req.auto_confirm,
                output_callback=lambda _: None,
            )

            # 查找 runbook
            template_dir = Path(__file__).parent.parent / "runbook" / "templates"
            yaml_path = template_dir / f"{req.name}.yaml"

            if not yaml_path.exists():
                raise HTTPException(status_code=404, detail=f"Runbook '{req.name}' not found. Available: {list_builtin_runbooks()}")

            runbook = executor.load_from_yaml(str(yaml_path))
            success, summary = executor.execute(runbook, variables=req.variables)

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

    @app.get("/api/v1/runbooks", dependencies=[Depends(verify_token)])
    async def list_runbooks():
        """列出可用 Runbook"""
        from ..runbook.executor import list_builtin_runbooks
        return {"runbooks": list_builtin_runbooks()}

    @app.get("/api/v1/tools", dependencies=[Depends(verify_token)])
    async def list_tools():
        """列出 Agent 可用工具"""
        from ..agent.tools_registry import ALL_TOOLS
        tools = []
        for t in ALL_TOOLS:
            name = t.name if hasattr(t, "name") else t.__name__
            doc = (t.description if hasattr(t, "description") else t.__doc__) or ""
            tools.append({"name": name, "description": doc.split("\n")[0]})
        return {"tools": tools, "count": len(tools)}

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

    uvicorn.run(
        "keeper.api.server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
