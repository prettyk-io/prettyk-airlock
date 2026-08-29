"""COS-020: CSS Style Boundary tests — isolation invariants.

Инварианты:
  1. .cosmo-control-station существует и НЕ содержит .cosmo-ide-root
  2. .cosmo-ide-root существует и НЕ содержит .cosmo-control-station
  3. CSS-переменные --cosmo-* доступны в обоих контекстах
  4. SurfaceSwitcher рендерит обе кнопки
"""
import re
from pathlib import Path


FRONTEND_SRC = Path(__file__).resolve().parents[3] / "frontend" / "src"
STYLES_DIR = FRONTEND_SRC / "styles"
COSMO_THEME = FRONTEND_SRC / "cosmo" / "theme"


class TestCSSFilesExist:
    def test_global_css_exists(self):
        assert (STYLES_DIR / "global.css").is_file()

    def test_control_station_css_exists(self):
        assert (STYLES_DIR / "control-station.css").is_file()

    def test_web_ide_css_exists(self):
        assert (STYLES_DIR / "web-ide.css").is_file()

    def test_style_bounds_css_exists(self):
        assert (COSMO_THEME / "styleBounds.css").is_file()


class TestCSSVariableBridge:
    def test_shared_tokens_in_global_css(self):
        content = (STYLES_DIR / "global.css").read_text(encoding="utf-8")
        # Canon-переменные из research spec
        assert "--pk-status-passed" in content
        assert "--pk-status-failed" in content
        assert "--pk-status-blocked" in content
        assert "--pk-status-running" in content
        assert "--pk-bg-canvas-light" in content
        assert "--pk-bg-canvas-dark" in content

    def test_control_station_scoped(self):
        content = (STYLES_DIR / "control-station.css").read_text(encoding="utf-8")
        # Scoping: MUI CssBaseline inside .cosmo-control-station only
        assert ".cosmo-control-station" in content
        # Инвариант: НЕ протекает в IDE scope
        assert ".cosmo-control-station * {" in content

    def test_web_ide_scoped(self):
        content = (STYLES_DIR / "web-ide.css").read_text(encoding="utf-8")
        # Tailwind Preflight only inside .cosmo-ide-root
        assert ".cosmo-ide-root" in content
        # IDE-specific colors only через --ide-* переменные
        assert "--ide-bg" in content
        assert "--ide-text" in content

    def test_surface_switcher_css(self):
        content = (STYLES_DIR / "control-station.css").read_text(encoding="utf-8")
        assert ".cosmo-surface-switcher" in content
        assert ".cosmo-surface-switcher button.active" in content


class TestCSSNoLeak:
    """Проверить, что CSS-файлы не содержат взаимных утечек."""

    def test_control_station_no_ide_root_selector(self):
        content = (STYLES_DIR / "control-station.css").read_text(encoding="utf-8")
        # Игнорируем комментарии (/* ... */) — проверяем только правила
        rules_only = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        assert ".cosmo-ide-root" not in rules_only, (
            "Control Station CSS must NOT reference .cosmo-ide-root"
        )

    def test_web_ide_no_control_station_selector(self):
        content = (STYLES_DIR / "web-ide.css").read_text(encoding="utf-8")
        rules_only = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        assert ".cosmo-control-station" not in rules_only, (
            "Web IDE CSS must NOT reference .cosmo-control-station"
        )


class TestCosmoThemeProvider:
    """CosmoThemeProvider НЕ применяет глобальный CssBaseline."""

    def test_no_global_css_baseline(self):
        content = (COSMO_THEME / "CosmoThemeProvider.tsx").read_text(encoding="utf-8")
        # Проверить: нет импорта CssBaseline (кроме комментариев)
        code_lines = [l for l in content.splitlines() if not l.strip().startswith("//") and not l.strip().startswith("/*") and not l.strip().startswith("*")]
        code_only = "\n".join(code_lines)
        assert "import { CssBaseline" not in code_only, (
            "CosmoThemeProvider must NOT import CssBaseline for import"
        )
        assert "<CssBaseline" not in code_only, (
            "CosmoThemeProvider must NOT render <CssBaseline /> globally"
        )

    def test_scoped_css_comment(self):
        content = (COSMO_THEME / "CosmoThemeProvider.tsx").read_text(encoding="utf-8")
        # COS-020: CssBaseline is scoped — no global import.
        # After refactor (Flash/Boss 2026-08-29), theme is applied via
        # ThemeProvider + ScopedCssBaseline in ControlStationShell.
        # The Provider itself uses usePreference (REST) and creates MUI theme.
        assert "ThemeProvider" in content or "createTheme" in content, (
            "CosmoThemeProvider must provide MUI theme"
        )


class TestAppImportsCSS:
    """App.tsx импортирует все три CSS-файла."""

    def test_app_imports_styles(self):
        content = (FRONTEND_SRC / "App.tsx").read_text(encoding="utf-8")
        assert "./styles/global.css" in content
        assert "./styles/control-station.css" in content
        assert "./styles/web-ide.css" in content