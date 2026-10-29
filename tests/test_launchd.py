"""The launchd agents render to valid plists that run what the docs say they run."""
from __future__ import annotations

import plistlib
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("bash") and shutil.which("sed"), "needs bash and sed")
class TestCarryAgents(unittest.TestCase):
    def render(self):
        out = subprocess.run(["bash", str(ROOT / "scripts" / "install-carry-launchd.sh"), "--print"],
                             capture_output=True, text=True, check=True,
                             env={"PATH": "/usr/bin:/bin", "HOME": "/tmp", "PYTHON": "/x/python"}).stdout
        docs = re.findall(r"<\?xml.*?</plist>", out, re.S)
        return {p["Label"]: p for p in (plistlib.loads(d.encode()) for d in docs)}

    def test_two_books_kept_alive_from_the_repo(self):
        agents = self.render()
        self.assertEqual(sorted(agents), ["com.espero.carry-maker", "com.espero.carry-taker"])
        for label, p in agents.items():
            costs = label.rsplit("-", 1)[1]
            args = p["ProgramArguments"]
            self.assertEqual(args[:5], ["/x/python", "-m", "espero", "carry", "paper"])
            self.assertEqual(args[args.index("--costs") + 1], costs)
            self.assertEqual(args[args.index("--state") + 1], str(ROOT / f"carry-{costs}.db"))
            self.assertIn("--loop", args)
            self.assertEqual(p["WorkingDirectory"], str(ROOT))          # where .env is read
            self.assertTrue(p["KeepAlive"] and p["RunAtLoad"])
            self.assertTrue(p["StandardOutPath"].endswith(f"carry-{costs}.log"))

    def test_only_the_maker_book_trades_on_testnet(self):
        agents = self.render()
        self.assertIn("--execute-testnet", agents["com.espero.carry-maker"]["ProgramArguments"])
        self.assertNotIn("--execute-testnet", agents["com.espero.carry-taker"]["ProgramArguments"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
