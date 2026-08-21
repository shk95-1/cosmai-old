# Roadmap Candidates Register

- 문서 지위: 활성 프로젝트 registry — **필수 구현이 아닌 기능 후보의 등록부**
- 적용 범위: P1 재구축 이후 기능 후보
- 최종 수정일: 2026-08-21

## 이 문서가 하는 일과 `service-register.md`와의 역할 구분

`[결정]` 이 문서는 **필수 구현이 아닌 기능 후보**의 등록부다. 여기 실린 항목은 P1 Entry
Gate가 요구하는 경로에 들어 있지 않으며, 항목이 여기 있다는 사실은 "지금은 만들지 않는다"는
결정이 기록되어 있다는 뜻이지 "언젠가 반드시 만든다"는 약속이 아니다.

`[확인 사실]` [`docs/service-register.md`](service-register.md)는 **서비스·애드온 후보**의
등록부다 — 무엇을 입력으로 먹고, 무엇을 출력하고, 어떤 애드온 kind이며, 어떤 계약 변경과
Open Question이 막고 있는지를 다룬다. `[결정]` 이 문서는 그 역할을 나누지 않는다. 여기
실리는 것은 **기능 후보**다 — 화면, 판단 로직, 잡 트리거처럼 새 애드온 kind나 계약 변경을
반드시 요구하지는 않는, P1의 필수 경로 밖에 있는 것들. 하나의 후보가 애드온 kind와 계약
변경까지 필요로 하는 크기로 자라면 그 시점에 `service-register.md`로 옮겨 적는다 — 이
문서에 계속 두어 두 등록부가 같은 항목에 대해 다른 말을 하게 두지 않는다.

`[결정]` GitHub issue로의 전환은 개별 항목마다 산발적으로 하지 않고 **M7 정합성 점검에서
일괄 수행**한다. 그 전까지 이 표가 유일한 기록이다.

## 등록부

| id | 항목 | 출처 | 비고 |
|---|---|---|---|
| `RC-001` | 카드·트렌드 화면 | 능력 지도 §5.3, [재구축 설계 스펙](superpowers/specs/2026-08-21-p1-reconstruction-design.md) §2.5 표의 5.3행, [DP-026](decisions/DP-026-p0-closure-scope-and-collector-topology.md) D1 | DP-026 D1이 DP-011의 product scope를 P1 첫 마일스톤으로 옮긴 결정의 착지점. |
| `RC-002` | 선크림·토너 기회 카드 | 능력 지도 §6.1, [재구축 설계 스펙](superpowers/specs/2026-08-21-p1-reconstruction-design.md) §2.6 표의 6.1행 | plan.md: 기능 후보로 등록, 필수 구현요구사항 아님. |
| `RC-003` | 결정적 트렌드 분류 | 능력 지도 §6.3, [재구축 설계 스펙](superpowers/specs/2026-08-21-p1-reconstruction-design.md) §2.6 표의 6.3행 | 가능한 서비스 기능으로 마일스톤에 기록. |
| `RC-004` | 성분 완전성 판단 | 능력 지도 §6.4, [재구축 설계 스펙](superpowers/specs/2026-08-21-p1-reconstruction-design.md) §2.6 표의 6.4행 | 서비스 구현에서 판단할 내용으로 마일스톤에 기록. |
| `RC-005` | 새 `record_type` 설계: trend-radar rank/review 계열, youtube video 계열 | [DP-030](decisions/DP-030-p1-normalization-scope.md) D4 | DP-030 D4가 Schema 0.3(봉투 + `record_type` 유니온)은 승계하되 새 `record_type`은 이 등록부에 올리도록 정한 결정의 착지점. |
| `RC-006` | tubedepth 잡 생성 트리거 (수집이 읽기 전용을 넘어 수집 요청까지) | [DP-012](decisions/DP-012-independent-scraper-services.md), [DP-031](decisions/DP-031-p1-collector-topology.md) D4 | DP-012의 읽기 경계를 넓히는 후보 — 지금은 COSMAI가 tubedepth의 기존 export를 읽기만 한다. |
| `RC-007` | 대시보드 인증 | [`p0-security.md`](conventions/p0-security.md) Local execution boundary | loopback 밖 노출을 만들기 전 반드시 있어야 하는 전제조건. |

`[확인 사실]` **2026-08-21, 오너 지시로 7건 전부 GitHub issue로 등록됨**: `RC-001`→[#5](https://github.com/slopindustries/cosmai/issues/5), `RC-002`→[#6](https://github.com/slopindustries/cosmai/issues/6), `RC-003`→[#7](https://github.com/slopindustries/cosmai/issues/7), `RC-004`→[#8](https://github.com/slopindustries/cosmai/issues/8), `RC-005`→[#9](https://github.com/slopindustries/cosmai/issues/9), `RC-006`→[#10](https://github.com/slopindustries/cosmai/issues/10), `RC-007`→[#11](https://github.com/slopindustries/cosmai/issues/11). 이 표가 여전히 정본이고, issue는 추적 표면이다.

## 항목별 상세

### `RC-001` — 카드·트렌드 화면

`[확인 사실]` DP-026 D1은 "DP-011's product scope — opportunity card, sunscreen and toner
canonicalization, deterministic trend classes — and its 2026-08-26 freeze move to **P1's
first milestone**"라고 기록한다. `RC-001`은 그 문장이 가리키는 실제 화면 산출물을 여기
등록부에 이름 붙여 둔 것이다 — 결정은 DP-026에 있고, 후보 자체는 여기 있다.

### `RC-002` — 선크림·토너 기회 카드

`[확인 사실]` `plan.md` §6.1은 이 항목을 "이슈 중 가능한 기능 후보로 표현하여 등록. 필수
구현요구사항 아님"이라고 적는다. `[추론]` 이 후보가 실제로 착수될 때는
[DP-027](decisions/DP-027-dataset-standard-and-share-alike.md) D2의 조건이 여전히 유효하다는
점을 함께 봐야 한다 — Open Beauty Facts는 한국 선크림·토너 행을 0개 반환했고, D2는 "P0 gains
no product-relevant evidence from this source"라고 기록했다. `RC-002`의 착수는 이 카드가
실제로 근거할 제품 데이터가 별도로 필요하다는 뜻이며, 그 공백은 이 항목이 아니라 소스 선택
문제다.

### `RC-003` — 결정적 트렌드 분류

`[확인 사실]` `plan.md` §6.3은 "마일스톤으로 기록. 가능한 서비스 기능으로"라고 적는다. 이
항목은 P0의 결정론적 요구사항(트렌드 분석기의 P0 구현 경계, `service-register.md` 5번 후보)과
구별된다 — P0는 폐기형 evaluator로 측정하는 것이 경계이고, `RC-003`은 그 위에 세워질 서비스
기능이다.

### `RC-004` — 성분 완전성 판단

`[확인 사실]` `plan.md` §6.4는 "서비스 구현에서 판단할 내용. 마일스톤으로 기록"이라고 적는다.
`[확인 사실]` DP-027 D2는 "Ingredient completeness is 26.5% database-wide. No threshold exists
in this repository to judge that against"를 조건으로 남겼다. `RC-004`가 실제로 판단 로직을
가지려면 이 임계값 공백(`SRC-003`의 열린 질문 1)이 먼저 닫혀야 한다 — 이 항목은 그 공백을
대신 닫지 않는다.

### `RC-005` — 새 `record_type` 설계

`[확인 사실]` **정정, 2026-08-21 (`REVIEW-GATE-M0` F10 수리).** DP-030 D4는 영어로 다음과 같이
기록한다 — "New `record_type`s are registered as roadmap candidates (`RC-005`, covering the
trend-radar rank/review family and the YouTube video family) rather than committed as contract
work in this packet." `RC-005`가 그 등록 지점이며, 이 문서가 그 등록부다. `[확인 사실]` 이전
버전은 이 문장을 한국어 인용부호 안에 "(Task 9)"를 포함해 옮겼는데, DP-030 원문(영어)에는
"Task 9"라는 표현이 없다 — 발명된 인용이었다. `[확인 사실]` DP-031 D3가
확정한 어댑터 대상은 trend-radar 1.0.0과 tubedepth 두 종이며, `RC-005`의 두 계열(rank/review,
youtube video)은 이 두 어댑터가 실제로 수집을 시작할 때 필요해질 레코드 모양이다. `[추론]`
유니온 멤버 수 증가의 반증 조건(멤버 수가 소스 수에 근접)은 DP-030이 유지한 채이므로,
`RC-005`를 채택할 때는 그 반증 조건도 함께 다시 확인해야 한다.

### `RC-006` — tubedepth 잡 생성 트리거

`[추론]` **정정, 2026-08-21 (`REVIEW-GATE-M0` F10 수리).** DP-012는 영어 문서이므로 아래는
직접 인용이 아니라 D1의 요약이다: 어댑터 경계는 스크래퍼 코드·스케줄·1차 저장소를 외부
서비스가 소유하고, 어댑터는 서비스 DB를 읽거나 스크래퍼 모듈을 import하지 않는 것으로 정해져
있다. `[확인 사실]` DP-031 D4는 "Data exchange with either adapter target is REST-API-only...
Collection scheduling is COSMAI's own: the P1 scheduler... creates a collect job on its own
interval, and that job reads whatever the external service's REST export currently holds"라고
정하는데(이전 버전은 이 부분을 한국어 인용부호와 말줄임표로 옮겼으나 DP-031 원문에는 그
한국어 문자열이 없었다), 이것은 COSMAI가 **자기 쪽** 수집 잡을 스케줄대로
생성해 tubedepth의 기존 export를 **읽는** 일이다. `[추론]` tubedepth 자신에게 "지금 새로
수집하라"는 요청을 보내는 것은 다른 방향의 쓰기이며, DP-012의 읽기 경계를 넓히는 결정이 별도로
필요하다. `RC-006`은 그 넓힘을 아직 채택하지 않은 채 후보로만 적어 둔다.

### `RC-007` — 대시보드 인증

`[확인 사실]` `p0-security.md`의 Local execution boundary는 "API와 Dashboard는 기본적으로
loopback interface에만 bind한다... 별도 Decision Packet 없이 public ingress, shared staging
또는 internet-facing deployment를 만들지 않는다"라고 정한다. `[확인 사실]` DP-033 D1이 정한
여섯 화면 중 어느 것도 인증을 다루지 않는다. `[추론]` 따라서 `RC-007`은 새 화면이 아니라
**전제조건**이다 — loopback 밖으로 대시보드를 노출하는 어떤 결정도 `RC-007`이 채택되기
전에는 이루어질 수 없다.

## 후보를 추가할 때

각 항목에 다음을 적는다.

- 어떤 능력 지도 절, `plan.md` 절, 또는 결정에서 나왔는가 — `[확인 사실]` `plan.md`는
  저장소에 커밋되지 않은 오너의 원본 메모다. 그 내용은 [재구축 설계
  스펙](superpowers/specs/2026-08-21-p1-reconstruction-design.md) §2에 재현되어 있고, 커밋된
  권위 있는 출처는 스펙 쪽이다. `plan.md` 절을 인용할 때는 가능하면 스펙의 대응 표·행도 함께
  적는다.
- 이 후보를 막고 있는 것이 있는가 (데이터 공백, 임계값 부재, 다른 결정의 선행 등)
- `docs/service-register.md`로 옮겨야 할 만큼 애드온 kind나 계약 변경이 필요해졌는가
- M7 정합성 점검에서 GitHub issue로 옮길 때 필요한 최소 정보(제목, 근거 링크)가 이미
  있는가
