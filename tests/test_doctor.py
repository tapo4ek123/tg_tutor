from types import SimpleNamespace

from tutor import doctor
from tutor.config import Settings
from tutor.provider_errors import ModelError


async def test_doctor_reports_empty_key_without_api_call(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("An empty key must not cause an API request")

    monkeypatch.setattr(doctor, "OpenAITutor", forbidden)
    result = await doctor.check(Settings(_env_file=None, openai_api_key=""))
    assert result == 1
    assert "OPENAI_API_KEY пустой" in capsys.readouterr().out


async def test_doctor_sends_synthetic_profile_and_closes_model(monkeypatch, capsys):
    instances = []

    class FakeModel:
        def __init__(self, settings, **options):
            assert options == {"timeout": 20, "max_retries": 0}
            self.closed = False
            instances.append(self)

        async def generate(self, kind, schema, payload):
            assert kind == "diagnostic"
            assert payload["goal"] == "Освоить основы Go"
            return SimpleNamespace(questions=["one", "two"])

        async def close(self):
            self.closed = True

    monkeypatch.setattr(doctor, "OpenAITutor", FakeModel)
    result = await doctor.check(Settings(_env_file=None, openai_api_key="never-print-this-key"))
    output = capsys.readouterr().out
    assert result == 0
    assert "OK: API доступен" in output
    assert "never-print-this-key" not in output
    assert instances[0].closed


async def test_doctor_reports_translated_provider_error(monkeypatch, capsys):
    class FailedModel:
        def __init__(self, *args, **kwargs):
            pass

        async def generate(self, *args):
            raise ModelError(
                "Провайдер запретил доступ",
                diagnostics={
                    "http_status": 403,
                    "provider_code": "model_access_denied",
                },
            )

        async def close(self):
            pass

    monkeypatch.setattr(doctor, "OpenAITutor", FailedModel)
    result = await doctor.check(Settings(_env_file=None, openai_api_key="secret"))
    output = capsys.readouterr().out
    assert result == 1
    assert "403" in output
    assert "model_access_denied" in output
