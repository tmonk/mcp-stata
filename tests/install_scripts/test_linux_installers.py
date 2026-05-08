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
        # We mount the install script so we can test the local version
        docker_cmd = [
            "docker", "run", "--rm",
            "-v", f"{INSTALL_SH}:/install.sh:ro",
            image,
            shell, "-c", command
        ]
        return subprocess.run(docker_cmd, capture_output=True, text=True, env=env)

    def test_ubuntu_install(self):
        print("Testing on Ubuntu (Minimal)...")
        # Ubuntu: only add curl (to start the script). It should install tar/gzip itself.
        res = self.run_in_docker("ubuntu:latest", "apt-get update && apt-get install -y curl && bash /install.sh --dry-run --agent claude")
        print(res.stdout)
        if res.returncode != 0:
            print(res.stderr)
        self.assertEqual(res.returncode, 0)
        self.assertIn("uv", res.stdout)
        self.assertIn("Launching mcp-stata installer", res.stdout)
        # Verify it detected missing deps
        self.assertIn("Missing system dependencies", res.stdout)

    def test_alpine_install(self):
        print("Testing on Alpine...")
        # Alpine: must install bash first as the script uses bashisms.
        # But we don't install tar/gzip so we can test the script's dep-management.
        res = self.run_in_docker("alpine:latest", "apk add --no-cache bash curl && bash /install.sh --dry-run --agent claude")
        print(res.stdout)
        if res.returncode != 0:
            print(res.stderr)
        self.assertEqual(res.returncode, 0)
        self.assertIn("uv", res.stdout)
        self.assertIn("Missing system dependencies", res.stdout)

    def test_fedora_install(self):
        print("Testing on Fedora...")
        res = self.run_in_docker("fedora:latest", "dnf install -y curl && bash /install.sh --dry-run --agent claude")
        print(res.stdout)
        if res.returncode != 0:
            print(res.stderr)
        self.assertEqual(res.returncode, 0)

    def test_opensuse_install(self):
        print("Testing on openSUSE (Dependency Test)...")
        # openSUSE: must install bash first.
        res = self.run_in_docker("opensuse/leap:latest", "zypper --non-interactive install curl bash && bash /install.sh --dry-run --agent claude")
        print(res.stdout)
        if res.returncode != 0:
            print(res.stderr)
        self.assertEqual(res.returncode, 0)
        self.assertIn("Missing system dependencies", res.stdout)

    def test_arch_install(self):
        print("Testing on Arch Linux...")
        res = self.run_in_docker("archlinux:latest", "pacman -Sy --noconfirm curl bash && bash /install.sh --dry-run --agent claude")
        print(res.stdout)
        if res.returncode != 0:
            print(res.stderr)
        self.assertEqual(res.returncode, 0)

if __name__ == "__main__":
    unittest.main()
