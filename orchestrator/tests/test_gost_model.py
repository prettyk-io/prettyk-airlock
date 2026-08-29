"""COS-005: Тесты ГОСТ-Акт модели."""
import pytest
from pydantic import ValidationError
from cosmo.ledger import (
    GOSTAct, GOSTActHeader, GOSTActObject, GOSTFinding, GOSTSignature,
)


class TestGOSTSignature:
    def test_minimal(self):
        s = GOSTSignature(role="Руководитель", name="Иванов И.И.", date="2026-08-27")
        assert s.status == "signed"

    def test_empty_role(self):
        with pytest.raises(ValidationError):
            GOSTSignature(role="", name="x", date="2026-01-01")


class TestGOSTFinding:
    def test_critical(self):
        f = GOSTFinding(severity="Critical", title="SQLi в поле поиска",
                        description="Обнаружена SQL-инъекция", cwe="CWE-89")
        assert f.severity == "Critical"
        assert f.cwe == "CWE-89"

    def test_with_evidence(self):
        f = GOSTFinding(severity="High", title="XSS",
                        evidence_refs=["run-1/batch-1/step-3"])
        assert len(f.evidence_refs) == 1


class TestGOSTActHeader:
    def test_minimal(self):
        h = GOSTActHeader(project_name="Тестовый проект")
        assert h.organization == "Центральный Банк РФ"


class TestGOSTActObject:
    def test_minimal(self):
        o = GOSTActObject(name="Example App", url="https://example.com")
        assert o.name == "Example App"


class TestGOSTAct:
    def test_empty_act(self):
        act = GOSTAct(
            header=GOSTActHeader(project_name="Test"),
            object=GOSTActObject(name="App"),
        )
        assert act.header.project_name == "Test"
        assert len(act.findings_table) == 0

    def test_with_findings(self):
        act = GOSTAct(
            header=GOSTActHeader(project_name="Proj"),
            object=GOSTActObject(name="App"),
            findings_table=[
                GOSTFinding(severity="Critical", title="SQLi", cwe="CWE-89"),
                GOSTFinding(severity="Medium", title="Info leak", cwe="CWE-200"),
            ],
        )
        assert len(act.findings_table) == 2

    def test_with_signatures(self):
        act = GOSTAct(
            header=GOSTActHeader(project_name="Proj"),
            object=GOSTActObject(name="App"),
            signatures=[
                GOSTSignature(role="Руководитель", name="Петров П.П.", date="2026-08-27"),
                GOSTSignature(role="Эксперт", name="Сидоров С.С.", date="2026-08-28"),
            ],
        )
        assert len(act.signatures) == 2