# P0 Security Baseline

- 문서 지위: `ACCEPTED_FOR_POC` safety constraint
- 적용 범위: P0-A platform core와 P0-B source probe 및 domain integration
- 최종 수정일: 2026-08-17

P1 scope amendment: dashboard write-only credential entry and the security disposition are decided in [DP-034](../decisions/DP-034-p1-credential-entry.md).

P1 scope amendment (2026-08-21): fleet egress and the container bind are decided in [DP-035](../decisions/DP-035-fleet-egress-and-container-bind.md) — the two clauses it amends are annotated in place below.

## 목적과 경계

P0가 폐기형 prototype이라는 사실은 실제 credential, 외부 네트워크, dataset과 debug data를 안전하지 않게 다룰 이유가 되지 않는다. 이 문서는 production IAM 또는 secret-management 제품을 선택하지 않고도 지켜야 하는 최소 불변조건을 정의한다.

## Local execution boundary

- API와 Dashboard는 기본적으로 loopback interface에만 bind한다.
  - `[결정]` [DP-035](../decisions/DP-035-fleet-egress-and-container-bind.md) D2 (2026-08-21):
    API의 process bind는 `COSMA_API_BIND_SCOPE=container`라는 명시적 opt-in 아래에서만
    unspecified address를 허용한다. 기본값은 여전히 loopback 전용이고 폴백은 없다. 이때
    노출 경계는 process bind에서 compose 포트 매핑으로 이동하며, 호스트 쪽 표면은
    loopback 전용으로 유지된다(`127.0.0.1` 포트 매핑). 컨테이너 네트워크(`db-net`) 안의
    다른 fleet 컨테이너가 API에 도달 가능해지는 것은 DP-035 D2가 기록한 의도된 변화다.
- 별도 Decision Packet 없이 public ingress, shared staging 또는 internet-facing deployment를 만들지 않는다.
- 인증이 없는 P0 UI는 local operator boundary 밖에서 사용할 수 있다고 가정하지 않는다.
- local boundary를 넘어야 하는 실험은 먼저 threat, identity, authorization과 data exposure를 별도 질문으로 기록한다.

## Outbound source policy

This section applies only to P0-B. P0-A must not register a source, create an outbound source policy, or issue a source request.

- Dashboard와 job payload는 임의 URL이 아니라 등록된 `source_id`를 선택한다.
- Source profile에는 허용 HTTPS scheme, hostname, port와 endpoint path 범위를 기록한다.
- HTTP redirect가 발생하면 destination을 같은 정책으로 다시 검증한다.
- DNS resolution 결과가 loopback, private, link-local, multicast 또는 허용되지 않은 address range이면 차단한다.
  - `[결정]` 이 규칙의 per-source 구멍은 정확히 두 개다: `allow_loopback`(loopback만),
    그리고 [DP-035](../decisions/DP-035-fleet-egress-and-container-bind.md) D1의
    `allow_fleet`(private만, fleet 컨테이너 대상). 두 플래그는 직교하고, 둘 다 켜져도
    link-local(169.254.169.254 포함)·multicast·reserved·unspecified는 계속 차단된다.
    두 플래그 모두 운영자가 source row에 승인해야 하며 커밋된 기본값이 될 수 없다.
- connect/read timeout, maximum redirects, response body size와 page/record limit을 source별로 둔다.
- Network error와 HTTP response를 기록할 때 Authorization, Cookie와 provider-protected header를 제거한다.

P0에서는 범용 URL fetcher를 만들지 않는다. 선택된 source의 bounded behavior를 검증하는 것이 목적이다.

[DP-008](../decisions/DP-008-addon-architecture.md) 이후 이 절의 모든 의무는 애드온이 아니라 플랫폼이 진다.

- 플랫폼이 제공하는 `fetch(endpoint_ref, params)`가 **유일한 outbound 경로**다. 애드온은 URL을 조립하지 않고 endpoint 이름만 지정한다.
- 실제 URL은 등록된 source row의 `outbound_profile`에서 플랫폼이 만든다. Manifest의 `[declares]`는 요구이지 허가가 아니며, 운영자 승인을 거쳐 source row에 들어가야 권한이 된다.
- 애드온은 credential을 받지 않는다. 플랫폼이 요청 시점에 해석해 붙이고, 응답에서 보호 헤더를 제거한 뒤 돌려준다.
- `fetch`는 endpoint_ref를 받으므로 임의 URL을 받을 수 있는 형태가 아니다. 이 절의 첫 문장은 그대로 유효하다.

## Add-on trust boundary

[DP-008](../decisions/DP-008-addon-architecture.md)의 애드온은 **같은 프로세스 안에서 실행되는 신뢰된 코드**다. 이 사실을 명시적으로 기록해 두는 이유는, 계약이 격리처럼 보이기 때문이다.

- `[확인 사실]` 인프로세스 애드온이 database driver를 직접 import해 DB에 접속하는 것을 막는 장치는 없다.
- `[결정]` 이 설계가 막는 것은 **사고에 의한** 결합과 **사고에 의한** credential 노출이다. 적대적인 애드온은 막지 못한다.
- `[결정]` 애드온이 저장소 안에 있고 리뷰를 거친다는 전제 위에서 P0는 이 자세를 수용한다. 리뷰 경계 밖의 애드온을 받아들이는 순간 이 전제는 깨진다.
- `[결정]` 계약의 입출력은 직렬화 가능한 형태로만 작성한다. 서브프로세스 격리로 옮겨야 할 때 계약이 아니라 host만 바뀌도록 남겨 두는 것이 이 제약의 목적이다.
- `[확인 사실]` 의존 방향은 테스트로 강제한다. 애드온은 `addon_api`만 import할 수 있고, `platform_core`는 애드온 계층을 import하지 않는다.

## Agent sandbox baseline

Agent 실행 샌드박스는 application의 outbound source policy와 **독립적인 두 번째 강제 지점**이다. Application 쪽 검증에 결함이 있어도 샌드박스가 egress를 막는다.

P0-A 현재 상태는 의도적으로 넓게 열려 있다. P0-A는 source를 탐색하거나 outbound source request를 실행하지 않는다.

- `[결정]` P0-A 한정으로 `sandbox.network.allowedDomains: ["*"]`와 `sandbox.autoAllowBashIfSandboxed: true`를 유지할 수 있다. 근거: P0-A는 source와 real credential을 다루지 않고 개발 의존성 설치와 도구 실행 편의가 우선한다.
- `[확인 사실]` 이 조합은 프롬프트 없는 임의 외부 요청을 허용한다. 문서만 있는 레포에서만 성립하는 트레이드오프다.

**P0-B 진입 시 반드시 조정한다.** 첫 source probe가 실제 outbound 요청을 만들기 전에 다음을 수행한다.

- `allowedDomains`를 등록된 source profile의 host와 필요한 package registry로 좁힌다.
- 정책상 접근 금지 대상은 `deniedDomains`에 명시한다. `deniedDomains`는 모든 설정 소스에서 병합되며 `allowedDomains`보다 우선한다.
- `autoAllowBashIfSandboxed`를 유지할지 재검토한다. Source와 credential을 다루는 P0-B에서는 P0-A의 근거가 더 이상 성립하지 않는다.
- 조정 결과를 첫 source probe experiment record의 Environment에 남긴다.

## Credential handling

P0-A implements only the repository-external secret-store location guard, redaction, protected-debug behavior, and explicit configuration failure. Source credentials, `credential_ref` authorization, and credential resolution belong to P0-B.

- Code, committed config, database, job payload, Raw header, fixture, log, screenshot에 secret 원문을 저장하지 않는다.
- P0-B Source와 domain job에는 opaque `credential_ref`만 저장한다.
- P0-B Worker가 사용 시점에 승인된 local secret source에서 reference를 해석하고, 값을 요청 수명 동안만 보유한다.
- Credential 값을 프로세스 환경변수로 export하지 않는다. 환경으로 펼치면 모든 자식 프로세스가 모든 credential을 상속하며, 이는 log 통제와 다른 유출 채널이다. 실행 경계에는 store 위치만 전달한다.
- Worker가 어떤 reference를 해석할 수 있어야 하는지는 [OQ-007](../open-questions/OQ-007-credential-scope.md)에서 결정한다. 그때까지 범위 제한을 확정된 것으로 다루지 않는다.
- 공개 가능한 key 이름과 형식은 `config/env.example`에 기록한다.
- 실제 credential 값은 repository working tree 밖의 승인된 local secret source에만 둔다. 기본 위치는 `~/.config/cosmai/`이며 다른 위치를 쓰려면 실험 기록이나 Decision Packet에 남긴다.
- Working tree 안에는 `.env`를 포함해 어떤 secret 파일도 만들지 않는다. `.gitignore`와 agent permission deny 규칙은 안전망이지 유일한 방어선이 아니다.
- 적용 절차는 [Secret Setup](secret-setup.md)에 있다.
- Credential이 없거나 해석되지 않으면 명시적인 non-retryable configuration failure로 종료한다. 빈 값이나 fallback credential로 계속하지 않는다.

## Logs and debug evidence

- Structured log에는 correlation identifiers와 분류된 error만 기록한다.
- Header와 payload를 통째로 log하지 않는다.
- Debug detail은 allowlisted field 또는 redacted summary로 만든다.
- Redaction 실패 가능성이 있는 output은 `private`로 분류하며 에이전트나 Git evidence에 사용하지 않는다.
- Dashboard screenshot과 exported trace도 같은 data classification을 적용한다.

## Dataset and personal data

- Dataset은 [Data Handling Convention](data-handling.md)에 따라 분류한다.
- P0 목적에 불필요한 personal data는 ingest하지 않는다.
- 예상하지 못한 sensitive field가 발견되면 해당 input 처리를 중단하고 artifact를 승격하지 않는다.
- 테스트는 synthetic 또는 허용된 최소 fixture를 우선 사용한다.

## Minimum acceptance evidence

- `SEC-001` — P0-A/P0-B: secret과 protected detail이 log, error, metadata와 screenshot에 나타나지 않는다. Raw metadata와 protected source header 검증은 P0-B에서 추가한다.
- `SEC-002` — P0-B: 등록되지 않은 source 또는 허용되지 않은 host 요청이 실행 전에 거부된다.
- `SEC-003` — P0-B: redirect와 DNS 결과가 source policy를 벗어나면 거부된다.
- `SEC-004` — P0-B: oversized/slow response가 bounded failure로 종료되고 worker를 무기한 점유하지 않는다.
- `SEC-005` — P0-A/P0-B: P0 operator surface가 기본 설정에서 loopback 밖에 노출되지 않는다.
- `SEC-006` — P0-B entry: Agent 샌드박스의 `allowedDomains`가 P0-A의 `["*"]`에서 등록된 source host와 필요한 registry로 좁혀져 있다.
  - `[결정]` **P0 범위에서 면제됨 — [DP-023](../decisions/DP-023-sec-006-waived-for-p0.md).**
    2026-08-19 기준 좁혀져 있지 않고, 수집기 셋이 이미 실제 API에 요청을 보냈다. 독립 mutation
    리뷰가 이를 blocking으로 보고했고(`ADVERSARIAL-REVIEW-2026-08-19-MUTATION.md` B1), 운영자가
    노출을 인지한 상태에서 수용했다. **미수행이 아니라 면제이며, 둘은 settings 파일에서 똑같이
    보이지만 전혀 다른 것이다.** 이 면제는 P1 Entry Gate에서 만료된다. 따라서 `SEC-006`은
    충족된 acceptance evidence 목록에 올라갈 수 없다.
  - `[측정]` 2026-08-20, DP-023이 스스로 적어 둔 반증 조건 중 하나가 실제로 관측됐다:
    application guard에서 승인 범위를 호스트 전체로 넓히는 결함이 하나 더 나왔다. 수리됐고,
    기록은 [DP-023 §면제 이후 관측](../decisions/DP-023-sec-006-waived-for-p0.md#면제-이후-관측된-것-2026-08-20)에 있다.

### ⚠️ 위 번호는 `tests/acceptance/SEC-00N`과 다른 번호 체계다

`[확인 사실]` 이 문서의 `SEC-00N`은 **요구사항 baseline**이고,
[`tests/acceptance/`](../../tests/acceptance/)의 `SEC-00N`은 **시나리오 id**다. 접두사가 같고
번호가 겹치는데 **가리키는 것이 하나도 일치하지 않는다.**
[ADVERSARIAL-REVIEW-2026-08-19-MUTATION.md](../../experiments/integrated-p0/ADVERSARIAL-REVIEW-2026-08-19-MUTATION.md)
M5가 찾았다.

| 이 문서 | 내용 | 대응하는 시나리오 |
|---|---|---|
| `SEC-001` | secret이 log·error·metadata에 나타나지 않는다 | **`SEC-004`** redaction boundary holds |
| `SEC-002` | 미등록 source·미허용 host 거부 | 없음 — P0-B `SEC` 시나리오로 추가되어야 한다 |
| `SEC-003` | redirect·DNS가 정책을 벗어나면 거부 | 없음 — 같음 |
| `SEC-004` | oversized·slow response가 bounded failure로 종료 | 없음 — 같음 |
| `SEC-005` | operator surface가 loopback 밖에 노출되지 않는다 | **`SEC-002`** operator surfaces bind to loopback |
| `SEC-006` | 샌드박스 `allowedDomains` 축소 | 없음 — [DP-023](../decisions/DP-023-sec-006-waived-for-p0.md)으로 면제 |

`[확인 사실]` 시나리오 쪽에만 있고 이 목록에 대응이 없는 것도 둘 있다:
`SEC-001`(secret store 경로 가드)과 `SEC-003`(잘못된 설정은 재시도 불가).

`[추론]` **"SEC-002가 통과했다"는 문장은 이 대조표 없이는 뜻이 정해지지 않는다.** 둘 중 어느
체계인지에 따라 전혀 다른 주장이 된다. 번호를 다시 매기지 않고 대조표를 두는 쪽을 골랐는데,
개명은 두 방향의 기존 링크를 모두 깨뜨리고 이 혼동은 링크가 아니라 **인용**에서 생기기
때문이다. Architecture Synthesis는 이 표를 거쳐 인용해야 한다.

## Non-goals

- Production identity provider 선택
- Vault/KMS 제품 선택
- Multi-tenant authorization
- Internet-facing deployment hardening
- 조직 전체 보안 또는 compliance 인증
