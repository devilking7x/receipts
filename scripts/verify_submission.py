"""Pre-submission self-check for Receipts.

Checks, in order:
1. Required files exist.
2. At least 3 input examples and matching output examples exist, and
   the output vendor names cover the input vendor names.
3. No forbidden files (.env, .pem, .key) are present.
4. No real secret VALUES are present. Identifier words (token, key,
   password as variable names) and .env.example placeholders are
   reported as informational only, not failures, because the required
   environment names themselves contain those words.
5. Dockerfile defaults to SAMPLE_MODE=true.
6. metadata.json is valid and declares sample mode support.
7. README contains the nine required sections.

Exit code 0 means every hard check passed.
"""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REQUIRED_FILES = [
    "run.py", "config.py", "requirements.txt", "Dockerfile",
    ".env.example", ".gitignore", ".dockerignore", "metadata.json",
    "README.md", "LICENSE", "conftest.py",
    "cognition/__init__.py", "cognition/generator.py",
    "cognition/markov_state.py", "cognition/world_model.py",
    "agents/__init__.py", "agents/planner.py", "agents/executors.py",
    "agents/evaluator.py", "agents/writer.py", "agents/pipeline.py",
    "data_layer/__init__.py", "data_layer/zetaris_client.py",
    "data_layer/search_client.py",
    "data_layer/sample_fixtures/helios_raw.json",
    "data_layer/sample_fixtures/clean_vendor_raw.json",
    "data_layer/sample_fixtures/moderate_vendor_raw.json",
    "app/__init__.py", "app/main.py",
    "app/adapters/__init__.py", "app/adapters/zetaris.py",
    "app/adapters/meterless.py",
    "scripts/verify_submission.py", "scripts/smoke_test.py",
    "tests/test_receipts.py",
    "input_examples/01_helios.json",
    "input_examples/02_northwind_clean.json",
    "input_examples/03_bluepeak_moderate.json",
]

README_SECTIONS = [
    "setup", "usage", "dependencies", "agent roles", "examples",
    "limitations", "ai disclosure", "pre-existing",
    "live-vs-cached",
]

# Patterns that indicate a real secret VALUE, not a word.
VALUE_PATTERNS = [
    re.compile(r"nvapi-[A-Za-z0-9]{8,}"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY"),
]
ASSIGNMENT_PATTERN = re.compile(
    r"(api[_-]?key|token|password)\s*=\s*[\"']?([^\"'\s]+)[\"']?",
    re.IGNORECASE)
PLACEHOLDER_HINTS = ("your_", "example", "placeholder", "here",
                     "<", "xxx", "change_me")


def _is_placeholder(value):
    lowered = value.lower()
    return any(hint in lowered for hint in PLACEHOLDER_HINTS)


def main():
    failures = []
    infos = []

    def check(name, ok, detail=""):
        mark = "PASS" if ok else "FAIL"
        print("[%s] %s %s" % (mark, name, detail))
        if not ok:
            failures.append(name)

    for rel in REQUIRED_FILES:
        check("file exists: %s" % rel, os.path.isfile(os.path.join(ROOT, rel)))

    input_dir = os.path.join(ROOT, "input_examples")
    output_dir = os.path.join(ROOT, "output_examples")
    inputs = sorted(f for f in os.listdir(input_dir)
                    if f.endswith(".json")) if os.path.isdir(input_dir) else []
    check("at least 3 input examples", len(inputs) >= 3, "(%d)" % len(inputs))
    input_vendors = set()
    for fname in inputs:
        with open(os.path.join(input_dir, fname), encoding="utf-8") as fh:
            input_vendors.add(json.load(fh)["vendor_name"])
    outputs = sorted(os.listdir(output_dir)) \
        if os.path.isdir(output_dir) else []
    check("at least 3 output examples", len(outputs) >= 3,
          "(%d)" % len(outputs))
    output_vendors = set()
    for fname in outputs:
        if fname.endswith(".json"):
            with open(os.path.join(output_dir, fname),
                      encoding="utf-8") as fh:
                output_vendors.add(json.load(fh)["vendor_name"])
    check("output vendors cover input vendors",
          input_vendors <= output_vendors,
          "(inputs=%s outputs=%s)" % (sorted(input_vendors),
                                       sorted(output_vendors)))

    forbidden = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        if ".git" in dirpath:
            continue
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fname in filenames:
            if fname == ".env" or fname.endswith((".pem", ".key")):
                forbidden.append(os.path.relpath(
                    os.path.join(dirpath, fname), ROOT))
    check("no forbidden files (.env/.pem/.key)", not forbidden,
          "(%s)" % forbidden if forbidden else "")

    secret_hits = []
    identifier_hits = 0
    for dirpath, dirnames, filenames in os.walk(ROOT):
        if ".git" in dirpath:
            continue
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "__pycache__")]
        for fname in filenames:
            path = os.path.join(dirpath, fname)
            try:
                with open(path, encoding="utf-8", errors="ignore") as fh:
                    text = fh.read()
            except OSError:
                continue
            for pattern in VALUE_PATTERNS:
                if pattern.search(text):
                    secret_hits.append("%s: %s"
                                       % (os.path.relpath(path, ROOT),
                                          pattern.pattern))
            for match in ASSIGNMENT_PATTERN.finditer(text):
                identifier_hits += 1
                value = match.group(2)
                if not _is_placeholder(value) and len(value) >= 16:
                    secret_hits.append("%s: suspicious assignment %s"
                                       % (os.path.relpath(path, ROOT),
                                          match.group(0)[:60]))
    check("no real secret values", not secret_hits,
          "(%s)" % secret_hits if secret_hits else "")
    infos.append("identifier word occurrences (names, not values): %d"
                 % identifier_hits)

    with open(os.path.join(ROOT, "Dockerfile"), encoding="utf-8") as fh:
        dockerfile = fh.read()
    check("Dockerfile defaults SAMPLE_MODE=true",
          "ENV SAMPLE_MODE=true" in dockerfile)
    with open(os.path.join(ROOT, "metadata.json"),
              encoding="utf-8") as fh:
        metadata = json.load(fh)
    check("metadata sample_mode_supported true",
          metadata.get("sample_mode_supported") is True)
    check("metadata trace_file_path logs/traces.jsonl",
          metadata.get("trace_file_path") == "logs/traces.jsonl")
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
        readme = fh.read().lower()
    missing_sections = [s for s in README_SECTIONS if s not in readme]
    check("README has all nine required sections", not missing_sections,
          "(missing: %s)" % missing_sections if missing_sections else "")

    for info in infos:
        print("[INFO] %s" % info)
    print("")
    if failures:
        print("VERIFY FAILED: %d failing check(s)" % len(failures))
        return 1
    print("VERIFY PASSED: all hard checks green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
