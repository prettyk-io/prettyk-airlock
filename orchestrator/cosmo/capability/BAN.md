# BAN: tool_ctl.py

`ScannerCtl`, `PlaywrightCtl`, `RunCapabilities` — **не размещать в этом каталоге**.

Это Pure Box (управление ZAP/Playwright процессами через REST).
Cosmo только триггерит сессии через `CapabilityBroker.acquire()` и получает результаты через webhook/SSE.

**Запрещено:**
- `from cosmo.capability.tool_ctl import ...`
- `from orchestrator.cosmo.capability.tool_ctl import ...`
- Любые локальные импорты адаптеров scanner/playwright

**Разрешено:**
- `from cosmo.capability.broker import CapabilityBroker, Capability`

Удалён: COS-ROLLBACK от 2026-08-29. Архитектура не нарушена.