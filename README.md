# gen_comment

코드 파일의 모든 함수에 LLM(Ollama)으로 **RAG 검색에 최적화된 구조화 주석**을 자동 생성하는 CLI 도구.

## 주요 기능

- **다국어 지원**: Python, C/C++, Java, JavaScript/TypeScript
- **함수 단위 처리**: 파일 전체가 아닌 개별 함수만 LLM에 전달하여 속도와 정확도 향상
- **원본 보존**: 원본 파일은 수정하지 않고 `result/` 폴더에 전체 복사 후 작업
- **즉시 반영**: 함수마다 주석 생성 즉시 result 파일에 저장 (중단 시에도 이전 결과 보존)
- **RAG 최적화 주석**: `[Summary]`, `[Args]`, `[Tags]` 등 구조화된 포맷으로 검색 성능 극대화
- **실시간 진행률**: tqdm 기반 파일/함수 단위 프로그레스 바
- **비UTF-8 파일 지원**: chardet 기반 인코딩 자동 감지 (EUC-KR, Shift_JIS 등)

## 설치

```bash
# 의존성 설치
pip install -r requirements.txt

# Ollama 실행 필요 (별도 터미널)
ollama serve
```

### requirements.txt

```
requests>=2.28.0
chardet>=5.0.0
tqdm>=4.60.0
tree-sitter>=0.24.0        # Java, JS/TS 파싱용 (Python, C만 사용 시 불필요)
tree-sitter-java>=0.23.0
tree-sitter-javascript>=0.23.0
tree-sitter-typescript>=0.23.0
```

> Python, C/C++ 파일만 처리할 경우 `requests`, `chardet`, `tqdm`만 설치하면 됩니다.
> C/C++ 파서는 외부 의존성 없이 정규식 + 중괄호 매칭으로 동작합니다.

## 사용법

```bash
python3 main.py <경로> [옵션]
```

### 기본 사용 예시

```bash
# 폴더 전체 처리 (재귀 탐색)
python3 main.py ./src

# 단일 파일 처리
python3 main.py ./src/auth.py

# 출력 폴더 지정
python3 main.py ./src -o commented/

# 함수 목록만 확인 (LLM 미호출)
python3 main.py ./src --dry-run
```

### 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `path` | 처리할 디렉토리 또는 파일 경로 | (필수) |
| `-o`, `--output` | 출력 디렉토리 | `result/` |
| `-m`, `--model` | Ollama 모델명 | `gemma4:31b` |
| `--ollama-url` | Ollama API URL | `http://localhost:11434` |
| `--workers` | 파일 내 병렬 LLM 호출 수 | `3` |
| `--overwrite` | 기존 docstring/주석도 재생성 | off |
| `--include-declarations` | 본문 없는 함수 선언에도 주석 생성 | off |
| `--lang` | 처리할 언어 제한 (쉼표 구분) | 전체 |
| `--dry-run` | 함수 목록만 출력, LLM 미호출 | off |
| `-v`, `--verbose` | 상세 로그 출력 | off |

### 고급 사용 예시

```bash
# Python과 Java만 처리
python3 main.py ./src --lang python,java

# 기존 docstring 덮어쓰기
python3 main.py ./src --overwrite

# 다른 Ollama 모델 사용
python3 main.py ./src -m qwen3:8b

# 병렬 처리 수 조절 (GPU 성능에 따라)
python3 main.py ./src --workers 1
```

## 처리 동작 방식

```
1. 모든 파일을 result/ 폴더에 복사
2. result/ 내 소스 파일에서 함수를 추출하고 처리 대상을 필터링
3. 각 함수의 소스 텍스트를 LLM에 전달하여 주석 생성
4. 주석이 생성되면 해당 함수의 중괄호({ ) 다음 줄에 즉시 삽입 후 파일 저장
5. bottom-up (파일 뒤쪽 함수부터) 순서로 처리하여 라인 번호 시프트 방지
```

## 출력 구조

원본 디렉토리 구조를 `result/` 폴더에 그대로 복사하여 작업합니다.

```
원본: ./src/auth/login.py
결과: ./result/auth/login.py
```

처리 완료 시 요약 리포트가 출력됩니다:

```
==================================================
처리 완료: 15개 파일, 47개 함수 발견
  주석 생성: 42 | 스킵: 5 | 오류: 0
  결과 경로: /home/project/result/
==================================================
```

## 생성되는 주석 포맷

RAG 시스템에서 함수 단위 검색에 최적화된 구조화 포맷을 사용합니다.

### Python

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

    [Calls] db.get_user, jwt.encode, hash_password
    [Side Effects] 로그인 시도 횟수를 DB에 기록
    [Tags] 인증, JWT, 로그인, 보안, 사용자
    """
```

### C/C++

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

### Java / JavaScript

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

### 주석 섹션 설명

| 섹션 | 필수 | 설명 |
|------|------|------|
| `[Summary]` | O | 함수 목적 한 줄 요약 |
| `[Args]` | | 파라미터 이름, 타입, 설명 |
| `[Returns]` | | 반환값 타입 및 설명 |
| `[Raises]` / `[Throws]` | | 발생 가능 예외 |
| `[Calls]` | | 호출하는 다른 함수 목록 |
| `[Side Effects]` | | 부수 효과 (DB 쓰기, 파일 I/O 등) |
| `[Tags]` | | 검색용 의미 키워드 |

해당 없는 섹션은 자동으로 생략됩니다.

### 자동 스킵 대상

- 이미 docstring/주석이 있는 함수 (`--overwrite`로 재생성 가능)
- 본문 없는 함수 선언: 추상 메서드, 인터페이스 (`--include-declarations`로 포함 가능)
- 헤더 파일 (`.h`, `.hpp`, `.hh`)
- 구문 오류가 있는 파일

## 프로젝트 구조

```
gen_comment/
├── main.py                  # CLI 진입점
├── config.py                # 설정 상수
├── models.py                # 데이터 클래스
├── llm_client.py            # Ollama API 클라이언트
├── prompt.py                # 프롬프트 템플릿 및 응답 파싱
├── processor.py             # 파일 처리 오케스트레이터
├── progress.py              # tqdm 기반 진행률 모니터
├── comment_inserter.py      # 주석 삽입 엔진 (레거시)
├── parsers/
│   ├── __init__.py          # 파서 레지스트리
│   ├── base.py              # 파서 추상 클래스
│   ├── python_parser.py     # Python (ast 표준 라이브러리)
│   ├── c_parser.py          # C/C++ (정규식 + 중괄호 매칭)
│   ├── java_parser.py       # Java (tree-sitter)
│   └── js_parser.py         # JavaScript/TypeScript (tree-sitter)
├── requirements.txt
├── docs/
│   └── design_report.md     # 설계 보고서
└── README.md
```

## 지원 언어

| 언어 | 확장자 | 파싱 엔진 |
|------|--------|-----------|
| Python | `.py` | `ast` (표준 라이브러리) |
| C/C++ | `.c` `.cpp` `.cc` `.cxx` | 정규식 + 중괄호 매칭 (외부 의존성 없음) |
| Java | `.java` | tree-sitter |
| JavaScript/TypeScript | `.js` `.ts` `.jsx` `.tsx` | tree-sitter |

> C/C++ 헤더 파일(`.h`, `.hpp`, `.hh`)은 자동 스킵됩니다.
