"""실시간 진행률 모니터"""

import sys
import time
import threading


class ProgressMonitor:
    """파일 및 함수 단위 실시간 진행률 표시"""

    def __init__(self, total_files: int, enabled: bool = True):
        self.total_files = total_files
        self.enabled = enabled

        # 파일 단위
        self.current_file_idx = 0
        self.current_file_name = ""

        # 함수 단위 (현재 파일 내)
        self.current_func_total = 0
        self.current_func_done = 0
        self.current_func_name = ""

        # 전체 함수 누적
        self.global_func_total = 0
        self.global_func_done = 0

        # 결과 카운터
        self.success_count = 0
        self.skip_count = 0
        self.error_count = 0

        # 시간
        self.start_time = time.time()
        self._last_line_len = 0
        self._lock = threading.Lock()

    def start_file(self, file_name: str, func_total: int):
        with self._lock:
            self.current_file_idx += 1
            self.current_file_name = file_name
            self.current_func_total = func_total
            self.current_func_done = 0
            self.current_func_name = ""
            self.global_func_total += func_total
        self._render()

    def start_function(self, func_name: str):
        with self._lock:
            self.current_func_name = func_name
        self._render()

    def finish_function(self, func_name: str, status: str = "success"):
        with self._lock:
            self.current_func_done += 1
            self.global_func_done += 1
            if status == "success":
                self.success_count += 1
            elif status == "skip":
                self.skip_count += 1
            elif status == "error":
                self.error_count += 1
        self._render()

    def skip_file(self, file_name: str, func_count: int):
        with self._lock:
            self.current_file_idx += 1
            self.skip_count += func_count
            self.global_func_total += func_count
            self.global_func_done += func_count
        self._render()

    def finish(self):
        if not self.enabled:
            return
        self._clear_line()
        elapsed = time.time() - self.start_time
        sys.stderr.write(
            f"\r전체 완료 | "
            f"함수: {self.success_count} 성공, {self.skip_count} 스킵, {self.error_count} 실패 | "
            f"소요: {self._format_time(elapsed)}\n"
        )
        sys.stderr.flush()

    def _render(self):
        if not self.enabled:
            return

        elapsed = time.time() - self.start_time

        # 잔여 시간 추정
        eta_str = ""
        if self.global_func_done > 0 and self.global_func_total > self.global_func_done:
            rate = elapsed / self.global_func_done
            remaining = (self.global_func_total - self.global_func_done) * rate
            eta_str = f" | ETA {self._format_time(remaining)}"

        # 현재 파일 내 진행
        file_progress = f"[{self.current_file_idx}/{self.total_files}]"
        func_progress = f"({self.current_func_done}/{self.current_func_total})"

        # 처리 중인 함수명 (길면 잘라내기)
        func_display = self.current_func_name
        if len(func_display) > 30:
            func_display = func_display[:27] + "..."

        # 전체 카운터
        counts = f"OK:{self.success_count} skip:{self.skip_count} err:{self.error_count}"

        line = (
            f"\r{file_progress} {self.current_file_name} "
            f"{func_progress} {func_display} | "
            f"{counts} | {self._format_time(elapsed)}{eta_str}"
        )

        self._write_line(line)

    def _write_line(self, line: str):
        # 이전 출력보다 짧으면 공백으로 덮어쓰기
        padding = max(0, self._last_line_len - len(line))
        sys.stderr.write(line + " " * padding)
        sys.stderr.flush()
        self._last_line_len = len(line)

    def _clear_line(self):
        sys.stderr.write("\r" + " " * self._last_line_len + "\r")
        sys.stderr.flush()
        self._last_line_len = 0

    @staticmethod
    def _format_time(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f}s"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        if minutes < 60:
            return f"{minutes}m{secs:02d}s"
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours}h{mins:02d}m"
