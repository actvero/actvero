"""Regression tests for the publication boundary, including partial staging."""
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("public_check", Path(__file__).with_name("check-public-content.py"))
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def entries(extra=None, documents=None):
    docs = {"README.md": "Project overview"} | (documents or {})
    policy = {"documents": docs, "restricted_identifier_sha256": [hashlib.sha256(b"internalbrand").hexdigest()]}
    return {check.POLICY: ("100644", json.dumps(policy).encode()), "README.md": ("100644", b"# Project\n")} | (extra or {})


class PublicationTests(unittest.TestCase):
    def test_public_source_and_benign_substrings(self):
        self.assertEqual(check.inspect(entries({"icons.json": ("100644", b'{"name":"antenna","key":"sha512-EnNNwUW"}')})), [])

    def test_process_file_is_rejected_even_if_registered(self):
        errors = check.inspect(entries({"docs/HANDOFF.md": ("100644", b"# notes")}, {"docs/HANDOFF.md": "notes"}))
        self.assertIn("collaboration-process-document", [e[2] for e in errors])

    def test_unregistered_markdown_is_rejected(self):
        self.assertTrue(check.inspect(entries({"docs/notes.md": ("100644", b"# notes")})))

    def test_process_files_cannot_bypass_policy_with_another_format(self):
        for extension in ("txt", "json", "pdf", "docx", "csv"):
            name = "docs/HANDOFF." + extension
            with self.subTest(extension=extension):
                errors = check.inspect(entries({name: ("100644", b"notes")}, {name: "notes"}))
                self.assertIn("collaboration-process-document", [e[2] for e in errors])

    def test_new_documents_outside_docs_also_require_registration(self):
        for name in ("notes.txt", "guide.pdf", "archive/notes.docx"):
            with self.subTest(name=name):
                errors = check.inspect(entries({name: ("100644", b"notes")}))
                self.assertIn("unregistered-public-document", [e[2] for e in errors])

    def test_force_added_private_file_is_rejected(self):
        errors = check.inspect(entries({".local/process/note.json": ("100644", b"{}")}))
        self.assertIn("private-or-generated-file", [e[2] for e in errors])

    def test_process_narrative_cannot_hide_in_registered_readme(self):
        self.assertTrue(check.inspect(entries({"README.md": ("100644", "# Project\n本轮已完成测试".encode())})))

    def test_company_identifier_is_case_insensitive(self):
        self.assertTrue(check.inspect(entries({"data.json": ("100644", b'{"name":"InternalBrand"}')})))

    def test_secrets_are_rejected_without_value_in_diagnostics(self):
        secret = "gh" + "p_" + "a" * 36
        errors = check.inspect(entries({"config.py": ("100644", secret.encode())}))
        self.assertIn("access-token", [e[2] for e in errors])
        self.assertNotIn(secret, repr(errors))

    def test_env_is_forbidden_but_example_is_allowed(self):
        self.assertTrue(check.inspect(entries({".env": ("100644", b"SAMPLE=1")})))
        self.assertEqual(check.inspect(entries({".env.example": ("100644", b"SAMPLE=placeholder")})), [])

    def test_links_use_snapshot_not_filesystem(self):
        self.assertTrue(check.inspect(entries({"README.md": ("100644", b"# Project\n[missing](missing.md)")})))

    def test_symlinks_are_not_followed(self):
        self.assertTrue(check.inspect(entries({"external": ("120000", b"/tmp/private")})))

    def test_index_check_catches_secret_hidden_by_unstaged_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            content = entries({"config.py": ("100644", ("gh" + "p_" + "b" * 36).encode())})
            for name, (_, data) in content.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            (root / "config.py").write_text("safe = True\n")
            self.assertEqual(check.inspect(check.snapshot(root)), [])
            self.assertTrue(check.inspect(check.snapshot(root, staged=True)))


if __name__ == "__main__":
    unittest.main()
