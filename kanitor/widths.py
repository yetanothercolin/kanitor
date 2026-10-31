"""Column sizing grammar and deterministic integer-space allocation."""
from dataclasses import dataclass
import re


# Used by both the column parser and the discoverable work configuration schema.
_SPACE, _MODE, _BOUND = r'[ \t]*', r'(?:hug|fill)', r'[1-9][0-9]*'
_COMMA = rf'{_SPACE},{_SPACE}'
WIDTH_PATTERN = (rf'^{_SPACE}(?:{_MODE}|{_BOUND}{_COMMA}{_MODE}|{_MODE}{_COMMA}{_BOUND}|'
                 rf'{_BOUND}{_COMMA}{_MODE}{_COMMA}{_BOUND}){_SPACE}$(?!\n)')


@dataclass(frozen=True)
class WidthSpec:
    mode: str
    minimum: int = None
    maximum: int = None


def parse_width(value):
    if value is None:
        return WidthSpec('fill')
    if type(value) is int and value >= 4:
        return WidthSpec('fixed', maximum=value)
    if isinstance(value, str) and re.fullmatch(WIDTH_PATTERN, value):
        parts = [part.strip() for part in value.split(',')]
        mode = next(part for part in parts if part in ('hug', 'fill'))
        minimum = int(parts[0]) if parts[0] != mode else None
        maximum = int(parts[-1]) if parts[-1] != mode else None
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError('minimum width must not exceed maximum width')
        return WidthSpec(mode, minimum, maximum)
    raise ValueError('must be an integer of at least 4 terminal cells, "hug", "fill", '
                     'or a constraint such as "fill,8", "8,hug", or "2,hug,8" '
                     '(bounds must be positive integers)')


def shrink_widths(targets, minimums, budget):
    """Shrink excess proportionately; give rounding cells to eligible columns in order."""
    extras = [target - minimum for target, minimum in zip(targets, minimums)]
    total = sum(extras)
    remaining = budget - sum(minimums)
    if not total:
        return list(minimums)
    widths = [base + remaining * extra // total for base, extra in zip(minimums, extras)]
    remainder = budget - sum(widths)
    for index, target in enumerate(targets):
        if remainder and widths[index] < target:
            widths[index] += 1
            remainder -= 1
    return widths


def share_widths(minimums, maximums, budget):
    """Find the equal fill level with bounds, then round in configuration order."""
    def at_level(level):
        return [max(low, min(level, high if high is not None else budget))
                for low, high in zip(minimums, maximums)]

    lower, upper = 0, budget
    while lower < upper:
        middle = (lower + upper + 1) // 2
        if sum(at_level(middle)) <= budget:
            lower = middle
        else:
            upper = middle - 1
    widths = at_level(lower)
    remainder = budget - sum(widths)
    for index, maximum in enumerate(maximums):
        # A column pinned above the water level already has its full minimum.
        if remainder and widths[index] == lower and (maximum is None or widths[index] < maximum):
            widths[index] += 1
            remainder -= 1
    return widths
