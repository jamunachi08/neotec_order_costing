#!/usr/bin/env python3
"""Pre-package sanity check: every DocType folder has a JSON + py + __init__,
every JSON parses, every Python file compiles, and every hook target resolves
to a real module path."""
import ast, json, os, pathlib, re, sys

ROOT = pathlib.Path(__file__).parent / "neotec_order_costing"
errors, checked = [], 0

for path in ROOT.rglob("*.json"):
    try:
        json.loads(path.read_text())
        checked += 1
    except Exception as exc:
        errors.append(f"JSON {path}: {exc}")

for path in ROOT.rglob("*.py"):
    try:
        ast.parse(path.read_text())
        checked += 1
    except SyntaxError as exc:
        errors.append(f"PY {path}: {exc}")

dt_root = ROOT / "neotec_order_costing" / "doctype"
for folder in sorted(p for p in dt_root.iterdir() if p.is_dir()):
    for required in (f"{folder.name}.json", "__init__.py"):
        if not (folder / required).exists():
            errors.append(f"MISSING {folder.name}/{required}")

# patches.txt must carry BOTH sections or frappe's parser raises KeyError
# during install, after doctypes have already synced.
import configparser
pf = ROOT / "patches.txt"
if pf.exists():
    cp = configparser.ConfigParser(allow_no_value=True)
    try:
        cp.read(pf)
        for section in ("pre_model_sync", "post_model_sync"):
            if not cp.has_section(section):
                errors.append(f"patches.txt: missing [{section}] section")
        for section in cp.sections():
            for entry in cp[section]:
                mod = entry.replace(".", "/") + ".py"
                if not (ROOT.parent / mod).exists():
                    errors.append(f"patches.txt: {entry} -> missing {mod}")
    except Exception as exc:
        errors.append(f"patches.txt unparseable: {exc}")
else:
    errors.append("patches.txt missing")

# Controllers must not shadow Document internals. Overriding _save, _submit,
# db_insert and friends breaks every save path on the doctype.
RESERVED = {
    "_save", "_submit", "_cancel", "_rename", "_validate", "_set_defaults",
    "db_insert", "db_update", "load_from_db", "get_valid_dict", "get_doc_before_save",
    "run_method", "check_permission", "set_new_name", "get_title", "as_dict",
}
dt_root2 = ROOT / "neotec_order_costing" / "doctype"
if dt_root2.exists():
    for path in dt_root2.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        tree2 = ast.parse(path.read_text())
        for node in ast.walk(tree2):
            if isinstance(node, ast.ClassDef):
                for member in node.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                            and member.name in RESERVED:
                        errors.append(
                            f"RESERVED OVERRIDE {path.name}: {node.name}.{member.name} "
                            f"shadows a frappe Document method"
                        )

# Every custom_noc_* field written or read anywhere in the codebase must be
# declared in install.py. An undeclared field is an "Unknown column" error
# waiting to happen at runtime.
install_src = (ROOT / "install.py").read_text()
declared = set(re.findall(r'"fieldname":\s*"(custom_noc_[a-z0-9_]+)"', install_src))
declared |= {"custom_noc_order_cost_peg"}  # PEG_LINK constant

used = set()
for path in list(ROOT.rglob("*.py")) + list(ROOT.rglob("*.js")):
    if path.name == "install.py":
        continue
    used |= set(re.findall(r'custom_noc_[a-z0-9_]+', path.read_text()))

# fields on doctypes this app owns are in their own JSON, not install.py
own = set()
for path in ROOT.rglob("*.json"):
    own |= set(re.findall(r'"fieldname":\s*"(custom_noc_[a-z0-9_]+)"', path.read_text()))

undeclared = sorted(used - declared - own)
if undeclared:
    errors.append("UNDECLARED custom fields (add to install.py): " + ", ".join(undeclared))

# A client script that calls the backend with frm.doc.name must first bail out
# on an unsaved document, whose temporary name does not exist server side.
for path in (ROOT / "public" / "js").glob("*.js"):
    js = path.read_text()
    if "frm.doc.name" in js and "method:" in js and "is_new()" not in js:
        errors.append(
            f"UNGUARDED {path.name}: calls the server with frm.doc.name "
            f"but never checks frm.is_new()"
        )

hooks = (ROOT / "hooks.py").read_text()
tree = ast.parse(hooks)
targets = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        v = node.value
        if v.startswith("neotec_order_costing.") and "." in v[21:]:
            targets.add(v)
for target in sorted(targets):
    module = target.rsplit(".", 1)[0].replace(".", "/")
    if not (ROOT.parent / (module + ".py")).exists():
        errors.append(f"HOOK TARGET missing module: {target}")

print(f"checked {checked} files")
if errors:
    print("\n".join("  ! " + e for e in errors))
    sys.exit(1)
print("tree OK")
