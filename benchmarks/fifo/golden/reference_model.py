from collections import deque


class FifoModel:
    def __init__(self, data_width: int, depth: int):
        if data_width < 1 or depth < 1:
            raise ValueError("data_width and depth must be positive")
        self.mask = (1 << data_width) - 1
        self.depth = depth
        self.entries: deque[int] = deque()
        self.r_data = 0

    @property
    def empty(self) -> bool:
        return not self.entries

    @property
    def full(self) -> bool:
        return len(self.entries) == self.depth

    def reset(self) -> None:
        self.entries.clear()
        self.r_data = 0

    def step(self, *, wr_en: bool, rd_en: bool, w_data: int) -> None:
        do_write = wr_en and not self.full
        do_read = rd_en and not self.empty
        if do_write:
            self.entries.append(w_data & self.mask)
        if do_read:
            self.r_data = self.entries.popleft()
