"""
Разбор полей уведомления Prodamus в структуру, эквивалентную PHP-массиву `$_POST`.

Prodamus шлёт уведомление в multipart/form-data с плоскими ключами вида
`products[0][name]`, `subscription[id]`. Он подписывает исходный ассоциативный массив,
а форма — лишь транспорт, поэтому подпись проверяется ПОСЛЕ разбора, на восстановленной
структуре. Транспорт (multipart или urlencoded) на результат не влияет.

Ключевая тонкость: PHP-массив с ключами 0..n-1 без пропусков json_encode кодирует как
список, а не объект. Если этого не воспроизвести, подпись не сойдётся.
"""
import re
from collections.abc import Iterable
from urllib.parse import parse_qsl

_KEY_RE = re.compile(r"^([^\[\]]+)((?:\[[^\[\]]*\])*)$")
_PART_RE = re.compile(r"\[([^\[\]]*)\]")


def _split_key(key: str) -> list[str]:
    """'a[b][0]' -> ['a', 'b', '0']; 'a' -> ['a']. Некорректный ключ -> [key]."""
    match = _KEY_RE.match(key)
    if match is None:
        return [key]
    base, rest = match.group(1), match.group(2)
    return [base, *_PART_RE.findall(rest)]


def _assign(root: dict, path: list[str], value: str) -> None:
    node = root
    for i, part in enumerate(path):
        last = i == len(path) - 1
        if part == "":
            # PHP `a[]=x` — автоинкремент числового индекса.
            part = str(len([k for k in node if k.isdigit()]))
        if last:
            node[part] = value
            return
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child


def _listify(node):
    """dict с ключами '0'..'n-1' без пропусков -> list (как PHP-массив)."""
    if not isinstance(node, dict):
        return node
    converted = {k: _listify(v) for k, v in node.items()}
    keys = list(converted)
    if keys and all(k.isdigit() for k in keys):
        indexes = sorted(int(k) for k in keys)
        if indexes == list(range(len(indexes))):
            return [converted[str(i)] for i in indexes]
    return converted


def parse_php_pairs(pairs: Iterable[tuple[str, str]]) -> dict:
    """[('products[0][name]', 'X'), ('order_id', '1')] -> {'products': [{'name': 'X'}], 'order_id': '1'}"""
    root: dict = {}
    for key, value in pairs:
        _assign(root, _split_key(key), value)
    result = _listify(root)
    return result if isinstance(result, dict) else root


def parse_php_form(body: str) -> dict:
    """'products[0][name]=X&order_id=1' -> {'products': [{'name': 'X'}], 'order_id': '1'}"""
    return parse_php_pairs(parse_qsl(body, keep_blank_values=True))


def php_form_pairs(data, prefix: str = "") -> list[tuple[str, str]]:
    """Вложенная структура -> плоские пары PHP-формы (для multipart в тестах и имитации)."""
    pairs: list[tuple[str, str]] = []
    items = enumerate(data) if isinstance(data, (list, tuple)) else data.items()
    for key, value in items:
        full = f"{prefix}[{key}]" if prefix else str(key)
        if isinstance(value, (dict, list, tuple)):
            pairs.extend(php_form_pairs(value, full))
        else:
            pairs.append((full, "" if value is None else str(value)))
    return pairs


def php_urlencode(data, prefix: str = "") -> str:
    """Обратная операция — нужна тестам и локальной имитации вебхука."""
    from urllib.parse import quote

    parts: list[str] = []
    items = enumerate(data) if isinstance(data, (list, tuple)) else data.items()
    for key, value in items:
        full = f"{prefix}[{key}]" if prefix else str(key)
        if isinstance(value, (dict, list, tuple)):
            nested = php_urlencode(value, full)
            if nested:
                parts.append(nested)
        else:
            text = "" if value is None else str(value)
            parts.append(f"{quote(str(full), safe='')}={quote(text, safe='')}")
    return "&".join(parts)
