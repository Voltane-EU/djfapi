from fastapi import Response
from ..schemas import Health


def get_health(response: Response) -> Health:
    from health_check.mixins import CheckMixin
    check = CheckMixin()

    plugins = check.plugins if type(check.plugins) == list else check.plugins.values()

    failures = any([not plugin.status for plugin in plugins if plugin.critical_service])
    warnings = any([not plugin.status for plugin in plugins if not plugin.critical_service])

    health = Health.parse_obj({
        'status': 'FAILURE' if failures else ('WARNING' if warnings else 'OK'),
        'checks': [
            {
                'name': plugin.__class__.__name__,
                'status': 'OK' if not plugin.errors else ('WARNING' if not plugin.critical_service else 'FAILURE'),
                'errors': [{
                    'type': error.message_type,
                    'message': error.message,
                } for error in plugin.errors],
            } for plugin in plugins
        ]
    })

    response.status_code = 500 if health.status == 'FAILURE' else 200

    return health
