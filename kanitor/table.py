"""Physical-line scrolling for selectable summary rows of different heights."""
from bisect import bisect_right


class RowViewport:
    def __init__(self, heights=(), capacity=1):
        self.heights = list(heights)
        self.capacity = max(1, capacity)
        self.starts = [0]
        for height in heights:
            self.starts.append(self.starts[-1] + height)

    @property
    def total(self):
        return self.starts[-1]

    @property
    def maximum(self):
        return max(0, self.total - self.capacity)

    @property
    def multiline(self):
        return any(height > 1 for height in self.heights)

    def index(self, line):
        return max(0, min(len(self.heights) - 1, bisect_right(self.starts, line) - 1))

    def ensure(self, selected, top):
        top = max(0, min(self.maximum, top))
        if not self.heights:
            return top
        start, end = self.starts[selected:selected + 2]
        if self.heights[selected] > self.capacity:
            return min(start, self.maximum) if end <= top or start >= top + self.capacity else top
        return max(0, min(self.maximum, min(top, start) if start < top else max(top, end - self.capacity)))

    def move(self, selected, top, delta, page=False):
        new_top = max(0, min(self.maximum, top + delta))
        if not self.heights:
            return selected, new_top
        if page:
            selected = self.index(max(self.starts[selected], top) + delta)
        elif self.starts[selected + 1] <= new_top:
            selected = self.index(new_top)
        elif self.starts[selected] >= new_top + self.capacity:
            selected = self.index(new_top + self.capacity - 1)
        return selected, new_top
