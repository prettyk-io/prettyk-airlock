"""COS-005: Тесты ГОСТ-Акт renderer."""
import pytest
from cosmo.ledger import (
    GOSTAct, GOSTActHeader, GOSTActObject, GOSTFinding, GOSTSignature,
)
from cosmo.ledger.gost_renderer import render_gost_act_html


@pytest.fixture
def sample_act() -> GOSTAct:
    return GOSTAct(
        header=GOSTActHeader(
            act_number="PK-2026-001",
            project_name="Тестовое приложение",
        ),
        object=GOSTActObject(
            name="TestApp v2.1",
            url="https://test.example.com",
            domain="example.com",
        ),
        findings_table=[
            GOSTFinding(severity="Critical", title="SQLi", cwe="CWE-89",
                        description="SQL-инъекция в поле login",
                        recommendation="Использовать параметризованные запросы"),
            GOSTFinding(severity="Medium", title="XSS",
                        description="Reflected XSS в search", cwe="CWE-79"),
        ],
        signatures=[
            GOSTSignature(role="Руководитель", name="Иванов", date="2026-08-27"),
        ],
    )


class TestRenderGOSTAct:
    def test_renders_html(self, sample_act: GOSTAct):
        html = render_gost_act_html(sample_act)
        assert "<!DOCTYPE html>" in html
        assert "<html lang=\"ru\">" in html

    def test_contains_project_name(self, sample_act: GOSTAct):
        html = render_gost_act_html(sample_act)
        assert "Тестовое приложение" in html

    def test_contains_findings(self, sample_act: GOSTAct):
        html = render_gost_act_html(sample_act)
        assert "SQLi" in html
        assert "CWE-89" in html
        assert "XSS" in html
        assert "CWE-79" in html

    def test_contains_signature(self, sample_act: GOSTAct):
        html = render_gost_act_html(sample_act)
        assert "Иванов" in html
        assert "Руководитель" in html

    def test_empty_findings(self):
        act = GOSTAct(
            header=GOSTActHeader(project_name="Empty"),
            object=GOSTActObject(name="No findings"),
            findings_table=[],
        )
        html = render_gost_act_html(act)
        assert "Находок не обнаружено" in html