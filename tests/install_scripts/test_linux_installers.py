import subprocess
import unittest
import os
from pathlib import Path

# Path to the install script to test
INSTALL_SH = Path(__file__).resolve().parents[2] / "plugin" / "install.sh"
REPO_ROOT = Path(__file__).resolve().parents[2]

class TestLinuxInstallers(unittest.TestCase):
    def run_in_docker(self, image, command, shell="bash", env=None):
        """Runs a command in a fresh docker container."""
        # We mount the entire repo so we can test the local version including sub-modules
        docker_cmd = [
            "docker", "run", "--rm",
            "-v", f"{REPO_ROOT}:/repo:ro",
            image,
            shell, "-c", command
        ]
        return subprocess.run(docker_cmd, capture_output=True, text=True, env=env)

    def test_ubuntu_install(self):
        print("Testing on Ubuntu (Minimal)...")
        # Ubuntu: only add curl (to start the script).
        res = self.run_in_docker("ubuntu:latest", "apt-get update && apt-get install -y curl && bash /repo/plugin/install.sh --dry-run --no-fail-on-empty")
        print(res.stdout)
        if res.returncode != 0:
            print(res.stderr)
        self.assertEqual(res.returncode, 0)

    def test_alpine_install(self):
        print("Testing on Alpine...")
        # Alpine: must use 'sh' as the entrypoint to install bash.
        res = self.run_in_docker("alpine:latest", "apk add --no-cache bash curl && bash /repo/plugin/install.sh --dry-run --no-fail-on-empty", shell="sh")
        print(res.stdout)
        if res.returncode != 0:
            print(res.stderr)
        self.assertEqual(res.returncode, 0)

    def test_fedora_install(self):
        print("Testing on Fedora...")
        res = self.run_in_docker("fedora:latest", "dnf install -y curl && bash /repo/plugin/install.sh --dry-run --no-fail-on-empty")
        print(res.stdout)
        if res.returncode != 0:
            print(res.stderr)
        self.assertEqual(res.returncode, 0)

    def test_opensuse_install(self):
        print("Testing on openSUSE (Dependency Test)...")
        # openSUSE: must install bash first.
        res = self.run_in_docker("opensuse/leap:latest", "zypper --non-interactive install curl bash && bash /repo/plugin/install.sh --dry-run --no-fail-on-empty")
        print(res.stdout)
        if res.returncode != 0:
            print(res.stderr)
        self.assertEqual(res.returncode, 0)

    def test_arch_install(self):
        print("Testing on Arch Linux...")
        res = self.run_in_docker("archlinux:latest", "pacman -Sy --noconfirm curl bash && bash /repo/plugin/install.sh --dry-run --no-fail-on-empty")
        print(res.stdout)
        if res.returncode != 0:
            print(res.stderr)
        self.assertEqual(res.returncode, 0)

    def test_dry_run_uninstall(self):
        print("Testing Dry-run Uninstall (Ubuntu)...")
        # Create a dummy symlink to ensure the uninstall script has something to "would remove"
        setup_cmd = "mkdir -p ~/.agents/skills && ln -s /tmp ~/.agents/skills/mcp-stata"
        res = self.run_in_docker("ubuntu:latest", f"apt-get update && apt-get install -y curl && {setup_cmd} && bash /repo/plugin/install.sh --uninstall --dry-run --no-fail-on-empty")
        print(res.stdout)
        if res.returncode != 0:
            print(res.stderr)
        self.assertEqual(res.returncode, 0)

    def test_agent_config_integrity(self):
        print("Testing agent config merging and preservation (Ubuntu)...")
        # This test creates a dummy Cursor config, runs the installer, 
        # verifies the merge, runs the uninstaller, and verifies the cleanup.
        script = """
set -e
apt-get update && apt-get install -y curl jq > /dev/null
mkdir -p /root/.cursor
cat > /root/.cursor/mcp.json <<EOF
{
  "mcpServers": {
    "existing-server": {
      "command": "echo",
      "args": ["hello"]
    }
  }
}
EOF

echo "[TEST] Running install..."
# Run installer (real run, skip Stata check by not passing --verify)
bash /repo/plugin/install.sh --agent cursor --scope user

echo "[TEST] Verifying install integrity..."
# Use jq to verify JSON structure
if ! jq -e '.mcpServers["mcp-stata"]' /root/.cursor/mcp.json > /dev/null; then
    echo "ERROR: mcp-stata not found in config"
    cat /root/.cursor/mcp.json
    exit 1
fi
if ! jq -e '.mcpServers["existing-server"]' /root/.cursor/mcp.json > /dev/null; then
    echo "ERROR: existing-server was lost"
    cat /root/.cursor/mcp.json
    exit 1
fi

echo "[TEST] Running uninstall..."
bash /repo/plugin/install.sh --uninstall --agent cursor --scope user

echo "[TEST] Verifying uninstall integrity..."
if jq -e '.mcpServers["mcp-stata"]' /root/.cursor/mcp.json > /dev/null; then
    echo "ERROR: mcp-stata still found in config after uninstall"
    cat /root/.cursor/mcp.json
    exit 1
fi
if ! jq -e '.mcpServers["existing-server"]' /root/.cursor/mcp.json > /dev/null; then
    echo "ERROR: existing-server was lost after uninstall"
    cat /root/.cursor/mcp.json
    exit 1
fi

echo "INTEGRITY_CHECK_PASSED"
"""
        res = self.run_in_docker("ubuntu:latest", script)
        print(res.stdout)
        if res.returncode != 0:
            print(res.stderr)
        self.assertEqual(res.returncode, 0)
        self.assertIn("INTEGRITY_CHECK_PASSED", res.stdout)

    def test_alpine_uninstall(self):
        print("Testing Uninstall on Alpine...")
        # Alpine: ensure even with musl/sh, the uninstall command exits 0
        res = self.run_in_docker("alpine:latest", "apk add --no-cache bash curl && bash /repo/plugin/install.sh --uninstall --dry-run --no-fail-on-empty", shell="sh")
        print(res.stdout)
        if res.returncode != 0:
            print(res.stderr)
        self.assertEqual(res.returncode, 0)

if __name__ == "__main__":
    unittest.main()
