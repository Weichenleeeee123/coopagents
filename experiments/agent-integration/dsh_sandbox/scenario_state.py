"""Evidence-linked scenario state transitions; this module never operates agents."""


_SAFE_FIELDS = {
    'question_created': ('request_id',),
    'reply_created': ('request_id', 'reply_id'),
    'answer_consumed': ('request_id', 'reply_id'),
    'decision_presented': (),
    'operator_decision': ('decision', 'actor_alias'),
    'decision_applied': ('decision',),
}


class ScenarioState:
    def __init__(self, scenario_id):
        if not isinstance(scenario_id, str) or not scenario_id:
            raise ValueError('Scenario id is required')
        self.scenario_id = scenario_id
        self.events = []
        self._request_id = None
        self._reply_id = None
        self._operator_decision = None

    @property
    def complete(self):
        kinds = [event['kind'] for event in self.events]
        if self.scenario_id == 'human-decision':
            return all(kind in kinds for kind in ('decision_presented', 'operator_decision', 'decision_applied'))
        return all(kind in kinds for kind in ('question_created', 'reply_created', 'answer_consumed'))

    def observe(self, kind, *, source, evidence_ref, **details):
        if kind not in _SAFE_FIELDS:
            raise ValueError('Unknown scenario event')
        if source not in ('native', 'human'):
            raise ValueError('Scenario transitions require native evidence or an operator event')
        if not isinstance(evidence_ref, str) or not evidence_ref.strip():
            raise ValueError('Evidence reference is required')
        if any(event['kind'] == kind for event in self.events):
            raise ValueError('Scenario event already recorded')
        safe = {key: details[key] for key in _SAFE_FIELDS[kind] if key in details}
        if kind == 'question_created':
            self._request_id = safe.get('request_id')
            if source != 'native' or not self._request_id:
                raise ValueError('A native request identity is required')
        elif kind == 'reply_created':
            if source != 'native' or not self._request_id or safe.get('request_id') != self._request_id or not safe.get('reply_id'):
                raise ValueError('Reply must link to the current native request')
            self._reply_id = safe['reply_id']
        elif kind == 'answer_consumed':
            if source != 'native' or not self._reply_id or safe.get('request_id') != self._request_id or safe.get('reply_id') != self._reply_id:
                raise ValueError('Consumption must link to the observed request and reply')
        elif kind == 'decision_presented':
            if self.scenario_id != 'human-decision' or source != 'native':
                raise ValueError('Decision presentation must be a native observation')
        elif kind == 'operator_decision':
            if self.scenario_id != 'human-decision' or not any(e['kind'] == 'decision_presented' for e in self.events):
                raise ValueError('An actual operator decision must follow the presented decision')
            if source != 'human' or safe.get('decision') not in ('approve', 'reject') or not safe.get('actor_alias'):
                raise ValueError('Operator decision needs a human actor and explicit choice')
            self._operator_decision = safe['decision']
        elif kind == 'decision_applied':
            if self._operator_decision is None or source != 'native' or safe.get('decision') != self._operator_decision:
                raise ValueError('Applied decision must match the current operator decision')
        self.events.append({'kind': kind, 'source': source, 'evidence_ref': evidence_ref, **safe})
        return self.export()

    def export(self):
        return {'schema_version': 1, 'scenario_id': self.scenario_id,
                'complete': self.complete, 'events': [dict(event) for event in self.events]}
