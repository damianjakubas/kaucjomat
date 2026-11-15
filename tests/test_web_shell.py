"""Testy dymne powłoki HTML/CSS/JS oraz automatyczni strażnicy jakości kodu."""

import ast
import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from kaucjomat.app import create_app
from kaucjomat.config import get_project_root


def _assert_no_external_urls(content: str, asset_name: str) -> None:
    """Sprawdza brak odwołań sieciowych i protocol-relative URL w zasobach frontendowych."""
    lowered = content.lower()
    forbidden_schemes = ("http://", "https://", "ws://", "wss://", "ftp://")
    for scheme in forbidden_schemes:
        assert scheme not in lowered, f"Wykryto zewnętrzny schemat {scheme} w {asset_name}."

    protocol_relative_refs = ('src="//', "src='//", 'href="//', "href='//", "url(//", 'url("//', "url('//")
    for ref in protocol_relative_refs:
        assert ref not in lowered, f"Wykryto adres protocol-relative {ref} w {asset_name}."


def _extract_pkg_name(requirement_spec: str) -> str:
    """Wyodrębnia znormalizowaną nazwę pakietu z deklaracji zależności bez użycia regexów."""
    cleaned = requirement_spec.strip().lower()
    for sep in (";", "[", "=", "<", ">", "!", "~", " "):
        cleaned = cleaned.split(sep, 1)[0]
    return cleaned.strip().replace("_", "-")


def test_root_serves_offline_demo_shell_with_three_views() -> None:
    """Sprawdza serwowanie `/` oraz obecność wszystkich 3 widoków, napisów DEMO i brak CDN."""
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    html = response.text
    required_fragments = (
        "KaucjaSim",
        "DEMO",
        "SYMULATOR EDUKACYJNY — TRYB DEMO",
        "KASA SKLEPOWA — TRYB DEMO (Dokumenty niefiskalne)",
        "Butelkomat",
        "Kasa Sklepowa",
        "Analityka i Benchmark GIL",
        'data-view-panel="butelkomat"',
        'data-view-panel="kasa"',
        'data-view-panel="analityka"',
        'data-view-target="butelkomat"',
        'data-view-target="kasa"',
        'data-view-target="analityka"',
        'id="deposit-dropzone"',
        'id="package-cards-shelf"',
        'id="reset-demo-btn"',
        'id="scanner-result-box"',
        "/static/styles.css",
        "/static/return_machine.css",
        "/static/app.js",
        "/static/return_machine.js",
    )
    for fragment in required_fragments:
        assert fragment in html, f"Brak wymaganego fragmentu w index.html: {fragment}"

    _assert_no_external_urls(html, "index.html")


def test_static_assets_served_with_expected_content() -> None:
    """Weryfikuje serwowanie lokalnych zasobów CSS i JS dla powłoki oraz butelkomatu."""
    client = TestClient(create_app())

    css_response = client.get("/static/styles.css")
    assert css_response.status_code == 200
    assert "text/css" in css_response.headers["content-type"]
    assert ".demo-badge" in css_response.text
    assert ".view-switcher" in css_response.text
    _assert_no_external_urls(css_response.text, "styles.css")

    machine_css_response = client.get("/static/return_machine.css")
    assert machine_css_response.status_code == 200
    assert "text/css" in machine_css_response.headers["content-type"]
    assert ".deposit-dropzone" in machine_css_response.text
    assert ".package-cards-shelf" in machine_css_response.text
    _assert_no_external_urls(machine_css_response.text, "return_machine.css")

    js_response = client.get("/static/app.js")
    assert js_response.status_code == 200
    assert "javascript" in js_response.headers["content-type"]
    assert "/**" in js_response.text
    for fn_name in ("selectView", "fetchViewMetadata", "renderErrorBanner", "initAppShell"):
        assert fn_name in js_response.text, f"Brak funkcji {fn_name} w app.js"
    _assert_no_external_urls(js_response.text, "app.js")

    machine_js_response = client.get("/static/return_machine.js")
    assert machine_js_response.status_code == 200
    assert "javascript" in machine_js_response.headers["content-type"]
    assert "/**" in machine_js_response.text
    for fn_name in (
        "loadReturnCards",
        "loadReturnSession",
        "submitPackageDeposit",
        "resetReturnDemoState",
        "initReturnMachine",
    ):
        assert fn_name in machine_js_response.text, f"Brak funkcji {fn_name} w return_machine.js"
    _assert_no_external_urls(machine_js_response.text, "return_machine.js")


def test_module_line_count_limits() -> None:
    """Pilnuje limitu < 300 linii w modułach/testach/HTML/JS oraz < 200 linii w plikach `.css`."""
    root = get_project_root()
    checked_dirs = (root / "src" / "kaucjomat", root / "tests")
    source_extensions = {".py", ".html", ".css", ".js"}

    violations: list[str] = []
    for base_dir in checked_dirs:
        for file_path in sorted(base_dir.rglob("*")):
            if not file_path.is_file() or file_path.suffix not in source_extensions:
                continue
            if "__pycache__" in file_path.parts:
                continue
            line_count = len(file_path.read_text(encoding="utf-8").splitlines())
            limit = 200 if file_path.suffix == ".css" else 300
            if line_count >= limit:
                rel_path = file_path.relative_to(root)
                violations.append(f"{rel_path}: {line_count} linii (limit < {limit})")

    assert not violations, f"Przekroczono limit linii: {violations}"


def _is_model_or_dataclass(class_node: ast.ClassDef) -> bool:
    """Rozpoznaje klasy Pydantic BaseModel oraz klasy oznaczone dekoratorem @dataclass."""
    for base in class_node.bases:
        if isinstance(base, ast.Name) and base.id == "BaseModel":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "BaseModel":
            return True

    for decorator in class_node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "dataclass":
            return True
        if isinstance(decorator, ast.Call):
            func = decorator.func
            if isinstance(func, ast.Name) and func.id == "dataclass":
                return True
            if isinstance(func, ast.Attribute) and func.attr == "dataclass":
                return True
    return False


def _collect_missing_annotations_and_docstrings(module_path: Path, tree: ast.Module) -> list[str]:
    """Zbiera braki docstringów i adnotacji typów z modułu Pythona."""
    issues: list[str] = []
    rel_name = module_path.name

    if not ast.get_docstring(tree):
        issues.append(f"{rel_name}: brak docstringa modułu")

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if not ast.get_docstring(node):
                issues.append(f"{rel_name}:{node.name}: brak docstringa klasy")
            if _is_model_or_dataclass(node):
                ann_fields = [stmt for stmt in node.body if isinstance(stmt, ast.AnnAssign)]
                unannotated = [stmt for stmt in node.body if isinstance(stmt, ast.Assign)]
                if not ann_fields:
                    issues.append(f"{rel_name}:{node.name}: brak adnotacji pól (AnnAssign)")
                if unannotated:
                    issues.append(f"{rel_name}:{node.name}: wykryto pola bez adnotacji typu")

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not ast.get_docstring(node):
                issues.append(f"{rel_name}:{node.name}: brak docstringa funkcji/metody")
            if node.returns is None:
                issues.append(f"{rel_name}:{node.name}: brak adnotacji zwracanego typu")

            positional = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            for arg in positional:
                if arg.arg in {"self", "cls"}:
                    continue
                if arg.annotation is None:
                    issues.append(
                        f"{rel_name}:{node.name}({arg.arg}): brak adnotacji typu argumentu"
                    )

    return issues


def test_docstrings_and_type_annotations_present() -> None:
    """Weryfikuje przez AST obecność docstringów i adnotacji typów w `src/kaucjomat/**/*.py`."""
    src_dir = get_project_root() / "src" / "kaucjomat"
    all_issues: list[str] = []

    for py_file in sorted(src_dir.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
        all_issues.extend(_collect_missing_annotations_and_docstrings(py_file, tree))

    assert not all_issues, "Braki docstringów lub adnotacji typów:\n" + "\n".join(all_issues)


def test_requirements_txt_contains_runtime_dependencies_only() -> None:
    """Sprawdza zgodność `requirements.txt` z `pyproject.toml` i `uv.lock` (bez paczek dev)."""
    root = get_project_root()
    req_path = root / "requirements.txt"
    pyproject_data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    lock_data = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))

    assert req_path.is_file(), "Brak pliku requirements.txt w katalogu głównym."
    runtime_declared = {
        _extract_pkg_name(dep)
        for dep in pyproject_data.get("project", {}).get("dependencies", [])
    }
    dev_declared = {
        _extract_pkg_name(dep)
        for dep in pyproject_data.get("dependency-groups", {}).get("dev", [])
    }
    locked_versions = {
        pkg["name"].lower().replace("_", "-"): pkg["version"]
        for pkg in lock_data.get("package", [])
        if "name" in pkg and "version" in pkg
    }

    lines = [
        line.strip().lower()
        for line in req_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert not any(line.startswith("-e") for line in lines), "Wykryto lokalny wpis `-e` w requirements.txt"

    exported_versions: dict[str, str] = {}
    for line in lines:
        assert "==" in line, f"Oczekiwano przypiętej wersji '==' w requirements.txt: {line}"
        name, version = line.split("==", 1)
        normalized_name = name.strip().replace("_", "-")
        exported_versions[normalized_name] = version.strip()

    assert runtime_declared <= set(exported_versions), "Brak zależności runtime w requirements.txt"
    assert not (dev_declared & set(exported_versions)), "Zależności dev trafiły do requirements.txt"
    for pkg_name, pkg_version in exported_versions.items():
        assert locked_versions.get(pkg_name) == pkg_version, (
            f"Rozbieżność wersji {pkg_name}: requirements.txt={pkg_version}, uv.lock={locked_versions.get(pkg_name)}"
        )
