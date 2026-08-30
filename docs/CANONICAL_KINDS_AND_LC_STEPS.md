# 🏛️ Справочник 16 типов приложений и 8 канонических шагов ЖЦ (Cosmoport 2.0)

> **Статус:** Канонический справочник сущностей и конвейеров (Чистая модель).  
> **Основа:** Выжимка реальных инструментов Cosmoport 2.0. Вырезаны проприетарные PTAI, Solar, Sandbox и весь DAST-блок (вынесен в PrettyK SecOps Lab).

---

## 1. Каталог 16 типов приложений (Project Kinds)

```text
                                КИТС (Домен / Капсула)
                                          │
        ┌─────────────────────────────────┼─────────────────────────────────┐
        ▼                                 ▼                                 ▼
   УРОВЕНЬ 0                         УРОВЕНЬ 1                         УРОВЕНЬ 2
(Библиотеки/Шаблоны)                 (Приложения)                    (Контейнеры)
  • library                         • universal_app (Линкор)          • meta_project (Вселенная)
  • report_templates                • ppod (Крейсер)
  • configuration_templates         • service_subsystem (СПС)
  • universal_lib (Карго)           • service (Гиперпривод)
  • data_transfer_lib (Буксир)      • ehd (Гиперион)
                                    • legacy (Реликт)
                                    • pis (Навигатор)
                                    • epvv_po (Харвестер ПО)
                                    • epvv_spo (Харвестер Инфра)
                                    • allocated (Выделенное)
```

---

## 2. Канонические 8 шагов ЖЦ (Clean Lifecycle Engine)

Жизненный цикл сборки, статического анализа и деплоя состоит строго из **8 реальных шагов** в 2 понятных секциях:

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        COSMOPORT 2.0 CLEAN LIFECYCLE ENGINE                            │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 1. СЕКЦИЯ: СБОРКА И СТАТИЧЕСКИЙ АНАЛИЗ (7 шагов)                                       │
│    • 1.1. Сборка ПО                      [ Обязательный / TERMINATE_ON_ERROR ]          │
│    • 1.2. Юнит-тестирование              [ Опциональный / CONTINUE ]                   │
│    • 1.3. Генерация документации         [ Опциональный / CONTINUE ]                   │
│    • 1.4. SonarQube (SAST & Quality)     [ Опциональный / TERMINATE_ON_ERROR ]          │
│    • 1.5. Trivy (SCA & Container Scan)   [ Опциональный / CONTINUE ]                   │
│    • 1.6. CodeScoring (SCA & Licenses)   [ Опциональный / CONTINUE ]                   │
│    • 1.7. Kaspersky Container Security  [ Опциональный / TERMINATE_ON_ERROR ]          │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 2. СЕКЦИЯ: РАЗВЁРТЫВАНИЕ (1 шаг)                                                       │
│    • 2.1. Развёртывание ПО               [ Обязательный / TERMINATE_ON_ERROR ]          │
└────────────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
       [ 🔬 Открыть в SecOps Lab (PrettyK DAST / Fuzzer / Playwright) ]
       (Глубокий динамический аудит вынесен в отдельный DAST-портал)
```

---

## 3. Матрица полей метаданных приложения (`ApplicationMetadata`)

```json
{
  "launch_priority": 100,
  "run_unit_tests": true,
  "multithreading_builds": false,
  "pseudo_builds": false,
  "auto_build": true,
  "use_vault": true,
  "data_categorization": false,
  "availability_monitoring": true,
  "app_survey_frequency": "1m",
  "run_quality_analysis": true,
  "run_security_analysis": true,
  "transfer_type": "sod",
  "transfer_source_code": false,
  "transfer_binary_files": true,
  "dbaas_execution_limit": 20.0,
  "application_deploy_time_override": 15,
  "library_content_type": null,
  "abac_realm": "DEFAULT",
  "confluence_url": "https://wiki.bank.local/spaces/PAY",
  "jira_url": "https://jira.bank.local/projects/PAY"
}
```
