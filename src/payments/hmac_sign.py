r"""
Подпись запросов Prodamus, совместимая с их PHP-библиотекой (`Hmac::create`).

Эталонный алгоритм PHP:
    unset($data['signature']);
    array_walk_recursive($data, fn(&$v) => $v = strval($v));
    ksort_recursive($data);
    $json = json_encode($data, JSON_UNESCAPED_UNICODE);
    hash_hmac('sha256', $json, $secret_key);

Три места, где Python по умолчанию расходится с PHP и подпись молча не сходится:
  1. PHP экранирует "/" как "\/" — а слэшей полно в urlNotification/urlReturn;
  2. strval(true)="1", strval(false)="" и strval(null)="" — Python дал бы "True"/"False"/"None";
  3. PHP-массив с ключами 0..n-1 кодируется как JSON-список, а не объект
     (за это отвечает parse_php_form в formdata.py).
"""
import hashlib
import hmac
import json
import logging

logger = logging.getLogger(__name__)


def _stringify(value) -> str:
    """Аналог PHP strval() для скаляров."""
    if value is True:
        return "1"
    if value is False or value is None:
        return ""
    return str(value)


def _normalize(data):
    """Рекурсивно сортирует ключи словарей и приводит скаляры к строкам."""
    if isinstance(data, dict):
        return {str(k): _normalize(v) for k, v in sorted(data.items(), key=lambda kv: str(kv[0]))}
    if isinstance(data, (list, tuple)):
        return [_normalize(v) for v in data]
    return _stringify(data)


def _php_json(data) -> str:
    """json_encode($data, JSON_UNESCAPED_UNICODE): без пробелов, юникод как есть, слэши экранированы."""
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # "/" не структурный символ JSON, поэтому замена на готовой строке безопасна.
    return raw.replace("/", "\\/")


def create_signature(data: dict, secret_key: str) -> str:
    """Считает подпись по данным (ключ `signature` из подписи исключается)."""
    payload = {k: v for k, v in data.items() if k != "signature"}
    message = _php_json(_normalize(payload))
    return hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_signature(data: dict, secret_key: str, received: str | None) -> bool:
    """Сравнивает подпись из заголовка Sign с вычисленной (регистр не важен)."""
    if not received:
        return False
    expected = create_signature(data, secret_key)
    return hmac.compare_digest(expected, received.strip().lower())
