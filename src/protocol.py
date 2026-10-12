"""Shared collaboration operation schemas and strict payload validation."""
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
        result[key] = (int if key in {'before_id', 'ownership_epoch', 'source_request_id', 'task_id', 'after_id', 'limit'} else str, False, default)
    return result
