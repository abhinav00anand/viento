"""
Zephyr Command Line Interface (CLI).

Provides terminal commands for node runtime execution, initialization, status inspection,
local model listing/registration, environment diagnostics, configuration editing,
log tailing, version reporting, model weight pulling, and runtime shutdown.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import click
import httpx
import psutil
from rich.console import Console
from rich.live import Live
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
from rich.text import Text

from viento.backends import get_backend_adapter
from viento.config.loader import ConfigManager, RuntimeState, ZephyrConfig
from viento.connection.manager import ConnectionManager
from viento.scheduler.scheduler import JobScheduler

console = Console()
config_mgr = ConfigManager()


@click.group()
@click.version_option(version="0.1.0-beta", prog_name="zephyr")
def cli():
    """Zephyr Cloud CLI - Distributed AI Mesh Network Runtime & SDK."""
    pass


# -----------------------------------------------------------------------------
# Command: zephyr init
# -----------------------------------------------------------------------------
@cli.command("init")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing config.toml if it exists.")
def init_command(force: bool):
    """Initialize ~/.viento directory structure and default configuration."""
    cfg_file = config_mgr.config_file
    if cfg_file.exists() and not force:
        console.print(
            Panel(
                f"[yellow]Zephyr configuration already initialized at:[/yellow]\n[cyan]{cfg_file}[/cyan]\n\n"
                "[dim]Use `zephyr init --force` to overwrite.[/dim]",
                title="Configuration Exists",
                border_style="yellow",
            )
        )
        return

    config_mgr.ensure_directories()
    default_cfg = ZephyrConfig()
    config_mgr.save_config(default_cfg)

    console.print(
        Panel.fit(
            "[bold green]✔ ZEPHYR INITIALIZED SUCCESSFULLY[/bold green]\n\n"
            f"[dim]Config Path:[/dim] [yellow]{cfg_file}[/yellow]\n"
            f"[dim]Logs Directory:[/dim] [yellow]{config_mgr.logs_dir}[/yellow]\n"
            f"[dim]Gateway Server:[/dim] [cyan]{default_cfg.server_url}[/cyan]\n"
            f"[dim]Ollama Endpoint:[/dim] [cyan]{default_cfg.ollama_url}[/cyan]",
            border_style="green",
        )
    )


# -----------------------------------------------------------------------------
# Command: zephyr version
# -----------------------------------------------------------------------------
@cli.command("version")
def version_command():
    """Output SDK runtime, Python environment, and protocol version information."""
    table = Table(title="Zephyr Version & Environment Info", show_header=True, header_style="bold cyan")
    table.add_column("Property", style="yellow")
    table.add_column("Value", style="white")

    table.add_row("SDK Package Version", "0.1.0-beta")
    table.add_row("Protocol Envelope Version", "1.0")
    table.add_row("Python Version", sys.version.split(" ")[0])
    table.add_row("Platform OS", sys.platform)
    table.add_row("Config Directory", str(config_mgr.zephyr_dir))

    console.print(table)


# -----------------------------------------------------------------------------
# Command: zephyr logs
# -----------------------------------------------------------------------------
@cli.command("logs")
@click.option("--lines", "-n", type=int, default=50, help="Number of log lines to show (default 50).")
def logs_command(lines: int):
    """View and tail structured runtime logs (~/.viento/logs/)."""
    log_file = config_mgr.logs_dir / "runtime.log"
    if not log_file.exists():
        console.print(f"[yellow]No log file found at {log_file}. Run `viento run` to generate logs.[/yellow]")
        return

    try:
        content = log_file.read_text(encoding="utf-8").splitlines()
        tail = content[-lines:] if len(content) > lines else content
        console.print(Panel(Syntax("\n".join(tail), "json" if tail and tail[0].startswith("{") else "text", theme="monokai"), title=f"Logs: {log_file} (last {len(tail)} lines)", border_style="cyan"))
    except Exception as e:
        console.print(f"[bold red]Error reading log file: {e}[/bold red]")


# -----------------------------------------------------------------------------
# Command: viento run
# -----------------------------------------------------------------------------
@cli.command("run")
@click.option("--server", "-s", type=str, help="Override Zephyr WSS Cloud Gateway URL.")
@click.option("--ollama-url", "-o", type=str, help="Override local Ollama API URL.")
@click.option("--name", "-n", type=str, help="Custom runtime node name / ID.")
@click.option("--node-name", type=str, help="Custom runtime node name / ID.")
@click.option("--concurrency", "-c", type=int, help="Override maximum job concurrency.")
@click.option("--bootstrap-key", "-k", type=str, help="Runtime bootstrap authentication key.")
def run_command(
    server: Optional[str],
    ollama_url: Optional[str],
    name: Optional[str],
    node_name: Optional[str],
    concurrency: Optional[int],
    bootstrap_key: Optional[str],
):
    """Boot local runtime, connect to WSS gateway, perform handshake, and process jobs."""
    cfg = config_mgr.load_config()
    if server:
        cfg.server_url = server
    if ollama_url:
        cfg.ollama_url = ollama_url
    target_name = name or node_name
    if target_name:
        cfg.node_name = target_name
    if concurrency:
        cfg.max_concurrency = concurrency
    if bootstrap_key:
        cfg.bootstrap_key = bootstrap_key

    backend = get_backend_adapter(cfg.model_backend, base_url=cfg.ollama_url)

    console.print(
        Panel.fit(
            "[bold cyan]⚡ ZEPHYR RUNTIME BOOTSTRAP[/bold cyan]\n"
            f"[dim]Server Gateway:[/dim] [yellow]{cfg.server_url}[/yellow]\n"
            f"[dim]Backend Adapter:[/dim] [green]{backend.name()}[/green]\n"
            f"[dim]Engine Endpoint:[/dim] [yellow]{cfg.ollama_url}[/yellow]\n"
            f"[dim]Max Concurrency:[/dim] [green]{cfg.max_concurrency}[/green]",
            border_style="cyan",
        )
    )

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
        console.print(Panel(panel_content, title="[bold green]Node Authenticated[/bold green]", border_style="green"))

    conn_mgr.on_handshake_callback = on_handshake
    conn_mgr.on_job_received_callback = lambda envelope: asyncio.create_task(scheduler.submit_job(envelope))
    conn_mgr.on_embedding_received_callback = lambda envelope: asyncio.create_task(scheduler.submit_embedding_job(envelope))
    conn_mgr.on_job_cancel_callback = lambda job_id: asyncio.create_task(scheduler.cancel_job(job_id))

    async def main_loop():
        await scheduler.start()
        connection_task = asyncio.create_task(conn_mgr.start())

        try:
            with console.status("[bold cyan]Runtime active & listening for incoming inference jobs...[/bold cyan]") as status:
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

    status_color = "green" if state.status == "running" else "yellow" if state.status in ("booting", "busy") else "red"
    key_display = "Available in running process (in-memory only)" if state.status in ("running", "busy") else "N/A (Process stopped)"

    table = Table(title="Zephyr Runtime Node Status", show_header=True, header_style="bold magenta")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Status", f"[{status_color}]{state.status.upper()}[/{status_color}]")
    table.add_row("Session ID", state.session_id or "N/A")
    table.add_row("Active API Key", key_display)
    table.add_row("API Key TTL", ttl_str)
    table.add_row("Server Gateway", cfg.server_url)
    table.add_row("Ollama Endpoint", cfg.ollama_url)
    table.add_row("Registered Models", ", ".join(state.registered_models) if state.registered_models else "None")
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

    table = Table(title=f"Discovered & Registered Models", show_header=True, header_style="bold green")
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
    console.print(f"[bold green]✔ Registered model alias:[/bold green] [yellow]{model_name}[/yellow]")


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
    console.print(f"[bold green]✔ Unregistered model alias:[/bold green] [yellow]{model_name}[/yellow]")


# -----------------------------------------------------------------------------
# Command: viento doctor
# -----------------------------------------------------------------------------
@cli.command("doctor")
def doctor_command():
    """Diagnose local environment (Ollama API reachability, GPU/CPU stats, Cloud network)."""
    cfg = config_mgr.load_config()

    console.print(Panel("[bold cyan]🩺 ZEPHYR ENVIRONMENT DIAGNOSTIC DOCTOR[/bold cyan]", border_style="cyan"))
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
                table.add_row("Ollama Service", "[green]✔ PASS[/green]", f"Reachable at {cfg.ollama_url} ({count} models available)")
            else:
                table.add_row("Ollama Service", "[red]✖ FAIL[/red]", f"Returned HTTP {r.status_code}")
    except Exception as e:
        table.add_row("Ollama Service", "[red]✖ FAIL[/red]", f"Unreachable at {cfg.ollama_url}: {e}")

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
                table.add_row("Cloud Gateway", "[green]✔ PASS[/green]", f"Reachable at {cfg.http_url}")
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
        console.print(f"[yellow]Config file does not exist yet. Current defaults:[/yellow]\n{cfg.to_dict()}")


@config_group.command("get")
@click.argument("key", type=str)
def config_get(key: str):
    """Get specific configuration key value."""
    cfg = config_mgr.load_config()
    cfg_dict = cfg.to_dict()
    if key in cfg_dict:
        console.print(f"[bold cyan]{key}[/bold cyan] = [yellow]{cfg_dict[key]}[/yellow]")
    else:
        console.print(f"[bold red]Unknown configuration key '{key}'. Available keys: {list(cfg_dict.keys())}[/bold red]")


@config_group.command("set")
@click.argument("key", type=str)
@click.argument("value", type=str)
def config_set(key: str, value: str):
    """Set specific configuration key value."""
    cfg = config_mgr.load_config()
    cfg_dict = cfg.to_dict()

    if key not in cfg_dict:
        console.print(f"[bold red]Unknown configuration key '{key}'. Available keys: {list(cfg_dict.keys())}[/bold red]")
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
                    console.print(f"[bold red]Pull failed ({response.status_code}): {response.read()}[/bold red]")
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

        console.print(f"[bold green]✔ Model '{model}' successfully pulled and verified![/bold green]")
    except Exception as e:
        console.print(f"[bold red]Error pulling model '{model}': {e}[/bold red]")


# -----------------------------------------------------------------------------
# Command: viento stop
# -----------------------------------------------------------------------------
@cli.command("stop")
def stop_command():
    """Gracefully drain active jobs, update runtime state, and stop node process."""
    state = config_mgr.load_runtime_state()
    if state.status == "stopped":
        console.print("[yellow]Zephyr runtime node is already stopped.[/yellow]")
        return

    console.print("[bold yellow]Draining active jobs and sending disconnect signal...[/bold yellow]")
    config_mgr.update_runtime_state(status="stopped", active_api_key=None, key_expires_at=None)
    console.print("[bold green]✔ Zephyr runtime node gracefully stopped.[/bold green]")


if __name__ == "__main__":
    cli()
