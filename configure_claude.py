import os
import sys
import json
from pathlib import Path

def setup_claude_config():
    # 1. Resolve OS-specific Claude Desktop config path
    if sys.platform.startswith("win"):
        config_dir = Path(os.environ["APPDATA"]) / "Claude"
    elif sys.platform == "darwin":
        config_dir = Path.home() / "Library" / "Application Support" / "Claude"
    else:
        config_dir = Path.home() / ".config" / "Claude"

    config_file = config_dir / "claude_desktop_config.json"
    repo_root = Path(__file__).resolve().parent

    # 2. Resolve virtual environment Python executable
    if sys.platform.startswith("win"):
        venv_python = repo_root / ".venv" / "Scripts" / "python.exe"
    else:
        venv_python = repo_root / ".venv" / "bin" / "python"

    python_executable = str(venv_python if venv_python.exists() else sys.executable)
    gateway_script = str(repo_root / "Host_Gateway" / "mcp_gateway.py")

    # 3. Read existing configuration if present
    data = {}
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

    if "mcpServers" not in data:
        data["mcpServers"] = {}

    data["mcpServers"]["hardware_security_gateway"] = {
        "command": python_executable,
        "args": ["-u", gateway_script]
    }

    # 4. Write back
    config_dir.mkdir(parents=True, exist_ok=True)
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print("=====================================================")
    print("[SUCCESS] Claude Desktop configured successfully!")
    print(f"Config File : {config_file}")
    print(f"Python Exec : {python_executable}")
    print(f"Target MCP  : {gateway_script}")
    print("=====================================================")

if __name__ == "__main__":
    setup_claude_config()