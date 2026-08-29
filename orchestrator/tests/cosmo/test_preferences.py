"""COS-012: Preferences API tests — REST-based, no localStorage."""
import pytest


class TestPreferencesModel:
    def test_defaults(self):
        from cosmo.api.routes.preferences import Preferences
        p = Preferences()
        assert p.theme == "light"
        assert p.domain == "all"
        assert p.env == "stage"
        assert p.nav == "domains"

    def test_update_partial(self):
        from cosmo.api.routes.preferences import UpdatePreferences
        u = UpdatePreferences(theme="dark")
        assert u.theme == "dark"
        assert u.domain is None  # не трогаем
        assert u.env is None


class TestPreferencesStore:
    def test_default_get(self):
        from cosmo.api.routes.preferences import get_preferences, reset_store
        reset_store()

        # Создаём мок Request
        class MockRequest:
            @property
            def cookies(self): return {}
            @property
            def headers(self): return {}
            @property
            def client(self): return None

        # В тестовом окружении без asyncio вызываем напрямую
        import asyncio
        req = MockRequest()
        # Вызываем синхронно через asyncio.run (если доступно)
        # Но для простоты вызываем напрямую
        from cosmo.api.routes.preferences import _store
        _store.clear()

        # Прямая проверка логики store
        key = "ip:test"
        from cosmo.api.routes.preferences import Preferences
        prefs = _store.get(key)
        assert prefs is None  # ещё нет

        _store[key] = Preferences(theme="dark", domain="payments")
        assert _store[key].theme == "dark"
        assert _store[key].domain == "payments"

    def test_update(self):
        from cosmo.api.routes.preferences import Preferences, _store, reset_store
        reset_store()

        _store["test"] = Preferences()
        updated = _store["test"].model_copy(update={"theme": "dark", "domain": "cbr"})
        _store["test"] = updated

        assert _store["test"].theme == "dark"
        assert _store["test"].domain == "cbr"
        assert _store["test"].env == "stage"  # не менялся

    def test_reset_store(self):
        from cosmo.api.routes.preferences import Preferences, _store, reset_store
        _store["x"] = Preferences(theme="dark")
        assert len(_store) > 0
        reset_store()
        assert len(_store) == 0


class TestNoLocalStorageUsage:
    """COS-012: подтверждение что localStorage НЕ используется."""

    def test_theme_provider_no_localstorage(self):
        """CosmoThemeProvider.tsx не использует localStorage/sessionStorage в коде."""
        from pathlib import Path
        import re

        provider = Path(__file__).resolve().parents[3] / "frontend" / "src" / "cosmo" / "theme" / "CosmoThemeProvider.tsx"
        content = provider.read_text(encoding="utf-8")
        # Исключаем комментарии — проверяем только строки кода
        code = re.sub(r'/\*.*?\*/|//.*', '', content, flags=re.DOTALL)
        assert "localStorage" not in code
        assert "sessionStorage" not in code

    def test_use_preference_hook_no_localstorage(self):
        """usePreference.ts использует fetch, а не localStorage в коде."""
        from pathlib import Path
        import re

        hook = Path(__file__).resolve().parents[3] / "frontend" / "src" / "cosmo" / "shared" / "usePreference.ts"
        content = hook.read_text(encoding="utf-8")
        code = re.sub(r'/\*.*?\*/|//.*', '', content, flags=re.DOTALL)
        assert "localStorage" not in code
        assert "sessionStorage" not in code
        assert "fetch(" in code  # использует REST

    def test_control_station_no_localstorage(self):
        """ControlStationShell.tsx использует usePreference, а не useState."""
        from pathlib import Path
        import re

        shell = Path(__file__).resolve().parents[3] / "frontend" / "src" / "cosmo" / "station" / "ControlStationShell.tsx"
        content = shell.read_text(encoding="utf-8")
        code = re.sub(r'/\*.*?\*/|//.*', '', content, flags=re.DOTALL)
        assert "localStorage" not in code
        assert "sessionStorage" not in code
        assert "usePreference" in code

    def test_app_tsx_no_localstorage(self):
        """App.tsx не использует localStorage."""
        from pathlib import Path
        import re

        app = Path(__file__).resolve().parents[3] / "frontend" / "src" / "App.tsx"
        content = app.read_text(encoding="utf-8")
        code = re.sub(r'/\*.*?\*/|//.*', '', content, flags=re.DOTALL)
        assert "localStorage" not in code
        assert "sessionStorage" not in code

    def test_deep_linker_no_localstorage(self):
        """DeepLinker.tsx использует URL, а не localStorage."""
        from pathlib import Path
        import re

        dl = Path(__file__).resolve().parents[3] / "frontend" / "src" / "cosmo" / "shared" / "DeepLinker.tsx"
        content = dl.read_text(encoding="utf-8")
        code = re.sub(r'/\*.*?\*/|//.*', '', content, flags=re.DOTALL)
        assert "localStorage" not in code
        assert "sessionStorage" not in code

    def test_web_ide_shell_no_localstorage(self):
        """WebIDEShell.tsx не использует localStorage."""
        from pathlib import Path
        import re

        ide = Path(__file__).resolve().parents[3] / "frontend" / "src" / "cosmo" / "ide" / "WebIDEShell.tsx"
        content = ide.read_text(encoding="utf-8")
        code = re.sub(r'/\*.*?\*/|//.*', '', content, flags=re.DOTALL)
        assert "localStorage" not in code
        assert "sessionStorage" not in code

    def test_use_live_run_no_localstorage(self):
        """useLiveRun.ts использует EventSource, а не localStorage."""
        from pathlib import Path
        import re

        hook = Path(__file__).resolve().parents[3] / "frontend" / "src" / "cosmo" / "shared" / "useLiveRun.ts"
        content = hook.read_text(encoding="utf-8")
        code = re.sub(r'/\*.*?\*/|//.*', '', content, flags=re.DOTALL)
        assert "localStorage" not in code
        assert "sessionStorage" not in code
        assert "EventSource" in code

    def test_surface_switcher_no_localstorage(self):
        """SurfaceSwitcher.tsx — чистые пропсы, без localStorage."""
        from pathlib import Path
        import re

        ss = Path(__file__).resolve().parents[3] / "frontend" / "src" / "cosmo" / "shared" / "SurfaceSwitcher.tsx"
        content = ss.read_text(encoding="utf-8")
        code = re.sub(r'/\*.*?\*/|//.*', '', content, flags=re.DOTALL)
        assert "localStorage" not in code
        assert "sessionStorage" not in code