"""설정 상수 및 기본값"""

# Ollama 설정
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3.5:122b"
DEFAULT_TIMEOUT = 600
DEFAULT_NUM_CTX = 131072
DEFAULT_TEMPERATURE = 0.3

# 처리 설정
DEFAULT_OUTPUT_DIR = "result"
DEFAULT_WORKERS = 3
LARGE_FUNCTION_THRESHOLD = 500      # 줄 수 초과 시 truncate
LARGE_FUNCTION_HEAD = 100
LARGE_FUNCTION_TAIL = 50
LARGE_FILE_THRESHOLD = 10000        # 줄 수 초과 시 청크 기반 쓰기
VERY_LARGE_FILE_THRESHOLD = 100000  # 줄 수 초과 시 진행률 표시

# 지원 언어별 확장자
LANGUAGE_EXTENSIONS = {
    "python": [".py"],
    "c": [".c", ".cpp", ".cc", ".cxx"],
    "java": [".java"],
    "javascript": [".js", ".ts", ".jsx", ".tsx"],
}

# 확장자 → 언어 역매핑
EXTENSION_TO_LANGUAGE = {}
for lang, exts in LANGUAGE_EXTENSIONS.items():
    for ext in exts:
        EXTENSION_TO_LANGUAGE[ext] = lang
