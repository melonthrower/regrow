"""Project an update's main contract independently of its optional next Action."""
from copy import deepcopy


def main_pair(schema, reply):
    """Keep the published schema strict; split only at local reception checks."""
    from regrow.runtime.model_transport import expand_schema
    schema = expand_schema(schema)
    props = schema.get('properties', {})
    if 'action_result' in props and 'next_action' in props:
        schema = deepcopy(schema)
        schema['properties'].pop('next_action')
        schema['required'] = [key for key in schema.get('required', []) if key != 'next_action']
        if isinstance(reply, dict):
            reply = {key: value for key, value in reply.items() if key != 'next_action'}
    elif 'proposal' in props:
        schema = deepcopy(schema)
        supplied = reply.get('proposal') if isinstance(reply, dict) else None
        for branch in schema['properties']['proposal'].get('anyOf', []):
            if 'action_result' in branch.get('properties', {}):
                projected, proposal = main_pair(branch, supplied)
                branch.clear()
                branch.update(projected)
                if isinstance(supplied, dict):
                    reply = {**reply, 'proposal': proposal}
    return schema, reply
