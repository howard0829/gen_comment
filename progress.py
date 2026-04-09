"""tqdm 기반 진행률 모니터"""

import sys

from tqdm import tqdm


class ProgressMonitor:
    """파일 바(outer) + 함수 바(inner) 2단 tqdm 진행률 표시"""

    def __init__(self, total_files: int, enabled: bool = True):
        self.enabled = enabled

        # 결과 카운터
        self.success_count = 0
        self.skip_count = 0
        self.error_count = 0

        # 파일 진행 바 (outer)
        self._file_bar: tqdm | None = None
        # 함수 진행 바 (inner)
        self._func_bar: tqdm | None = None

        if self.enabled:
            self._file_bar = tqdm(
                total=total_files,
                desc="전체 진행",
                unit="file",
                position=0,
                file=sys.stderr,
                bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} files [{elapsed}<{remaining}]",
            )

    def start_file(self, file_name: str, func_total: int):
        if not self.enabled:
            return
        # 이전 함수 바 정리
        self._close_func_bar()
        # 새 함수 바 생성
        self._func_bar = tqdm(
            total=func_total,
            desc=f"  {file_name}",
            unit="fn",
            position=1,
            leave=False,
            file=sys.stderr,
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} fn [{elapsed}<{remaining}] {postfix}",
        )
        self._update_func_postfix()

    def start_function(self, func_name: str):
        if not self.enabled or not self._func_bar:
            return
        self._func_bar.set_description(f"  ⏳ {func_name}")

    def finish_function(self, func_name: str, status: str = "success"):
        if status == "success":
            self.success_count += 1
        elif status == "skip":
            self.skip_count += 1
        elif status == "error":
            self.error_count += 1

        if not self.enabled or not self._func_bar:
            return
        self._func_bar.update(1)
        self._update_func_postfix()

    def skip_file(self, file_name: str, func_count: int):
        self.skip_count += func_count
        if not self.enabled:
            return
        if self._file_bar:
            self._file_bar.update(1)

    def add_skipped(self, count: int):
        """파일 내 필터링된 함수를 skip 카운터에 반영"""
        self.skip_count += count

    def finish_file(self):
        """현재 파일 처리 완료 — 파일 바 1칸 진행"""
        if not self.enabled:
            return
        self._close_func_bar()
        if self._file_bar:
            self._file_bar.update(1)

    def finish(self):
        if not self.enabled:
            return
        self._close_func_bar()
        if self._file_bar:
            self._file_bar.close()
            self._file_bar = None
        sys.stderr.write(
            f"\n전체 완료 | "
            f"함수: {self.success_count} 성공, {self.skip_count} 스킵, {self.error_count} 실패\n"
        )
        sys.stderr.flush()

    def _close_func_bar(self):
        if self._func_bar is not None:
            self._func_bar.close()
            self._func_bar = None

    def _update_func_postfix(self):
        if self._func_bar:
            self._func_bar.set_postfix_str(
                f"OK:{self.success_count} skip:{self.skip_count} err:{self.error_count}"
            )
