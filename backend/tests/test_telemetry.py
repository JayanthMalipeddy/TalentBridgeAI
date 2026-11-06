from contextlib import contextmanager
from unittest.mock import Mock, MagicMock
import pytest
from app.services.telemetry import Telemetry
from app.errors import AppError

def test_unconfigured_telemetry_is_local_only():
    telemetry = Telemetry()
    with telemetry.observation('test') as span:
        span.update(metadata={'status':'ok'})
    assert telemetry.capability()['available'] is False

def test_sdk_failure_never_swallows_application_error():
    client = Mock()
    client.start_as_current_observation.side_effect = RuntimeError('private SDK failure')
    with pytest.raises(AppError):
        with Telemetry(client=client).observation('test'):
            raise AppError('EXPECTED', 'private input')

def test_exception_content_never_sent_to_sdk():
    client, span = Mock(), Mock()
    @contextmanager
    def observation(**kwargs):
        assert 'input' not in kwargs and 'output' not in kwargs
        yield span
    client.start_as_current_observation.side_effect = observation
    with pytest.raises(AppError):
        with Telemetry(client=client).observation('test'):
            raise AppError('EXPECTED', 'SECRET CV CONTENT')
    span.update.assert_called_once_with(level='ERROR',status_message='EXPECTED')

def test_export_failure_does_not_break_success():
    client = Mock()
    client.start_as_current_observation.return_value = MagicMock()
    client.start_as_current_observation.return_value.__enter__.side_effect = RuntimeError('offline')
    with Telemetry(client=client).observation('test'):
        pass
