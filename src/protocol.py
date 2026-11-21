"""Shared collaboration operation schemas and strict payload validation."""
from dataclasses import asdict
from datetime import datetime, timezone

from .errors import ValidationError


def validate(data, schema):
    if not isinstance(data, dict) or any(key not in schema for key in data):
        raise ValidationError('Expected an object containing only supported fields')
    for key, (kind, required, default) in schema.items():
        if key not in data:
            if required:
                raise ValidationError('Missing required field: ' + key)
            data[key] = default
        value = data[key]
        if value is None and not required and default is None:
            continue
        if type(value) is not kind:
            raise ValidationError('Invalid field type: ' + key)
        if kind is str:
            try:
                value.encode('utf-8')
            except UnicodeEncodeError:
                raise ValidationError('Text must contain valid Unicode') from None
    return data


def fields(required='', optional=None):
    result = {key: (int if key in {'source_task_id', 'target_task_id', 'dependency_id', 'reply_id', 'expected_revision', 'ownership_epoch', 'expected_version', 'context_version', 'version', 'request_id', 'contract_id', 'task_id', 'after_id', 'limit'} else str, True, None) for key in required.split()}
    for key, default in (optional or {}).items():
        result[key] = (int if key in {'before_id', 'ownership_epoch', 'source_request_id', 'task_id', 'after_id', 'limit', 'hours'} else str, False, default)
    return result


SEND_REQUEST_SCHEMA = {
    **fields('request_key body', {'receiver_member_id': None, 'task_id': None}),
    'context_version': (int, False, 1),
}


def _text(value, field, maximum):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise ValidationError(f"{field} must contain 1 to {maximum} characters")
    return value.strip()


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


class ServiceOperations:
    def me(self, token):
        return {'me': asdict(self.identity.authenticate(token)), 'room': self.identity.room_info(token)}

    def call(self, operation, token, data):
        kind, method, schema = self.operations[operation]
        if kind:
            self.identity.authenticate(token, required_kind=None if kind == 'any' else kind)
        data = validate(dict(data) if isinstance(data, dict) else data, schema)
        return method(token, **data) if kind else method(**data)
