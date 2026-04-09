# gen_comment 설계 보고서

> 이 문서는 프로젝트의 설계안을 누적 관리합니다.
> 각 설계안은 독립된 섹션으로 추가되며, 채택 여부와 변경 이력을 함께 기록합니다.

---

## 목차

- [설계안 #1: LLM 기반 함수 주석 자동 생성기 (v1)](#설계안-1-llm-기반-함수-주석-자동-생성기-v1)

---

## 설계안 #1: LLM 기반 함수 주석 자동 생성기 (v1)

- **작성일**: 2026-04-09
- **상태**: **구현 완료** (2026-04-09)
- **목적**: 코드 파일의 모든 함수에 LLM(Ollama)으로 RAG 검색에 최적화된 구조화 주석을 자동 생성

### 1. 배경 및 목표

코드베이스의 함수를 RAG 시스템에서 효과적으로 검색하려면, 함수 단위로 chunking했을 때 검색 쿼리와 매칭되는 풍부한 텍스트가 필요하다. 이 도구는:

- 지정된 폴더를 재귀 탐색하여 모든 코드 파일의 함수를 찾고
- 각 함수를 개별적으로 LLM에 전달하여 구조화된 주석을 생성하고
- 원본을 손상하지 않고 result/ 폴더에 주석이 포함된 사본을 출력한다

### 2. 프로젝트 구조

```
gen_comment/
├── main.py                  # CLI 진입점 (argparse)
├── config.py                # 설정 상수 및 기본값
├── models.py                # 데이터 클래스 (FunctionInfo, CommentResult)
├── llm_client.py            # OllamaClient (참조: ../dev_agent_deepAssist/llm_clients.py)
├── prompt.py                # 프롬프트 템플릿 + LLM 응답 파싱
├── parsers/
│   ├── __init__.py          # 파서 레지스트리 + get_parser() 팩토리
│   ├── base.py              # BaseParser 추상 클래스
│   ├── python_parser.py     # Python ast 기반 함수 추출
│   ├── c_parser.py          # C/C++ tree-sitter 기반 함수 추출
│   ├── java_parser.py       # Java tree-sitter 기반 함수 추출
│   └── js_parser.py         # JavaScript/TypeScript tree-sitter 기반 함수 추출
├── comment_inserter.py      # 원본 라인에 주석 삽입 (bottom-up)
├── processor.py             # 오케스트레이터: 디렉토리 순회 → 파싱 → LLM → 삽입
├── requirements.txt         # requests, tree-sitter, tree-sitter-languages
└── docs/
    └── design_report.md     # 본 문서
```

### 3. 주석 포맷 설계 (RAG 최적화)

#### 3.1 포맷 예시

**Python** (docstring):
```python
def authenticate_user(username: str, password: str) -> dict:
    """
    [Summary] 사용자 인증을 수행하고 JWT 토큰을 발행한다.

    [Args]
        username (str): 사용자 로그인 ID
        password (str): 비밀번호 평문

    [Returns]
        dict: {"token": str, "expires_at": datetime}

    [Raises]
        AuthenticationError: 비밀번호 불일치 시
        ConnectionError: DB 연결 실패 시

    [Calls] db.get_user, jwt.encode, hash_password
    [Side Effects] 로그인 시도 횟수를 DB에 기록
    [Tags] 인증, JWT, 로그인, 보안, 사용자
    """
```

**C/C++** (블록 주석, 함수 본문 첫 줄):
```c
int authenticate_user(const char* username, const char* password) {
    /*
     * [Summary] 사용자 인증을 수행하고 토큰을 반환한다.
     *
     * [Args]
     *     username (const char*): 사용자 로그인 ID
     *     password (const char*): 비밀번호 평문
     *
     * [Returns]
     *     int: 성공 시 0, 실패 시 에러 코드
     *
     * [Calls] db_get_user, verify_password, generate_token
     * [Tags] 인증, 토큰, 로그인, 보안
     */
```

**Java / JavaScript** (JSDoc 스타일, 함수 본문 첫 줄):
```java
public AuthResult authenticateUser(String username, String password) {
    /**
     * [Summary] 사용자 인증을 수행하고 JWT 토큰을 발행한다.
     *
     * [Args]
     *     username (String): 사용자 로그인 ID
     *     password (String): 비밀번호 평문
     *
     * [Returns]
     *     AuthResult: 토큰과 만료 시간을 포함하는 객체
     *
     * [Throws] AuthenticationException, ConnectionException
     * [Calls] userRepository.findByUsername, jwtUtil.encode
     * [Tags] 인증, JWT, 로그인, 보안
     */
```

#### 3.3 언어별 주석 문법 매핑

| 언어 | 주석 형식 | 삽입 위치 |
|------|-----------|-----------|
| Python | `"""..."""` docstring | 함수 본문 첫 줄 |
| C/C++ | `/* ... */` 블록 주석 | 함수 본문 `{` 다음 줄 |
| Java | `/** ... */` Javadoc 스타일 | 함수 본문 `{` 다음 줄 |
| JavaScript/TypeScript | `/** ... */` JSDoc 스타일 | 함수 본문 `{` 다음 줄 |

#### 3.2 섹션별 역할 및 RAG 기여도

| 섹션 | 역할 | RAG 기여 |
|------|------|----------|
| **[Summary]** | 함수 목적 한 줄 요약 (필수) | 검색 쿼리와 직접 매칭되는 핵심 텍스트 |
| **[Args]** | 파라미터 이름/타입/설명 | 타입 기반 검색, 파라미터명으로 관련 함수 연결 |
| **[Returns]** | 반환값 타입/설명 | "~를 반환하는 함수" 류 쿼리 매칭 |
| **[Raises]** | 발생 가능 예외 | 에러 핸들링 관련 검색 |
| **[Calls]** | 호출하는 다른 함수 목록 | 의존성 그래프 구축, 관련 함수 연쇄 검색 |
| **[Side Effects]** | 부수 효과 (DB 쓰기, 파일 I/O 등) | 영향 범위 파악 쿼리 |
| **[Tags]** | 의미 키워드 | 코드 용어와 다른 자연어 쿼리 매칭의 핵심 |

- 해당 없는 섹션은 생략 (간단한 getter에 [Side Effects]는 불필요)
- `[Tags]`는 코드에 없는 동의어/상위 개념을 포함시켜 retrieval recall을 높임

### 4. 핵심 데이터 모델

```python
@dataclass
class FunctionInfo:
    name: str                    # 함수명
    source_text: str             # 원본 소스 텍스트
    lineno: int                  # def/함수선언 키워드 라인 (1-based)
    end_lineno: int              # 함수 마지막 라인
    body_start_lineno: int | None # 함수 본문 첫 라인 (None이면 본문 없음)
    col_offset: int              # 키워드 들여쓰기
    body_indent: str             # 본문 들여쓰기 문자열
    is_method: bool              # 클래스/구조체 메서드 여부
    is_async: bool
    class_name: str | None       # 소속 클래스/구조체명
    decorators: list[str]        # 데코레이터/어노테이션 이름들
    has_existing_docstring: bool # 기존 주석 존재 여부
    language: str                # 소스 언어 ("python", "c", "java", "javascript")
    is_declaration_only: bool    # 본문 없는 선언/프로토타입 여부

@dataclass
class CommentResult:
    function_name: str
    comment_lines: list[str]     # 삽입할 주석 라인들 (들여쓰기 포함)
    insert_lineno: int           # 삽입 위치 (1-based)
    replace_end_lineno: int | None  # 기존 주석 교체 시 끝 라인
```

### 5. 함수 추출 전략

#### 5.1 Python — `ast` 모듈 (표준 라이브러리)

1. `ast.parse(source)` → AST 트리 생성
2. `ast.walk(tree)`로 모든 `FunctionDef`/`AsyncFunctionDef` 노드 탐색
3. 각 노드에서:
   - `node.lineno` ~ `node.end_lineno` 범위의 원본 라인 추출 → `source_text`
   - `node.body[0].lineno` → 본문 시작 라인 (주석 삽입 위치)
   - `node.col_offset + 4` → 본문 들여쓰기 계산
   - 부모 노드가 `ClassDef`이면 `is_method=True`, `class_name` 기록
   - `node.body[0]`이 `ast.Expr(ast.Constant(str))`이면 기존 docstring 존재

#### 5.2 C/C++, Java, JavaScript — tree-sitter

tree-sitter를 사용하여 언어에 구애받지 않는 파싱:

1. `tree_sitter.Parser()`에 언어별 grammar 로드
2. `tree.root_node`에서 재귀 탐색하여 함수 노드 추출:
   - C/C++: `function_definition`, `declaration` (프로토타입)
   - Java: `method_declaration`, `constructor_declaration`
   - JS/TS: `function_declaration`, `method_definition`, `arrow_function`
3. 각 노드의 `start_point`, `end_point`로 라인 범위 결정
4. `body` 자식 노드(compound_statement/block)의 존재 여부로 선언 vs 정의 구분

#### 5.3 언어별 파서 매핑

| 확장자 | 파서 | 파싱 엔진 |
|--------|------|-----------|
| `.py` | `PythonParser` | `ast` (표준 라이브러리) |
| `.c`, `.h`, `.cpp`, `.hpp`, `.cc` | `CParser` | tree-sitter |
| `.java` | `JavaParser` | tree-sitter |
| `.js`, `.ts`, `.jsx`, `.tsx` | `JSParser` | tree-sitter |

#### 5.4 공통 엣지 케이스

**한줄 함수**: `def foo(): return 1` → `:` 이후를 분리하여 별도 라인으로 처리

**대형 함수**: 500줄 이상 → 앞 100줄 + 뒤 50줄만 LLM에 전달 (`# ... truncated ...` 마커)

**본문 없는 함수 선언 (is_declaration_only=True)**:
- C/C++ 헤더의 함수 프로토타입: `int foo(int x);`
- C++ 순수 가상 함수: `virtual void process() = 0;`
- Java 인터페이스 메서드: `void process(String data);`
- Python 추상 메서드: `@abstractmethod def process(self): ...`

→ **처리 정책**: 기본적으로 **스킵**. `--include-declarations` 옵션 시 함수 **앞(위)** 에 시그니처 기반 간략 주석 삽입 (본문이 없으므로 `[Summary]`, `[Args]`, `[Returns]`, `[Tags]`만 생성)

### 6. 주석 삽입 전략 (Bottom-up)

파일 뒤쪽 함수부터 처리하여 라인 번호 시프트를 방지:

```
1. comments를 insert_lineno 기준 내림차순 정렬
2. 원본 라인 리스트 복사
3. 각 comment에 대해:
   a. 기존 docstring 교체 시 → replace_end_lineno까지 라인 제거 후 삽입
   b. 신규 삽입 시 → insert_lineno - 1 위치에 comment_lines 삽입
   c. 선언 전용(is_declaration_only) → 함수 선언 라인 앞에 주석 삽입
4. 수정된 라인 리스트 반환
```

#### 6.1 대형 파일 최적화 (10만줄+)

10만줄 이상의 대형 파일에서 `list.insert()` 반복은 O(n*k) 성능 저하를 유발한다. 이를 해결하기 위한 전략:

**청크 기반 쓰기 (Chunk-based Write)**:
```
1. 원본 파일을 라인 단위로 순차 읽기 (전체 메모리 적재 회피)
2. 삽입 포인트를 오름차순 정렬
3. 출력 파일에 스트리밍 쓰기:
   - 다음 삽입 포인트까지의 원본 라인을 그대로 출력
   - 삽입 포인트 도달 시 주석 라인을 출력
   - 반복하여 파일 끝까지 처리
```

이 방식은 리스트 조작 없이 O(n) 단일 패스로 처리하며, 메모리 사용량도 현재 라인 + 주석 버퍼 수준으로 제한된다.

**파일 크기별 전략 분기**:

| 파일 크기 | 전략 | 이유 |
|-----------|------|------|
| ~1만줄 | 기존 bottom-up 리스트 삽입 | 단순하고 충분히 빠름 |
| 1만줄~10만줄 | 청크 기반 쓰기 | insert() 반복 O(n*k) 회피 |
| 10만줄+ | 청크 기반 쓰기 + 진행률 표시 | 처리 시간이 길어 사용자 피드백 필요 |

**진행률 표시**: 대형 파일 처리 시 `[파일명] 처리 중... 127/342 함수 (37%)` 형태로 터미널에 진행 상황 출력

### 7. LLM 통신 설계

참조: `../dev_agent_deepAssist/llm_clients.py`의 `OllamaClient` 단순화

- `/api/chat` 엔드포인트만 사용
- `/nothink` 모드 활성화 (thinking 비활성화로 속도 향상)
- 함수당 타임아웃: 120초
- `num_ctx: 8192` (함수 단위이므로 작은 컨텍스트 충분)
- `temperature: 0.3` (일관된 주석 생성)

### 8. 프롬프트 설계

- **시스템 프롬프트**: 주석 포맷 규칙, 섹션 설명, "해당 없는 섹션 생략" 지시
- **사용자 프롬프트**: 함수 소스코드 + 파일 경로 + 클래스명 컨텍스트
- **응답 파싱**: 마크다운 코드 펜스 제거, triple-quote 래핑 제거, `[Summary]` 존재 검증

### 9. 출력 전략

```
원본: /project/src/auth/login.py
결과: /project/result/src/auth/login.py
```

- `result/` 폴더에 디렉토리 구조를 그대로 미러링
- 함수가 있는 파일만 복사 (함수 없는 파일은 건너뜀)
- 처리 완료 후 터미널에 요약 리포트 출력
- **추가 제안**: `--diff` 옵션으로 unified diff 파일 생성

### 10. CLI 인터페이스

```
python main.py <path> [options]

필수:
  path                      처리할 디렉토리 또는 파일 경로

옵션:
  -o, --output DIR          출력 디렉토리 (기본: result/)
  -m, --model NAME          Ollama 모델 (기본: qwen3:8b)
  --ollama-url URL          Ollama URL (기본: http://localhost:11434)
  --workers N               파일 내 병렬 LLM 호출 수 (기본: 3)
  --overwrite               기존 docstring/주석도 재생성
  --include-declarations    본문 없는 함수 선언에도 주석 생성
  --lang LANG               처리할 언어 제한 (예: python,c,java) 기본: 전체
  --dry-run                 함수 목록만 출력, LLM 미호출
  -v, --verbose             상세 로그 출력
```

### 11. 처리 흐름

```
CLI args
  → Processor.run()
    → 재귀 디렉토리 탐색 (pathlib.rglob)
      → 확장자별 Parser 선택
        → parser.extract_functions(file) → list[FunctionInfo]
          → 각 함수별 (ThreadPool 병렬):
            → prompt 구성 (함수 소스만 전달)
            → OllamaClient.generate_comment()
            → 응답 파싱 → CommentResult
          → comment_inserter.insert_comments(원본라인, comments)
          → result/ 폴더에 수정 파일 저장
    → 요약 리포트 출력
```

### 12. 엣지 케이스 처리

| 케이스 | 처리 방법 |
|--------|----------|
| 구문 오류 파일 | `ast.parse` SyntaxError / tree-sitter 파싱 실패 → 로그 후 스킵 |
| 비UTF-8 파일 | UnicodeDecodeError → 스킵 |
| 한줄 함수 | def 라인 분리 후 주석 삽입 |
| 중첩 함수 | ast.walk / tree-sitter가 모두 탐지, bottom-up으로 안전 삽입 |
| 빈 함수 `def f(): pass` | pass 앞에 docstring 삽입 |
| 500줄+ 대형 함수 | 앞100줄+뒤50줄만 LLM 전달 |
| 10만줄+ 대형 파일 | 청크 기반 스트리밍 쓰기 + 진행률 표시 |
| 함수 없는 파일 | 스킵 |
| 기존 docstring/주석 | 기본: 스킵 / `--overwrite` 시 교체 |
| C/C++ 함수 프로토타입 (본문 없음) | 기본: 스킵 / `--include-declarations` 시 함수 앞에 간략 주석 |
| C++ 순수 가상 함수 `= 0` | 기본: 스킵 / `--include-declarations` 시 함수 앞에 간략 주석 |
| Java 인터페이스/추상 메서드 | 기본: 스킵 / `--include-declarations` 시 함수 앞에 간략 주석 |
| Python `@abstractmethod` / `...` body | 기본: 스킵 / `--include-declarations` 시 함수 앞에 간략 주석 |
| 헤더파일 전체 (`.h`, `.hpp`) | 모든 함수가 선언뿐이면 파일 스킵 (--include-declarations 없을 시) |

### 13. 구현 순서

| 순서 | 파일 | 의존성 |
|------|------|--------|
| 1 | `models.py` | 없음 |
| 2 | `config.py` | 없음 |
| 3 | `parsers/base.py` | models |
| 4 | `parsers/python_parser.py` | models, base |
| 5 | `parsers/c_parser.py` | models, base, tree-sitter |
| 6 | `parsers/java_parser.py` | models, base, tree-sitter |
| 7 | `parsers/js_parser.py` | models, base, tree-sitter |
| 8 | `parsers/__init__.py` | base, 모든 파서 |
| 9 | `llm_client.py` | config |
| 10 | `prompt.py` | models |
| 11 | `comment_inserter.py` | models |
| 12 | `processor.py` | 위 전체 통합 |
| 13 | `main.py` | processor |

### 14. 검증 방법

1. `--dry-run`으로 함수 추출 확인 (LLM 없이 파서만 테스트)
2. 단일 파일 end-to-end 테스트: `python main.py test_sample.py`
3. result/ 출력 파일의 구문 오류 확인: `ast.parse()` 통과 여부
4. 원본 vs result/ diff 비교
5. 셀프 테스트: `python main.py .` 으로 gen_comment 자체에 적용

### 15. 의존성

- `requests` (Ollama HTTP 호출)
- `tree-sitter` (C/C++, Java, JS 파싱)
- `tree-sitter-language-pack` (언어별 grammar 번들)
- Python 표준 라이브러리: `ast`, `argparse`, `pathlib`, `concurrent.futures`, `dataclasses`, `logging`

### 16. 향후 확장 고려사항

- **추가 언어 지원**: `parsers/` 디렉토리에 새 파서 추가 (BaseParser 상속, tree-sitter grammar 활용)
- **배치 처리**: 대규모 프로젝트를 위한 중단/재개 기능 (처리 완료 파일 목록 저장)
- **주석 품질 검증**: 생성된 주석을 2차 LLM 호출로 검증
- **증분 처리**: git diff 기반으로 변경된 함수만 재처리

---

<!-- 새 설계안 추가 시 아래 형식을 따라주세요:

## 설계안 #N: [제목]

- **작성일**: YYYY-MM-DD
- **상태**: `초안` | `채택` | `폐기`
- **목적**: 한 줄 요약
- **관련 설계안**: #1, #2 (있는 경우)

### 1. 배경 및 목표
...
-->
