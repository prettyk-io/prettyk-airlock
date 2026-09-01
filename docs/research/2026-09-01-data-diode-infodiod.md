# Data Diode / InfoDiod — принцип однонаправленного шлюза

> **Статус:** research overview
> **Дата:** 1 сентября 2026
> **Контекст:** gap-barrier между зонами, СОД, PureK multi-plane transfer
> **Источники:** Wikipedia (EN + RU), открытые материалы

---

## 1. Что такое data diode (однонаправленная сеть)

**Однонаправленная сеть** (unidirectional network, data diode, диод данных) —
сетевое устройство или комбинация аппаратного и программного обеспечения,
которая позволяет данным перемещаться **физически только в одном направлении**.
Передача в обратную сторону невозможна на уровне физики — не на уровне firewall
rules или ACL.

Базовая аналогия из электроники: диод пропускает ток только в одном направлении.
Data diode работает по тому же принципу на уровне сетевых пакетов и данных.

### Простейшая конструкция

```text
Source machine                 Target machine
    TX ──────────────────────────→ RX
    RX ←──────────/ /──────────── TX  (физически отключён или отсутствует)
```

В оптическом варианте: волоконно-оптический кабель (оптопара/оптрон), в котором
приёмопередатчик для обратного направления физически удалён, отключён или не
установлен. Любые механизмы защиты от сбоев линии (link failure protection)
должны быть отключены, чтобы устройство не пыталось установить обратную связь.

---

## 2. Два вида: data diode и unidirectional gateway

Современные реализации делятся на два типа:

### 2.1. Data diode (диод данных)

Сетевое устройство, позволяющее передавать **только необработанные данные** в
одном направлении. Используется для гарантирования информационной безопасности
и защиты критических систем (ICS/SCADA, АСУ ТП) от входящих кибератак.

```text
Source  → [data diode] → Target
         только raw bytes
```

### 2.2. Unidirectional gateway (однонаправленный шлюз)

Комбинация аппаратного и программного обеспечения:

```text
Source network              Target network
    ┌──────────┐              ┌──────────┐
    │  proxy   │              │  proxy   │
    │  server  │───[diode]───→│  server  │
    └──────────┘              └──────────┘
```

Аппаратное обеспечение обеспечивает физическую однонаправленность. Программное
обеспечение:

- реплицирует базы данных;
- эмулирует протокольные серверы для обработки двунаправленных протоколов;
- способно передавать несколько протоколов и типов данных одновременно;
- включает: secure boot, certificate management, data integrity (FEC), TLS,
  детерминированную доставку в предопределённые точки назначения.

Ключевая особенность: **protocol break** — данные принимаются proxy на source
стороне, затем проходят через diode как raw stream, и восстанавливаются proxy
на target стороне. Исходный двунаправленный протокол (например TCP с его
SYN/SYN-ACK/ACK handshake) разрывается и не пересекает границу физически.

---

## 3. Принцип работы и гарантии

### 3.1. Физическая гарантия

Главное свойство: **однонаправленность гарантирована физически**, а не правилами
межсетевого экрана. Даже если обе стороны (source и target) скомпрометированы,
физическая однонаправленность сохраняется.

Зарегистрированных случаев обхода или взлома data diode для установки
двустороннего трафика **не зафиксировано**.

### 3.2. Проблема ACK

Настоящий data diode **не может вернуть ACK по тому же data path**.

```text
A ──[diode]──→ B   OK
B ──[diode]──→ A   физически невозможно
```

Для обратной связи возможны варианты:

- **Отдельный разрешённый control/ACK канал** — физически другой кабель, другой
  diode или разрешённый bidirectional канал с противоположным направлением;
- **Operator ACK** — человек-оператор на target стороне подтверждает получение;
- **Controlled bidirectional gateway/session** — если используется не строгий
  diode, а управляемый gateway с session lease, TTL, direction policy и лимитами.

Важно различать:

```text
Data diode (strict one-way)
  ≠ Controlled bidirectional gateway (A ↔ B с session policy)
```

### 3.3. Две классические модели применения

**Модель 1: One-way flow to MORE secure systems (классическая)**

```text
Low side (Internet/менее защищённая сеть)
    ──[diode]──→
High side (classified/критическая сеть)
```

Данные поступают в защищённую сеть, но ничто не может покинуть её через этот
канал. Защищает от утечек. Применение: оборона, государственные системы,
[модель Белла-Лападулы](https://ru.wikipedia.org/wiki/Модель_Белла_—_Лападулы)
(«нет чтения вверх», «нет записи вниз»).

**Модель 2: One-way flow to LESS secure systems**

```text
High side (критическая система, АСУ ТП)
    ──[diode]──→
Low side (мониторинг, Internet)
```

Данные о состоянии системы публикуются наружу для мониторинга, но атака извне
не может проникнуть в критическую систему. Применение: АЭС, энергосети, дамбы,
железные дороги, банковские системы.

---

## 4. Российские производители

Из русской Википедии и открытых источников:

| Производитель | Страна | Продукт/сайт |
|---|---|---|
| **InfoDiode** | Россия | `infodiode.ru` (официальный сайт не ответил при проверке) |
| **Цифровые решения** | Россия | — |
| **Инконтрол** | Россия | `security.inctrl.ru/post_diode.html` |

Все три включены в список производителей однонаправленных сетей в русской
Википедии. InfoDiode — это, судя по названию, прямой российский аналог/бренд
data diode. Вероятно, именно он или его аналоги используются в банковских
gap-решениях (включая контур СОД).

Международные производители (для контекста):

- Siemens (Германия) — промышленный data diode до SIL4;
- Waterfall (Израиль) — unidirectional gateway для ICS;
- OWL Cyber Defense (США);
- BAE Systems (США/Великобритания);
- INFODAS (Германия) — программные («логические») data diode на микроядре;
- GENUA (Германия);
- ST Engineering (Сингапур) — multi-diode secure e-Application Gateway;
- Fox-IT (Нидерланды).

---

## 5. Что это означает для СОД и PureK transfer

### 5.1. Data diode как «дырка» в airgap

Фраза «они именно им дырку делают» теперь расшифровывается так:

```text
Airgap-сеть А (ЗР)
    │
    │  нет прямого сетевого соединения
    │
    ├── [approved staging/spool]
    │
    ▼
[InfoDiod / data diode]  ← однонаправленный физический канал
    │
    ▼
    ├── [approved staging/spool]
    │
Airgap-сеть Б (ЗТ)
```

Это не «дырка» в смысле firewall hole или NAT. Это **контролируемый физический
однонаправленный перенос**, часто с участием:

- source-side staging (spool);
- diode/gateway;
- target-side staging (spool);
- operator approval или отдельный control channel;
- session lease, TTL, byte limits.

### 5.2. Проблема ACK для PureK

Для нашего transfer framework это критически важно:

```text
Data diode (strict)
  → ACK не может вернуться по тому же каналу
  → нужен отдельный control channel или operator ACK

Controlled bidirectional gateway
  → A ↔ B с session policy
  → ACK возможен
  → но это другая security model
```

СОД, скорее всего, использует **controlled gateway/session**, а не строгий
diode. Но без фактической схемы утверждать нельзя.

### 5.3. Protocol break и наш TransferItem

Data diode / unidirectional gateway имеет **protocol break**: исходный протокол
не проходит напрямую. Данные принимаются proxy на source, проходят diode как
raw stream, восстанавливаются proxy на target.

Для PureK это означает:

- нельзя просто сделать `POST /api/transfer` через diode — нужен адаптер,
  который умеет работать с семантикой «отправил и забыл» или с отдельным
  статусным каналом;
- `TransferItem` должен иметь статусы, не требующие немедленного ACK:
  `staged → sent → (ждём подтверждения по другому каналу) → received → verified`;
- retry/recovery не может полагаться на target ACK в том же соединении;
- package idempotency и checksum становятся критически важными: target должен
  мочь проверить, что получил неповреждённый package, даже если source не
  получил немедленного подтверждения.

### 5.4. Что спросить у DevOps по факту

1. Какой именно тип устройства используется: строгий data diode или controlled
   bidirectional gateway?
2. Если diode: есть ли отдельный control/ACK канал для обратной связи?
3. Кто производитель: InfoDiode, Цифровые решения, Инконтрол или другой?
4. Как устроен protocol: TCP/UDP/raw stream? Какая throughput и latency?
5. Кто управляет session: СОД, отдельный relay или сам diode?
6. Есть ли staging/spool с обеих сторон? Где живут временные файлы?
7. Есть ли byte/size/session TTL limits?
8. Кто инициирует transfer: source push или target pull?
9. Как происходит operator approval / контроль?
10. Есть ли связь diode с Kafka в СОД (Kafka как event bus для
    отправки/получения уведомлений о transfer events)?

---

## 6. PureK implications для нашего transfer model

### 6.1. Transfer Option D теперь конкретнее

В наших `TRANSFER-OPTIONS.md` Option D описан абстрактно. Теперь:

```text
Option D — one-way data diode / unidirectional relay

Source staging
  → diode-adapted sender
  → physical one-way channel (InfoDiod / аналоги)
  → diode-adapted receiver
  → target staging
  → target-side checkup/import

ACK path:
  - отдельный разрешённый control channel; или
  - operator ACK; или
  - polling target status через разрешённый обратный канал

Не пытаться открыть bidirectional hole из PureK application code.
```

### 6.2. DiodeAdapter contract

Появился конкретный контракт для адаптера:

```text
DiodeAdapter
  → send(package, session_lease) → sent_event
  → track_status(transfer_id) → staged|sent|received|verified|failed
  → verify_on_target(package) → integrity_check_result
  → no_expect_immediate_ack() — дизайн без ожидания TCP ACK
```

### 6.3. Что не меняется

- PureK package contract (manifest, checksum, revision identity);
- PreTransferValidator;
- TargetCheckup;
- idempotency;
- audit;
- multi-plane separation (metadata ≠ OCI ≠ source ≠ packages).

Меняется только transport adapter: вместо HTTP request/response — адаптер под
однонаправленную физическую передачу с внешним статусным каналом.

---

## 7. Вывод

**Data diode / InfoDiod — это не магия и не «просто firewall rule».**
Это физически enforced однонаправленный канал передачи данных.

Для банковского gap-barrier это означает:

- пакет может уйти в одном направлении;
- подтверждение должно прийти другим путём;
- протокол разрывается — нужен адаптер, который это понимает;
- нельзя полагаться на request/response семантику;
- idempotency, checksum и correlation ID становятся единственным способом
  понять, что package доехал целым.

Для PureK это дополнительный transport option, не замена нашему package
contract. Наш design уже заложил разделение metadata envelope и artifact planes,
а также явное различие между delivery, import, verification и bootstrap. Data
diode только подтверждает, что это разделение было правильным.