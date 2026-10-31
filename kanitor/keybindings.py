"""Validated action bindings, independent of an initialized curses terminal."""
import curses
from dataclasses import dataclass
from functools import cached_property
import re


DEFAULT_KEYS = {
    'up': ('up', 'k'), 'down': ('down', 'j'),
    'left': ('left',), 'right': ('right',),
    'open': ('enter', 'space'), 'back': ('escape',),
    'first': ('home',), 'last': ('end',),
    'jumpUp': ('shift+up',), 'jumpDown': ('shift+down',),
    'jumpLeft': ('shift+left',), 'jumpRight': ('shift+right',),
    'pageUp': ('pageup', 'ctrl+shift+up'),
    'pageDown': ('pagedown', 'ctrl+shift+down'),
    'columnMenu': ('f',), 'statusFilter': ('s',), 'togglePreview': ('p',),
    'toggleActivity': ('a',), 'focusPane': ('tab', 'shift+tab'),
    'previousBoard': ('[',), 'nextBoard': (']', 'b'),
    'search': ('/',), 'refresh': ('r',), 'help': ('?',), 'quit': ('q',),
}

ACTION_DESCRIPTIONS = {
    'up': 'Previous row / scroll up', 'down': 'Next row / scroll down',
    'left': 'Previous cell / close details', 'right': 'Next cell',
    'open': 'Open row or square / activate menu', 'back': 'Close menu / parent view',
    'first': 'First item / top', 'last': 'Last item / bottom',
    'jumpUp': 'Jump up ten items or lines', 'jumpDown': 'Jump down ten items or lines',
    'jumpLeft': 'Previous cell / jump left five squares',
    'jumpRight': 'Next cell / jump right five squares',
    'pageUp': 'Previous visible page', 'pageDown': 'Next visible page',
    'columnMenu': 'Column actions', 'statusFilter': 'Task Status checkbox filter',
    'togglePreview': 'Show/hide description preview',
    'toggleActivity': 'Show/hide in-progress activity',
    'focusPane': 'Switch main table / activity focus',
    'previousBoard': 'Previous board', 'nextBoard': 'Next board',
    'search': 'Search tasks', 'refresh': 'Refresh files', 'help': 'Help',
    'quit': 'Close menu/help/details or quit',
}

NAMED_CODES = {
    'up': curses.KEY_UP, 'down': curses.KEY_DOWN,
    'left': curses.KEY_LEFT, 'right': curses.KEY_RIGHT,
    'home': curses.KEY_HOME, 'end': curses.KEY_END,
    'pageup': curses.KEY_PPAGE, 'pagedown': curses.KEY_NPAGE,
    'enter': curses.KEY_ENTER, 'backspace': curses.KEY_BACKSPACE,
    'delete': curses.KEY_DC, 'insert': curses.KEY_IC,
    'shift+up': curses.KEY_SR, 'shift+down': curses.KEY_SF,
    'shift+tab': curses.KEY_BTAB,
}
for _name, _constant in (('shift+left', 'KEY_SLEFT'), ('shift+right', 'KEY_SRIGHT'),
                         ('shift+home', 'KEY_SHOME'), ('shift+end', 'KEY_SEND')):
    if hasattr(curses, _constant):
        NAMED_CODES[_name] = getattr(curses, _constant)
CODE_NAMES = {code: name for name, code in NAMED_CODES.items()}
ALIASES = {'esc': 'escape', 'return': 'enter', 'pgup': 'pageup', 'pgdn': 'pagedown',
           'pgdown': 'pagedown', 'backtab': 'shift+tab', 'del': 'delete', 'ins': 'insert'}
BASE_NAMES = {'up', 'down', 'left', 'right', 'home', 'end', 'pageup', 'pagedown'}
LABELS = {'up': '↑', 'down': '↓', 'left': '←', 'right': '→', 'enter': 'Enter',
          'escape': 'Esc', 'space': 'Space', 'tab': 'Tab', 'home': 'Home', 'end': 'End',
          'pageup': 'PageUp', 'pagedown': 'PageDown', 'backspace': 'Backspace',
          'delete': 'Delete', 'insert': 'Insert'}


def key_token(key):
    """Normalize terminal aliases before resolving bindings or detecting conflicts."""
    if isinstance(key, str):
        aliases = {'\n': 'enter', '\r': 'enter', ' ': 'space', '\t': 'tab',
                   '\x1b': 'escape', '\x7f': 'backspace', '\b': 'backspace',
                   '\0': 'ctrl+space', '\x1c': 'ctrl+\\', '\x1d': 'ctrl+]',
                   '\x1e': 'ctrl+^', '\x1f': 'ctrl+_'}
        if key in aliases:
            return aliases[key]
        if len(key) == 1:
            number = ord(key)
            return 'ctrl+' + chr(number + 96) if 1 <= number <= 26 else key
        return None
    if not isinstance(key, int):
        return None
    if key in CODE_NAMES:
        return CODE_NAMES[key]
    if curses.KEY_F0 < key <= curses.KEY_F0 + 24:
        return f'f{key - curses.KEY_F0}'
    try:
        name = curses.keyname(key).decode('ascii')
    except (curses.error, UnicodeDecodeError):
        return None
    match = re.fullmatch(r'k(UP|DN|LFT|RIT|HOM|END|PRV|NXT)([256]?)', name)
    if match:
        base = dict(UP='up', DN='down', LFT='left', RIT='right', HOM='home', END='end', PRV='pageup', NXT='pagedown')[match[1]]
        modifier = {'': 'shift+', '2': 'shift+', '5': 'ctrl+', '6': 'ctrl+shift+'}[match[2]]
        return modifier + base
    return None


def parse_key(value):
    if not isinstance(value, str) or not value:
        raise ValueError('keys must be nonempty strings')
    if len(value) == 1 and value.isprintable():
        return key_token(value)
    name = ALIASES.get(value.casefold(), value.casefold())
    if name in BASE_NAMES | {'enter', 'escape', 'space', 'tab', 'backspace', 'delete', 'insert'}:
        return name
    if re.fullmatch(r'f(?:[1-9]|1[0-9]|2[0-4])', name):
        return name
    parts = name.split('+')
    modifiers = ['ctrl' if part == 'control' else part for part in parts[:-1]]
    base = ALIASES.get(parts[-1], parts[-1])
    if modifiers and len(modifiers) == len(set(modifiers)) and set(modifiers) <= {'ctrl', 'shift'}:
        prefix = ('ctrl+' if 'ctrl' in modifiers else '') + ('shift+' if 'shift' in modifiers else '')
        if base in BASE_NAMES or base == 'tab' and modifiers == ['shift']:
            return prefix + base
        if modifiers == ['shift'] and len(base) == 1 and base.isascii() and base.isalpha():
            return base.upper()
        if modifiers == ['ctrl']:
            if len(base) == 1 and 'a' <= base <= 'z':
                return key_token(chr(ord(base) - 96))
            if base in ('space', '\\', ']', '^', '_', '['):
                return 'escape' if base == '[' else 'ctrl+' + base
    raise ValueError(f'unsupported key {value!r}; use a character, named key, F1–F24, Ctrl+letter, or modified navigation key')


def key_label(token):
    if token in LABELS:
        return LABELS[token]
    if token.startswith('ctrl+'):
        return 'Ctrl+' + key_label(token[5:])
    if token.startswith('shift+'):
        return 'Shift+' + key_label(token[6:])
    return token.upper() if re.fullmatch(r'f\d+', token) else token


@dataclass(frozen=True)
class KeyBindings:
    entries: tuple = tuple(DEFAULT_KEYS.items())

    @cached_property
    def keys(self):
        return dict(self.entries)

    @cached_property
    def lookup(self):
        return {key: action for action, keys in self.entries for key in keys}

    def action(self, key):
        return self.lookup.get(key_token(key))

    def label(self, action, short=False):
        keys = self.keys[action]
        return '/'.join(key_label(key) for key in (keys[:1] if short else keys)) or 'Unbound'

    def movement(self, key, page_size):
        return {'up': (-1, False), 'down': (1, False),
                'jumpUp': (-10, False), 'jumpDown': (10, False),
                'pageUp': (-page_size, True), 'pageDown': (page_size, True)}.get(self.action(key))


DEFAULT_BINDINGS = KeyBindings()


def parse_keybindings(value):
    if not isinstance(value, dict):
        raise ValueError('must be an object mapping actions to keys')
    if any(not isinstance(action, str) for action in value):
        raise ValueError('action names must be strings')
    unknown = set(value) - DEFAULT_KEYS.keys()
    if unknown:
        raise ValueError('unknown action(s): ' + ', '.join(sorted(unknown)))
    entries = dict(DEFAULT_KEYS)
    for action, raw in value.items():
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            raise ValueError(f'{action} must be a key string or an array of keys (use [] to disable)')
        try:
            keys = tuple(parse_key(key) for key in raw)
        except ValueError as error:
            raise ValueError(f'{action}: {error}') from error
        if len(keys) != len(set(keys)):
            raise ValueError(f'{action} repeats a key or terminal alias')
        entries[action] = keys
    owners = {}
    for action, keys in entries.items():
        for key in keys:
            if key in owners:
                raise ValueError(f'{action} and {owners[key]} both bind {key_label(key)!r}; replace or disable one assignment')
            owners[key] = action
    return KeyBindings(tuple(entries.items()))
