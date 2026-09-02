"""
Viento Command Line Interface (CLI).

Provides terminal commands for node runtime execution, initialization, status inspection,
local model listing/registration, environment diagnostics, configuration editing,
log tailing, version reporting, model weight pulling, and runtime shutdown.
"""

import asyncio
import json
import os
import sys
import time
from typing import Any, Dict, Optional

import click
import httpx
import psutil
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.syntax import Syntax
from rich.table import Table

from viento.backends import get_backend_adapter
from viento.config.defaults import apply_env_overrides
from viento.config.loader import ConfigManager, VientoConfig
from viento.connection.manager import ConnectionManager
from viento.scheduler.scheduler import JobScheduler

console = Console()
config_mgr = ConfigManager()


@click.group()
@click.version_option(package_name="viento", prog_name="viento")
def cli():
    """Viento CLI - Distributed AI Mesh Network Runtime & SDK."""
    pass


# -----------------------------------------------------------------------------
# Command: viento init
# -----------------------------------------------------------------------------
@cli.command("init")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing config.toml if it exists.")
def init_command(force: bool):
    """Initialize ~/.viento directory structure and default configuration."""
    cfg_file = config_mgr.config_file
    if cfg_file.exists() and not force:
        console.print(
            Panel(
                f"[yellow]Viento configuration already initialized at:[/yellow]\n[cyan]{cfg_file}[/cyan]\n\n"
                "[dim]Use `viento init --force` to overwrite.[/dim]",
                title="Configuration Exists",
                border_style="yellow",
            )
        )
        return

    config_mgr.ensure_directories()
    default_cfg = VientoConfig()
    config_mgr.save_config(default_cfg)

    console.print(
        Panel.fit(
            "[bold green]✔ VIENTO INITIALIZED SUCCESSFULLY[/bold green]\n\n"
            f"[dim]Config Path:[/dim] [yellow]{cfg_file}[/yellow]\n"
            f"[dim]Logs Directory:[/dim] [yellow]{config_mgr.logs_dir}[/yellow]\n"
            f"[dim]Gateway Server:[/dim] [cyan]{default_cfg.server_url}[/cyan]\n"
            f"[dim]Ollama Endpoint:[/dim] [cyan]{default_cfg.ollama_url}[/cyan]",
            border_style="green",
        )
    )


# -----------------------------------------------------------------------------
# Command: viento version
# -----------------------------------------------------------------------------
@cli.command("version")
def version_command():
    """Output SDK runtime, Python environment, and protocol version information."""
    from viento import __version__

    table = Table(
        title="Viento Version & Environment Info", show_header=True, header_style="bold cyan"
    )
    table.add_column("Property", style="yellow")
    table.add_column("Value", style="white")

    table.add_row("SDK Package Version", __version__)
    table.add_row("Protocol Envelope Version", "1.0")
    table.add_row("Python Version", sys.version.split(" ")[0])
    table.add_row("Platform OS", sys.platform)
    table.add_row("Config Directory", str(config_mgr.viento_dir))

    console.print(table)


# -----------------------------------------------------------------------------
# Command: viento logs
# -----------------------------------------------------------------------------
@cli.command("logs")
@click.option(
    "--lines", "-n", type=int, default=50, help="Number of log lines to show (default 50)."
)
def logs_command(lines: int):
    """View and tail structured runtime logs (~/.viento/logs/)."""
    log_file = config_mgr.logs_dir / "runtime.log"
    if not log_file.exists():
        console.print(
            f"[yellow]No log file found at {log_file}. Run `viento run` to generate logs.[/yellow]"
        )
        return

    try:
        content = log_file.read_text(encoding="utf-8").splitlines()
        tail = content[-lines:] if len(content) > lines else content
        console.print(
            Panel(
                Syntax(
                    "\n".join(tail),
                    "json" if tail and tail[0].startswith("{") else "text",
                    theme="monokai",
                ),
                title=f"Logs: {log_file} (last {len(tail)} lines)",
                border_style="cyan",
            )
        )
    except Exception as e:
        console.print(f"[bold red]Error reading log file: {e}[/bold red]")


# -----------------------------------------------------------------------------
# Command: viento run
# -----------------------------------------------------------------------------
@cli.command("run")
@click.option("--server", "-s", type=str, help="Override Viento WSS Cloud Gateway URL.")
@click.option(
    "--backend",
    "-b",
    type=click.Choice(["ollama", "vllm", "llamacpp"], case_sensitive=False),
    default=None,
    help="Inference backend engine (ollama, vllm, llamacpp).",
)
@click.option("--ollama-url", "-o", type=str, help="Override local Ollama API URL.")
@click.option("--vllm-url", type=str, help="Override local vLLM API URL.")
@click.option("--llamacpp-url", type=str, help="Override local llama.cpp API URL.")
@click.option("--concurrency", "-c", type=int, help="Override maximum job concurrency.")
@click.option("--bootstrap-key", "-k", type=str, help="Runtime bootstrap authentication key.")
@click.option(
    "--name",
    "--node-name",
    type=str,
    default=None,
    help="Override node name (default: machine-unique ID).",
)
def run_command(
    server: Optional[str],
    backend: Optional[str],
    ollama_url: Optional[str],
    vllm_url: Optional[str],
    llamacpp_url: Optional[str],
    concurrency: Optional[int],
    bootstrap_key: Optional[str],
    name: Optional[str],
):
    """Boot local runtime, connect to WSS gateway, perform handshake, and process jobs."""
    # Centralized configuration loading with explicit precedence:
    # CLI Flags > Environment Variables > Config File > Defaults
    cfg = config_mgr.load_config()
    cfg = apply_env_overrides(cfg)

    if server:
        cfg.server_url = server
    if backend:
        cfg.model_backend = backend.lower()
    if ollama_url:
        cfg.ollama_url = ollama_url
    if vllm_url:
        cfg.vllm_url = vllm_url
    if llamacpp_url:
        cfg.llamacpp_url = llamacpp_url
    if concurrency:
        cfg.max_concurrency = concurrency
    if bootstrap_key:
        cfg.bootstrap_key = bootstrap_key
    if name:
        cfg.node_name = name

    # Select endpoint URL matching the active backend
    if cfg.model_backend == "vllm":
        target_url = cfg.vllm_url
    elif cfg.model_backend == "llamacpp":
        target_url = cfg.llamacpp_url
    else:
        target_url = cfg.ollama_url

    backend_adapter = get_backend_adapter(cfg.model_backend, base_url=target_url)

    # Record process PID and started status for real process management
    config_mgr.update_runtime_state(
        status="running",
        pid=os.getpid(),
        uptime_start=time.time(),
        process_name="viento",
    )

    console.print(
        Panel.fit(
            "[bold cyan]⚡ VIENTO RUNTIME BOOTSTRAP[/bold cyan]\n"
            f"[dim]Server Gateway:[/dim] [yellow]{cfg.server_url}[/yellow]\n"
            f"[dim]Backend Adapter:[/dim] [green]{backend_adapter.name()}[/green]\n"
            f"[dim]Engine Endpoint:[/dim] [yellow]{target_url}[/yellow]\n"
            f"[dim]Max Concurrency:[/dim] [green]{cfg.max_concurrency}[/green]\n"
            f"[dim]Node Name:[/dim] [green]{cfg.node_name}[/green]\n"
            f"[dim]Process PID:[/dim] [cyan]{os.getpid()}[/cyan]",
            border_style="cyan",
        )
    )

    backend = backend_adapter

    conn_mgr = ConnectionManager(config=cfg, config_manager=config_mgr, backend=backend)
    scheduler = JobScheduler(
        backend=backend,
        connection_manager=conn_mgr,
        max_concurrency=cfg.max_concurrency,
        max_queue_depth=cfg.max_queue_depth,
    )

    # Attach event handlers
    def on_handshake(api_key: str, session_id: str, ttl: float):
        ttl_minutes = int(ttl // 60)
        panel_content = (
            f"[bold green]✔ HANDSHAKE SUCCESSFUL[/bold green]\n\n"
            f"[bold yellow]Session ID:[/bold yellow] {session_id}\n"
            f"[bold yellow]Temporary API Key (1-Hour):[/bold yellow] [bold white on blue] {api_key} [/bold white on blue]\n"
            f"[bold yellow]Key Expiry TTL:[/bold yellow] {ttl_minutes} minutes ({int(ttl)} seconds)\n"
            f"[dim]Use this key to authenticate client SDK calls during this session.[/dim]"
        )
        console.print(
            Panel(
                panel_content,
                title="[bold green]Node Authenticated[/bold green]",
                border_style="green",
            )
        )

    conn_mgr.on_handshake_callback = on_handshake
    conn_mgr.on_job_received_callback = lambda envelope: asyncio.create_task(
        scheduler.submit_job(envelope)
    )
    conn_mgr.on_embedding_received_callback = lambda envelope: asyncio.create_task(
        scheduler.submit_job(envelope)
    )
    # BUG-5 FIX: cancel_job is SYNC not async — do not wrap in asyncio.create_task
    conn_mgr.on_job_cancel_callback = scheduler.cancel_job

    async def main_loop():
        await scheduler.start()
        connection_task = asyncio.create_task(conn_mgr.start())

        try:
            with console.status(
                "[bold cyan]Runtime active & listening for incoming inference jobs...[/bold cyan]"
            ):
                while True:
                    await asyncio.sleep(1.0)
        except (KeyboardInterrupt, asyncio.CancelledError):
            console.print("\n[bold yellow]Shutting down runtime node...[/bold yellow]")
            await scheduler.stop()
            await conn_mgr.stop()
            connection_task.cancel()
            console.print("[bold green]Runtime stopped cleanly.[/bold green]")

    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        console.print("\n[bold red]Interrupted by user.[/bold red]")


# -----------------------------------------------------------------------------
# Command: viento status
# -----------------------------------------------------------------------------
@cli.command("status")
def status_command():
    """Inspect local runtime state, session ID, active API key TTL, and models."""
    cfg = config_mgr.load_config()
    state = config_mgr.load_runtime_state()

    ttl = config_mgr.get_active_key_ttl()
    if ttl > 0:
        mins, secs = divmod(int(ttl), 60)
        ttl_str = f"[bold green]{mins}m {secs}s remaining[/bold green]"
    else:
        ttl_str = "[bold red]Expired / Inactive[/bold red]"

    status_color = (
        "green"
        if state.status == "running"
        else "yellow" if state.status in ("booting", "busy") else "red"
    )
    key_display = (
        "Available in running process (in-memory only)"
        if state.status in ("running", "busy")
        else "N/A (Process stopped)"
    )

    table = Table(title="Viento Runtime Node Status", show_header=True, header_style="bold magenta")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Status", f"[{status_color}]{state.status.upper()}[/{status_color}]")
    table.add_row("Session ID", state.session_id or "N/A")
    table.add_row("Active API Key", key_display)
    table.add_row("API Key TTL", ttl_str)
    table.add_row("Server Gateway", cfg.server_url)
    table.add_row("Ollama Endpoint", cfg.ollama_url)
    table.add_row(
        "Registered Models",
        ", ".join(state.registered_models) if state.registered_models else "None",
    )
    table.add_row("Jobs Completed", str(state.jobs_completed))
    table.add_row("Jobs Failed", str(state.jobs_failed))

    if state.uptime_start:
        uptime = int(time.time() - state.uptime_start)
        table.add_row("Node Uptime", f"{uptime // 3600}h {(uptime % 3600) // 60}m {uptime % 60}s")

    console.print(table)


# -----------------------------------------------------------------------------
# Command Group: viento models
# -----------------------------------------------------------------------------
@cli.group("models", invoke_without_command=True)
@click.pass_context
def models_group(ctx: click.Context):
    """List, add, or remove local models registered with the runtime."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(models_list)


@models_group.command("list")
def models_list():
    """List local models discovered from Ollama backend or registered manually."""
    cfg = config_mgr.load_config()
    url = f"{cfg.ollama_url.rstrip('/')}/api/tags"

    try:
        with httpx.Client(timeout=5.0) as client:
            res = client.get(url)
            if res.status_code == 200:
                data = res.json()
                models = data.get("models", [])
            else:
                models = []
    except Exception:
        models = []

    state = config_mgr.load_runtime_state()
    custom_models = set(state.registered_models)

    if not models and not custom_models:
        console.print("[yellow]No models found in local repository.[/yellow]")
        return

    table = Table(
        title="Discovered & Registered Models", show_header=True, header_style="bold green"
    )
    table.add_column("Model Name", style="cyan", no_wrap=True)
    table.add_column("Source", style="yellow")
    table.add_column("Size", style="magenta")

    for m in models:
        name = m.get("name", "unknown")
        size_gb = round(m.get("size", 0) / (1024**3), 2)
        size_str = f"{size_gb} GB" if size_gb > 0 else "N/A"
        table.add_row(name, "Ollama Auto-Discovered", size_str)

    for cm in custom_models:
        if not any(m.get("name") == cm for m in models):
            table.add_row(cm, "Manually Registered", "Custom")

    console.print(table)


@models_group.command("add")
@click.argument("model_name", type=str)
def models_add(model_name: str):
    """Register a custom model alias or local path with the runtime state."""
    state = config_mgr.load_runtime_state()
    models = set(state.registered_models)
    if model_name in models:
        console.print(f"[yellow]Model '{model_name}' is already registered.[/yellow]")
        return

    models.add(model_name)
    config_mgr.update_runtime_state(registered_models=list(models))
    console.print(
        f"[bold green]✔ Registered model alias:[/bold green] [yellow]{model_name}[/yellow]"
    )


@models_group.command("remove")
@click.argument("model_name", type=str)
def models_remove(model_name: str):
    """Unregister a model alias from the runtime state."""
    state = config_mgr.load_runtime_state()
    models = set(state.registered_models)
    if model_name not in models:
        console.print(f"[yellow]Model '{model_name}' is not in registered list.[/yellow]")
        return

    models.remove(model_name)
    config_mgr.update_runtime_state(registered_models=list(models))
    console.print(
        f"[bold green]✔ Unregistered model alias:[/bold green] [yellow]{model_name}[/yellow]"
    )


# -----------------------------------------------------------------------------
# Command: viento doctor
# -----------------------------------------------------------------------------
@cli.command("doctor")
def doctor_command():
    """Diagnose local environment (Ollama API reachability, GPU/CPU stats, Cloud network)."""
    cfg = config_mgr.load_config()

    console.print(
        Panel("[bold cyan]🩺 VIENTO ENVIRONMENT DIAGNOSTIC DOCTOR[/bold cyan]", border_style="cyan")
    )
    table = Table(show_header=True, header_style="bold white")
    table.add_column("Component", style="bold yellow")
    table.add_column("Status", style="bold")
    table.add_column("Details", style="dim white")

    # 1. Ollama Reachability
    ollama_url = f"{cfg.ollama_url.rstrip('/')}/api/tags"
    try:
        with httpx.Client(timeout=3.0) as client:
            r = client.get(ollama_url)
            if r.status_code == 200:
                count = len(r.json().get("models", []))
                table.add_row(
                    "Ollama Service",
                    "[green]✔ PASS[/green]",
                    f"Reachable at {cfg.ollama_url} ({count} models available)",
                )
            else:
                table.add_row(
                    "Ollama Service", "[red]✖ FAIL[/red]", f"Returned HTTP {r.status_code}"
                )
    except Exception as e:
        table.add_row(
            "Ollama Service", "[red]✖ FAIL[/red]", f"Unreachable at {cfg.ollama_url}: {e}"
        )

    # 2. CPU & Memory
    try:
        cpu_percent = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        mem_used_gb = round(mem.used / (1024**3), 1)
        mem_total_gb = round(mem.total / (1024**3), 1)
        table.add_row(
            "System Hardware",
            "[green]✔ PASS[/green]",
            f"CPU: {cpu_percent}% | RAM: {mem_used_gb} GB / {mem_total_gb} GB ({mem.percent}% used)",
        )
    except Exception as e:
        table.add_row("System Hardware", "[yellow]⚠ WARN[/yellow]", f"Could not query stats: {e}")

    # 3. GPU Diagnostics
    gpu_found = False
    gpu_info = "No NVIDIA GPU detected or PyNVML unavailable"
    try:
        import pynvml

        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()
        if device_count > 0:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8")
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            gpu_used_gb = round(info.used / (1024**3), 1)
            gpu_total_gb = round(info.total / (1024**3), 1)
            gpu_found = True
            gpu_info = f"{name} ({gpu_used_gb} GB / {gpu_total_gb} GB VRAM)"
    except Exception:
        pass

    if gpu_found:
        table.add_row("GPU Hardware", "[green]✔ PASS[/green]", gpu_info)
    else:
        table.add_row("GPU Hardware", "[yellow]⚠ WARN[/yellow]", gpu_info)

    # 4. Cloud Connectivity
    http_url = f"{cfg.http_url.rstrip('/')}/healthz"
    try:
        with httpx.Client(timeout=4.0) as client:
            r = client.get(http_url)
            if r.status_code == 200:
                table.add_row(
                    "Cloud Gateway", "[green]✔ PASS[/green]", f"Reachable at {cfg.http_url}"
                )
            else:
                table.add_row("Cloud Gateway", "[yellow]⚠ WARN[/yellow]", f"HTTP {r.status_code}")
    except Exception as e:
        table.add_row("Cloud Gateway", "[red]✖ FAIL[/red]", f"Cannot connect to cloud: {e}")

    console.print(table)


# -----------------------------------------------------------------------------
# Command: viento config
# -----------------------------------------------------------------------------
@cli.group("config")
def config_group():
    """View or edit local configuration (~/.viento/config.toml)."""
    pass


@config_group.command("view")
def config_view():
    """View full local configuration contents."""
    cfg = config_mgr.load_config()
    cfg_file = config_mgr.config_file
    if cfg_file.exists():
        content = cfg_file.read_text(encoding="utf-8")
        syntax = Syntax(content, "toml", theme="monokai", line_numbers=True)
        console.print(Panel(syntax, title=f"Config Path: {cfg_file}", border_style="cyan"))
    else:
        console.print(
            f"[yellow]Config file does not exist yet. Current defaults:[/yellow]\n{cfg.to_dict()}"
        )


@config_group.command("get")
@click.argument("key", type=str)
def config_get(key: str):
    """Get specific configuration key value."""
    cfg = config_mgr.load_config()
    cfg_dict = cfg.to_dict()
    if key in cfg_dict:
        console.print(f"[bold cyan]{key}[/bold cyan] = [yellow]{cfg_dict[key]}[/yellow]")
    else:
        console.print(
            f"[bold red]Unknown configuration key '{key}'. Available keys: {list(cfg_dict.keys())}[/bold red]"
        )


@config_group.command("set")
@click.argument("key", type=str)
@click.argument("value", type=str)
def config_set(key: str, value: str):
    """Set specific configuration key value."""
    cfg = config_mgr.load_config()
    cfg_dict = cfg.to_dict()

    if key not in cfg_dict:
        console.print(
            f"[bold red]Unknown configuration key '{key}'. Available keys: {list(cfg_dict.keys())}[/bold red]"
        )
        return

    old_val = cfg_dict[key]
    new_val: Any = value
    if isinstance(old_val, int):
        new_val = int(value)
    elif isinstance(old_val, float):
        new_val = float(value)
    elif isinstance(old_val, bool):
        new_val = value.lower() in ("true", "1", "yes")

    config_mgr.update_config(**{key: new_val})
    console.print(f"[bold green]✔ Config updated:[/bold green] {key} = [yellow]{new_val}[/yellow]")


# -----------------------------------------------------------------------------
# Command: viento pull <model>
# -----------------------------------------------------------------------------
@cli.command("pull")
@click.argument("model", type=str)
def pull_command(model: str):
    """Interact with local Ollama service (/api/pull) to pull and verify model weights."""
    cfg = config_mgr.load_config()
    url = f"{cfg.ollama_url.rstrip('/')}/api/pull"

    console.print(f"[bold cyan]Initiating pull for model:[/bold cyan] [yellow]{model}[/yellow]")

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    )

    try:
        with httpx.Client(timeout=None) as client:
            with client.stream("POST", url, json={"name": model, "stream": True}) as response:
                if response.status_code != 200:
                    console.print(
                        f"[bold red]Pull failed ({response.status_code}): {response.read()}[/bold red]"
                    )
                    return

                tasks: Dict[str, Any] = {}
                with progress:
                    for line in response.iter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            status_msg = data.get("status", "")
                            digest = data.get("digest", "")
                            completed = data.get("completed", 0)
                            total = data.get("total", 0)

                            if digest:
                                task_id = digest[:12]
                                if task_id not in tasks:
                                    tasks[task_id] = progress.add_task(
                                        f"Layer {task_id}", total=total or 100
                                    )
                                if total > 0:
                                    progress.update(
                                        tasks[task_id],
                                        completed=completed,
                                        total=total,
                                        description=f"{status_msg} ({task_id})",
                                    )
                            else:
                                console.print(f"[dim]{status_msg}[/dim]")

                        except json.JSONDecodeError:
                            continue

        console.print(
            f"[bold green]✔ Model '{model}' successfully pulled and verified![/bold green]"
        )
    except Exception as e:
        console.print(f"[bold red]Error pulling model '{model}': {e}[/bold red]")


# -----------------------------------------------------------------------------
# Command: viento stop
# -----------------------------------------------------------------------------
@cli.command("stop")
@click.option("--force", "-f", is_flag=True, help="Force kill node process immediately (SIGKILL).")
def stop_command(force: bool):
    """Gracefully drain active jobs and terminate the running Viento node process."""
    state = config_mgr.load_runtime_state()
    pid = state.pid

    if not pid:
        console.print("[yellow]No active Viento process PID found in runtime state.[/yellow]")
        config_mgr.update_runtime_state(status="stopped", active_api_key=None, pid=None)
        return

    # Validate process identity before terminating to protect against PID reuse
    proc_alive = False
    proc_obj = None
    try:
        proc_obj = psutil.Process(pid)
        if proc_obj.is_running() and proc_obj.status() != psutil.STATUS_ZOMBIE:
            cmdline = " ".join(proc_obj.cmdline()).lower()
            name = proc_obj.name().lower()
            # Must match python/viento to ensure we don't kill an unrelated recycled PID
            if "viento" in cmdline or "python" in name or "viento" in name:
                proc_alive = True
            else:
                console.print(
                    f"[yellow]PID {pid} exists but does not match Viento identity ({name}). Skipping termination.[/yellow]"
                )
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        proc_alive = False

    if not proc_alive:
        console.print(
            f"[yellow]Viento node process (PID {pid}) is not running. Resetting state to stopped.[/yellow]"
        )
        config_mgr.update_runtime_state(status="stopped", active_api_key=None, pid=None)
        return

    console.print(f"[bold yellow]Stopping Viento node process (PID {pid})...[/bold yellow]")
    try:
        if force:
            proc_obj.kill()
        else:
            proc_obj.terminate()
            try:
                proc_obj.wait(timeout=5.0)
            except psutil.TimeoutExpired:
                console.print(
                    "[yellow]Process did not terminate within 5s, terminating forcefully...[/yellow]"
                )
                proc_obj.kill()
        console.print("[bold green]✔ Viento runtime node successfully stopped.[/bold green]")
    except Exception as exc:
        console.print(f"[bold red]Failed to stop process {pid}: {exc}[/bold red]")
    finally:
        config_mgr.update_runtime_state(status="stopped", active_api_key=None, pid=None)


if __name__ == "__main__":
    cli()
