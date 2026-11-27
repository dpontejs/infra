"""Consistency of ansible/group_vars/all.yml: a retired stack must be gone from every list."""

import unittest
from pathlib import Path

import yaml

VARS = yaml.safe_load((Path(__file__).resolve().parent.parent / "ansible/group_vars/all.yml").read_text())


class GroupVarsTest(unittest.TestCase):
    def test_retired_stacks_are_not_enabled_deployed_or_watched(self) -> None:
        retired = set(VARS.get("retired_stacks", []))
        self.assertIn("flamengo-news", retired)
        self.assertFalse(retired & set(VARS["stacks_enabled"]), "retired stack still in stacks_enabled")
        self.assertFalse(retired & set(VARS["auto_update_stacks"]), "retired stack still auto-deployed")
        watched = {name.rsplit("-", 1)[0] for name in VARS["watched_containers"]}
        self.assertFalse({f"{s}-{s}" for s in retired} & watched, "retired stack still watched")

    def test_auto_updated_stacks_are_enabled(self) -> None:
        self.assertLessEqual(set(VARS["auto_update_stacks"]), set(VARS["stacks_enabled"]))


if __name__ == "__main__":
    unittest.main()
