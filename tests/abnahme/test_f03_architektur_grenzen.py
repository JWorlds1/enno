"""F03 Architektur-Grenzen als Fitness-Funktionen: die HTTP-Schicht kennt keine Persistenztechnik,
die Marke lebt an genau zwei Stellen."""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _imports(datei: Path) -> set[str]:
    mods = set()
    for n in ast.walk(ast.parse(datei.read_text())):
        if isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add(("." * n.level) + (n.module or ""))
    return mods


def test_api_importiert_weder_sqlalchemy_noch_db():
    mods = _imports(ROOT / "fldos" / "api.py")
    verboten = {m for m in mods if m.split(".")[0] in ("sqlalchemy", "asyncpg") or m in (".db", "fldos.db")}
    assert not verboten, sorted(verboten)


def test_markenfarbe_nur_in_theme_und_brand():
    erlaubt = {"theme.css", "brand.ts"}
    treffer = [str(p.relative_to(ROOT)) for p in (ROOT / "web" / "src").rglob("*")
               if p.is_file() and p.suffix in (".ts", ".tsx", ".css") and p.name not in erlaubt
               and re.search(r"fcc008", p.read_text(errors="ignore"), re.I)]
    assert not treffer, treffer


def test_positivkontrolle_theme_enthaelt_markenfarbe():
    assert re.search(r"fcc008", (ROOT / "web" / "src" / "theme.css").read_text(), re.I)
