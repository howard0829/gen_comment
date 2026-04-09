"""프롬프트 템플릿 및 LLM 응답 파싱"""

import re

from config import LARGE_FUNCTION_HEAD, LARGE_FUNCTION_TAIL, LARGE_FUNCTION_THRESHOLD
from models import FunctionInfo

SYSTEM_PROMPT = """\
You are a code documentation expert. Generate a structured comment for the given function.

## Output Format

Output ONLY the comment content below — no code fences, no triple quotes, no extra text.

[Summary] Detailed description of what the function does, its purpose, key logic, and behavior.
Write at least 3 sentences and at most 10 sentences so that a reader can fully understand the function without reading the code.

[Args]
    param1 (type): Description.
    param2 (type): Description.

[Returns]
    type: Description.

[Raises]
    ExceptionType: When it occurs.

[Calls] function_a, module.function_b
[Side Effects] Description of side effects.
[Tags] keyword1, keyword2, keyword3

## Rules

- [Summary] is REQUIRED. Write 3-10 sentences covering: what the function does, how it works (key logic/algorithm), and any important behavior or constraints.
- For other sections, be concise. One line per parameter/return/exception.
- [Tags] should include semantic keywords useful for search (synonyms, higher-level concepts).
- [Calls] lists other functions/methods this function calls.
- Write in the same language as the source code comments (Korean if Korean, English if English, etc.).
  If no comments exist, default to Korean.
- Do NOT wrap output in triple quotes, code fences, or any markup.
- Do NOT include the function signature in your output.
"""

DECLARATION_SYSTEM_PROMPT = """\
You are a code documentation expert. Generate a brief comment for a function declaration/prototype.
Since there is no function body, base your comment on the signature only.

## Output Format

Output ONLY the comment content — no code fences, no triple quotes.

[Summary] Detailed description based on function name and parameters (3-10 sentences).

[Args]
    param1 (type): Description.

[Returns]
    type: Description.

[Tags] keyword1, keyword2

## Rules

- [Summary] is REQUIRED. Write 3-10 sentences describing the likely purpose and behavior based on the signature.
- For other sections, be concise.
- Write in Korean by default.
- Do NOT wrap output in any markup.
"""


def build_user_prompt(func_info: FunctionInfo) -> str:
    source = func_info.source_text
    line_count = source.count("\n") + 1

    # 대형 함수: truncate
    if line_count > LARGE_FUNCTION_THRESHOLD:
        src_lines = source.splitlines(keepends=True)
        head = "".join(src_lines[:LARGE_FUNCTION_HEAD])
        tail = "".join(src_lines[-LARGE_FUNCTION_TAIL:])
        source = f"{head}\n# ... truncated ({line_count - LARGE_FUNCTION_HEAD - LARGE_FUNCTION_TAIL} lines) ...\n\n{tail}"

    context_parts = [f"Language: {func_info.language}"]
    if func_info.class_name:
        context_parts.append(f"Class: {func_info.class_name}")
    if func_info.is_async:
        context_parts.append("Async: yes")
    if func_info.decorators:
        context_parts.append(f"Decorators: {', '.join(func_info.decorators)}")

    context = " | ".join(context_parts)

    return f"{context}\n\nGenerate a structured comment for this function:\n\n{source}"


def get_system_prompt(func_info: FunctionInfo) -> str:
    if func_info.is_declaration_only:
        return DECLARATION_SYSTEM_PROMPT
    return SYSTEM_PROMPT


def parse_llm_response(raw: str) -> str | None:
    if not raw or not raw.strip():
        return None

    text = raw.strip()

    # 마크다운 코드 펜스 제거
    text = re.sub(r"^```\w*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)

    # triple-quote 래핑 제거
    if text.startswith('"""') or text.startswith("'''"):
        text = text[3:]
    if text.endswith('"""') or text.endswith("'''"):
        text = text[:-3]

    # /* */ 래핑 제거
    if text.startswith("/*"):
        text = re.sub(r"^/\*\*?\s*\n?", "", text)
        text = re.sub(r"\n?\s*\*/$", "", text)
        # 각 줄 앞의 * 제거
        lines = text.splitlines()
        cleaned = []
        for line in lines:
            cleaned_line = re.sub(r"^\s*\*\s?", "", line)
            cleaned.append(cleaned_line)
        text = "\n".join(cleaned)

    text = text.strip()

    # [Summary] 존재 확인
    if "[Summary]" not in text:
        # Summary가 없으면 첫 줄을 Summary로 간주
        lines = text.splitlines()
        if lines:
            text = f"[Summary] {lines[0]}\n" + "\n".join(lines[1:])

    return text if text else None
